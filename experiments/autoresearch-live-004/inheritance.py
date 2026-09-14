from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

UPSTREAM_PIN = "228791fb499afffb54b46200aca536f79142f117"
PREDECESSOR_BASELINE = "effe44963da4d8b81ecc9be1ba3f115ac3ef2dab"
INHERITED_A = "20a0df6cc98778ffb53957d6b4fafccda3a4973e"
FREEZE_REL = Path("experiments/autoresearch-live-003/AUTORESEARCH_LIVE_003_FREEZE.json")
FREEZE_SCHEMA = "openline.autoresearch.live003-freeze.v1"


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "command failed: " + " ".join(cmd))
    return p


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=repo, check=check).stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def verify_live003_freeze(airlock_root: Path) -> dict[str, Any]:
    path = (airlock_root / FREEZE_REL).resolve()
    if not path.is_file():
        raise RuntimeError(
            "LIVE-003 frozen result is not present. Do not run LIVE-004 before AUTORESEARCH_LIVE_003_FREEZE.json is merged."
        )
    freeze = read_json(path)
    if freeze.get("schema") != FREEZE_SCHEMA:
        raise RuntimeError("unexpected LIVE-003 freeze schema")
    if freeze.get("experiment_id") != "AUTORESEARCH-LIVE-003":
        raise RuntimeError("wrong predecessor experiment")
    if freeze.get("terminal_verdict") != "CONFIRMED_LIVE_IMPROVEMENT_PROMOTED":
        raise RuntimeError("LIVE-003 did not freeze the required positive terminal verdict")
    if freeze.get("final_accepted_commit") != INHERITED_A:
        raise RuntimeError("frozen LIVE-003 accepted commit does not equal preregistered A")
    baseline = freeze.get("baseline", {})
    if baseline.get("accepted_commit") != PREDECESSOR_BASELINE:
        raise RuntimeError("frozen LIVE-003 baseline commit mismatch")
    confirmation = freeze.get("confirmation", {})
    if confirmation.get("candidate_commit") != INHERITED_A or confirmation.get("decision") != "ACCEPT":
        raise RuntimeError("frozen LIVE-003 confirmation does not bind exact A")
    protected = freeze.get("protected_integrity", {})
    if protected.get("status") != "MATCH":
        raise RuntimeError("frozen LIVE-003 protected integrity is not MATCH")
    bundle = freeze.get("artifacts", {}).get("git_bundle", {})
    bundle_sha = bundle.get("sha256")
    if not isinstance(bundle_sha, str) or len(bundle_sha) != 64:
        raise RuntimeError("frozen LIVE-003 git-bundle SHA256 is missing")
    return {"path": str(path), "sha256": sha256_file(path), "freeze": freeze, "bundle_sha256": bundle_sha}


def verify_and_materialize_a(repo: Path, bundle: Path, airlock_root: Path) -> dict[str, Any]:
    repo = repo.resolve()
    bundle = bundle.resolve()
    if not bundle.is_file():
        raise RuntimeError(f"LIVE-003 git bundle not found: {bundle}")
    freeze_info = verify_live003_freeze(airlock_root)
    actual_bundle_sha = sha256_file(bundle)
    if actual_bundle_sha != freeze_info["bundle_sha256"]:
        raise RuntimeError("LIVE-003 git bundle SHA256 does not match frozen predecessor manifest")

    head = git(repo, "rev-parse", "HEAD")
    if head != UPSTREAM_PIN:
        raise RuntimeError(f"inheritance carrier must start from exact upstream pin; observed {head}")

    run(["git", "bundle", "verify", str(bundle)], cwd=repo)
    # Unbundle writes the contained objects into this repository without choosing
    # any bundle ref as accepted state. Exact A is selected only after validation.
    run(["git", "bundle", "unbundle", str(bundle)], cwd=repo)
    git(repo, "cat-file", "-e", f"{INHERITED_A}^{{commit}}")
    git(repo, "cat-file", "-e", f"{PREDECESSOR_BASELINE}^{{commit}}")

    parent = git(repo, "rev-parse", f"{INHERITED_A}^")
    if parent != PREDECESSOR_BASELINE:
        raise RuntimeError(f"A parent mismatch: {parent}")
    if run(["git", "merge-base", "--is-ancestor", UPSTREAM_PIN, INHERITED_A], cwd=repo, check=False).returncode:
        raise RuntimeError("A does not descend from pinned autoresearch upstream")
    changed = sorted(x for x in git(repo, "diff", "--name-only", f"{PREDECESSOR_BASELINE}..{INHERITED_A}").splitlines() if x)
    if changed != ["train.py"]:
        raise RuntimeError(f"predecessor accepted delta is not train.py-only: {changed}")

    # A contains the previously installed receiver overlay. Verify every upstream
    # immutable still matches the pinned manifest before accepting the carrier.
    upstream_manifest = read_json(airlock_root / "experiments/autoresearch-gate-001/upstream_manifest.json")
    if upstream_manifest.get("commit") != UPSTREAM_PIN:
        raise RuntimeError("Airlock upstream manifest pin mismatch")
    immutable = set(upstream_manifest.get("immutable_during_run", []))
    blobs = upstream_manifest.get("blobs", {})
    checked: list[dict[str, str]] = []
    for rel in sorted(immutable):
        expected = blobs.get(rel)
        actual = git(repo, "rev-parse", f"{INHERITED_A}:{rel}")
        if actual != expected:
            raise RuntimeError(f"A immutable upstream blob mismatch for {rel}")
        checked.append({"path": rel, "blob": actual})

    git(repo, "checkout", "-q", "--detach", INHERITED_A)
    git(repo, "switch", "-q", "-c", "prince/research-b")
    git(repo, "remote", "set-url", "--push", "origin", "no_push://autoresearch-live-004")
    status = git(repo, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise RuntimeError("inherited A checkout is not clean")

    return {
        "schema": "openline.autoresearch.live004-inheritance.v1",
        "source_experiment": "AUTORESEARCH-LIVE-003",
        "source_terminal_verdict": "CONFIRMED_LIVE_IMPROVEMENT_PROMOTED",
        "predecessor_freeze_manifest": freeze_info["path"],
        "predecessor_freeze_manifest_sha256": freeze_info["sha256"],
        "carrier_git_bundle": str(bundle),
        "carrier_git_bundle_sha256": actual_bundle_sha,
        "upstream_pin": UPSTREAM_PIN,
        "predecessor_baseline_commit": PREDECESSOR_BASELINE,
        "inherited_a_commit": INHERITED_A,
        "inherited_a_tree": git(repo, "rev-parse", f"{INHERITED_A}^{{tree}}"),
        "inherited_a_train_blob": git(repo, "rev-parse", f"{INHERITED_A}:train.py"),
        "predecessor_delta_paths": changed,
        "immutable_upstream_blobs_checked": checked,
        "worktree_clean": True,
        "push_url": git(repo, "remote", "get-url", "--push", "origin"),
    }
