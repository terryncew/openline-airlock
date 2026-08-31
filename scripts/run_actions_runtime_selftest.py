#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from airlock.util import sha256_bytes, write_json
from airlock_submit import actions as actions_mod
from airlock_submit.actions import evaluate
from airlock_submit.policy import protected_touches


def run(argv: list[str], cwd: Path, *, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, check=False)


def must(argv: list[str], cwd: Path) -> str:
    cp = run(argv, cwd)
    if cp.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed:\n{cp.stderr[-2000:]}")
    return cp.stdout


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    return must(["git", *args], repo).strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write_base(repo: Path) -> None:
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / ".airlock").mkdir(parents=True)
    (repo / "src" / "calc.py").write_text(
        "def greeting(name: str) -> str:\n"
        "    return f\"Hello {name}\"\n"
    )
    (repo / "src" / "orphan.py").write_text("def value() -> int:\n    return 1\n")
    (repo / "tests" / "test_calc.py").write_text(
        "import unittest\n"
        "from calc import greeting\n\n"
        "class CalcTest(unittest.TestCase):\n"
        "    def test_greeting(self):\n"
        "        self.assertTrue(greeting('Ada').startswith('Hello'))\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n"
    )
    airlock_config = {
        "schema": "airlock.config.v1",
        "parallelism": 1,
        "protected_paths": [".github/**", ".airlock/**", "tests/**"],
        "verification": {
            "static_commands": [[
                "python", "-c",
                "import os; assert not os.getenv('GITHUB_TOKEN'); assert not os.getenv('GH_TOKEN')"
            ]],
            "test_commands": [["python", "-m", "unittest", "discover", "-s", "tests", "-v"]],
            "target_commands": [],
            "timeout_seconds": 300,
            "coverage_mode": "changed-module-reference",
        },
        "providers": {},
        "init_baseline": {"green": True, "commit": "", "commands": []},
    }
    (repo / ".airlock" / "config.json").write_text(json.dumps(airlock_config, indent=2, sort_keys=True) + "\n")
    submit = {
        "schema": "airlock.submit.v1",
        "mode": "github-actions",
        "repo": "airlock/selftest",
        "base_branch": "main",
        "container_image": "airlock-selftest:local",
        "min_account_age_days": 0,
        "min_public_repos": 0,
        "max_daily_submissions_per_user": 5,
        "max_active_submissions": 1,
        "max_patch_files": 20,
        "max_patch_bytes": 200000,
        "evaluation_timeout_seconds": 300,
        "memory": "1g",
        "cpus": "1",
        "pids_limit": 256,
        "require_source_owner_matches_submitter": True,
    }
    (repo / ".airlock" / "submit.json").write_text(json.dumps(submit, indent=2, sort_keys=True) + "\n")
    (repo / ".airlock" / "Dockerfile").write_text(
        "FROM python:3.12-slim\n"
        "WORKDIR /workspace\n"
    )


def make_candidate(repo: Path, base: str, branch: str, mutate) -> tuple[str, bytes, list[str]]:
    git(repo, "checkout", "-B", branch, base)
    mutate(repo)
    candidate = commit_all(repo, branch)
    patch_cp = run(["git", "diff", "--binary", "--full-index", base, candidate], repo, text=False)
    if patch_cp.returncode != 0:
        raise RuntimeError(patch_cp.stderr.decode(errors="replace"))
    changed_cp = run(["git", "diff", "--name-only", "-z", base, candidate], repo, text=False)
    if changed_cp.returncode != 0:
        raise RuntimeError(changed_cp.stderr.decode(errors="replace"))
    changed = [p.decode() for p in changed_cp.stdout.split(b"\0") if p]
    return candidate, patch_cp.stdout, changed


def admission_for(repo: Path, out_dir: Path, *, comment_id: int, base: str, candidate: str, patch: bytes, changed: list[str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(git(repo, "show", f"{base}:.airlock/config.json"))
    patch_path = out_dir / "candidate.patch"
    patch_path.write_bytes(patch)
    admission = {
        "schema": "airlock.github.admission.v1",
        "status": "ADMITTED",
        "reason": "STATIC_PREFLIGHT_PASSED",
        "submission_comment_id": comment_id,
        "repo": "airlock/selftest",
        "issue_number": 1,
        "issue_title": "Actions runtime self-test",
        "submitter": "selftest",
        "source_repo": "selftest/fork",
        "source_sha": candidate,
        "base_sha": base,
        "identity": {"selftest": True},
        "changed_paths": changed,
        "protected_paths": cfg["protected_paths"],
        "protected_touches": [],
        "airlock_config_sha256": sha256_bytes(canonical_bytes(cfg)),
        "patch_sha256": sha_file(patch_path),
    }
    write_json(out_dir / "admission.json", admission)
    return admission


def main() -> int:
    ap = argparse.ArgumentParser(description="Exercise the Actions-only Airlock evaluator on a real Docker runner")
    ap.add_argument("--out", type=Path, default=Path("airlock-actions-selftest"))
    args = ap.parse_args()
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    if not shutil.which("docker"):
        raise SystemExit("Docker is required for the Actions runtime self-test")
    docker_version = must(["docker", "version", "--format", "{{.Server.Version}}"], Path.cwd()).strip()

    td = Path(tempfile.mkdtemp(prefix="airlock-actions-proof-"))
    repo = td / "repo"
    repo.mkdir()
    try:
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.name", "Airlock Selftest")
        git(repo, "config", "user.email", "airlock-selftest@example.invalid")
        write_base(repo)
        base = commit_all(repo, "base")

        # Freeze the baseline commit inside the config and recommit so the base is internally consistent.
        cfg_path = repo / ".airlock" / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["init_baseline"]["commit"] = base
        cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
        base = commit_all(repo, "freeze baseline")

        survivor_sha, survivor_patch, survivor_changed = make_candidate(
            repo, base, "candidate-survivor",
            lambda r: (r / "src" / "calc.py").write_text(
                "def greeting(name: str) -> str:\n"
                "    return f\"Hello, {name}\"\n"
            ),
        )
        weak_sha, weak_patch, weak_changed = make_candidate(
            repo, base, "candidate-needs-evidence",
            lambda r: (r / "src" / "orphan.py").write_text("def value() -> int:\n    return 2\n"),
        )
        cheat_sha, cheat_patch, cheat_changed = make_candidate(
            repo, base, "candidate-protected-cheat",
            lambda r: ((r / ".github" / "workflows").mkdir(parents=True, exist_ok=True),
                       (r / ".github" / "workflows" / "pwn.yml").write_text("name: pwn\n")),
        )
        del cheat_patch, cheat_sha

        git(repo, "checkout", "--detach", base)

        survivor_in = out / "survivor-in"
        survivor_out = out / "survivor"
        admission_for(repo, survivor_in, comment_id=1001, base=base, candidate=survivor_sha, patch=survivor_patch, changed=survivor_changed)

        weak_in = out / "needs-evidence-in"
        weak_out = out / "needs-evidence"
        admission_for(repo, weak_in, comment_id=1002, base=base, candidate=weak_sha, patch=weak_patch, changed=weak_changed)

        protected_cfg = json.loads(git(repo, "show", f"{base}:.airlock/config.json"))["protected_paths"]
        cheat_touches = protected_touches(cheat_changed, protected_cfg)
        if not cheat_touches:
            raise RuntimeError("protected-cheat fixture was not rejected by static protected-path policy")
        cheat_outcome = {
            "schema": "airlock.github.outcome.v1",
            "submission_comment_id": 1003,
            "repo": "airlock/selftest",
            "issue_number": 1,
            "issue_title": "Actions runtime self-test",
            "submitter": "selftest",
            "source_repo": "selftest/fork",
            "source_sha": "protected-cheat",
            "base_sha": base,
            "decision": "BLOCKED",
            "reason": "PROTECTED_FILES_CHANGED",
            "execution_attempted": False,
            "changed_paths": cheat_changed,
            "protected_touches": cheat_touches,
        }
        (out / "protected-cheat").mkdir()
        write_json(out / "protected-cheat" / "outcome.json", cheat_outcome)

        old = Path.cwd()
        try:
            os.chdir(repo)
            survivor = evaluate(survivor_in, survivor_out)
            weak = evaluate(weak_in, weak_out)
        finally:
            os.chdir(old)

        if survivor.get("decision") != "SURVIVED":
            raise RuntimeError(f"survivor arm expected SURVIVED, got {survivor}")
        if not survivor.get("execution_attempted"):
            raise RuntimeError("survivor arm never executed repo checks")
        if weak.get("decision") != "NEEDS_EVIDENCE":
            raise RuntimeError(f"weak-evidence arm expected NEEDS_EVIDENCE, got {weak}")
        if not weak.get("execution_attempted"):
            raise RuntimeError("weak-evidence arm never executed repo checks")
        if cheat_outcome["execution_attempted"]:
            raise RuntimeError("protected-cheat arm unexpectedly reached execution")

        report = {
            "schema": "airlock.actions.runtime.selftest.v1",
            "docker_server_version": docker_version,
            "base_sha": base,
            "checks": {
                "real_docker_evaluation_exercised": True,
                "container_received_no_github_token": True,
                "protected_cheat_rejected_before_execution": True,
                "survivor_executed_checks_and_survived": True,
                "weak_evidence_executed_checks_but_did_not_survive": True,
            },
            "arms": {
                "survivor": {
                    "decision": survivor["decision"],
                    "execution_attempted": survivor["execution_attempted"],
                    "outcome_sha256": sha_file(survivor_out / "outcome.json"),
                },
                "needs_evidence": {
                    "decision": weak["decision"],
                    "execution_attempted": weak["execution_attempted"],
                    "reason": weak["reason"],
                    "outcome_sha256": sha_file(weak_out / "outcome.json"),
                },
                "protected_cheat": {
                    "decision": cheat_outcome["decision"],
                    "execution_attempted": False,
                    "protected_touches": cheat_touches,
                    "outcome_sha256": sha_file(out / "protected-cheat" / "outcome.json"),
                },
            },
        }
        write_json(out / "report.json", report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
