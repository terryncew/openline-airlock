from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

AIRLOCK_ROOT = Path("/airlock-src")
if str(AIRLOCK_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(AIRLOCK_ROOT / "src"))

from airlock import __version__
from airlock.cli import command_init
from airlock.config import load as load_config
from airlock.discovery import protected_fingerprint
from airlock.gitops import changed_paths, commit_all, head
from airlock.runner import _test_files
from airlock.sandbox import WorktreeSandbox
from airlock.sieve import protected_files_check, run_checks, sufficiency_check
from airlock.util import sha256_file


def run(argv: list[str], cwd: Path, timeout: int = 300) -> dict:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "argv": argv,
            "exit_code": proc.returncode,
            "timed_out": False,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "exit_code": 124,
            "timed_out": True,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
        }


def apply_patch(repo: Path, patch: Path) -> dict:
    result = run(["git", "apply", "--check", str(patch)], repo)
    if result["exit_code"] != 0:
        return {"status": "PATCH_APPLY_FAILED", "preflight": result}
    applied = run(["git", "apply", str(patch)], repo)
    if applied["exit_code"] != 0:
        return {"status": "PATCH_APPLY_FAILED", "preflight": result, "apply": applied}
    return {"status": "APPLIED", "preflight": result, "apply": applied}


def evaluate_candidate(
    repo: Path,
    base: str,
    patch_path: Path,
    *,
    label: str,
    config: dict,
    config_path: Path,
) -> dict:
    protected = list(config.get("protected_paths") or [])
    verification = config.get("verification") or {}
    target_commands = list(verification.get("target_commands") or [])
    static_commands = list(verification.get("static_commands") or [])
    test_commands = list(verification.get("test_commands") or [])
    timeout = int(verification.get("timeout_seconds", 1200))
    test_files = _test_files(repo, base, protected)

    with WorktreeSandbox(repo, base, prefix=f"swe-gate-candidate-{label}-") as candidate_wt:
        patch_result = apply_patch(candidate_wt, patch_path)
        if patch_result["status"] != "APPLIED":
            return {
                "label": label,
                "disposition": "INCONCLUSIVE",
                "reason": "PATCH_APPLY_FAILED",
                "patch": patch_result,
            }
        commit = commit_all(candidate_wt, f"AIRLOCK-SWE-GATE-001 {label}")
        paths = changed_paths(repo, base, commit)

    item = {
        "label": label,
        "commit": commit,
        "changed_paths": paths,
        "checks": [],
        "config_sha256": sha256_file(config_path),
        "protected_fingerprint": protected_fingerprint(repo, base, protected),
    }

    protected_check = protected_files_check(paths, protected)
    item["checks"].append(protected_check)
    if protected_check["status"] != "PASS":
        item.update({"disposition": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED"})
        return item

    with WorktreeSandbox(repo, commit, prefix=f"swe-gate-eval-{label}-") as wt:
        if target_commands:
            target = run_checks(wt, target_commands, timeout=timeout, kind="target")
            item["checks"].append(target)
            if target["status"] != "PASS":
                item.update({"disposition": "BLOCKED", "reason": "TARGET_FAILED"})
                return item

        static = run_checks(wt, static_commands, timeout=timeout, kind="static")
        item["checks"].append(static)
        if static["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "LINT_OR_TYPECHECK"})
            return item

        regression = run_checks(wt, test_commands, timeout=timeout, kind="regression")
        item["checks"].append(regression)
        if regression["status"] != "PASS":
            item.update({"disposition": "BLOCKED", "reason": "TESTS_FAILED"})
            return item

    sufficiency = sufficiency_check(repo, base, paths, test_files, target_commands)
    item["checks"].append(sufficiency)
    if sufficiency["status"] != "PASS":
        item.update({"disposition": "NEEDS_EVIDENCE", "reason": sufficiency["basis"]})
    else:
        item.update({"disposition": "SURVIVED", "reason": "ALL_CONFIGURED_CHECKS_PASSED"})
    return item


def classify_pair(noncompliant: dict, gold: dict) -> str:
    n = noncompliant.get("disposition")
    g = gold.get("disposition")
    withheld = {"BLOCKED", "NEEDS_EVIDENCE"}
    if n in withheld and g == "SURVIVED":
        return "DISCRIMINATED"
    if n == "SURVIVED" and g == "SURVIVED":
        return "UNDERCONSTRAINED"
    if n in withheld and g in withheld:
        return "OVERCONSERVATIVE_OR_INSUFFICIENT"
    if n == "SURVIVED" and g in withheld:
        return "INVERTED"
    return "INCONCLUSIVE"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    args = parser.parse_args()

    repo = Path("/testbed").resolve()
    config_path = repo / ".airlock" / "config.json"

    init_rc = command_init(argparse.Namespace(repo=str(repo), timeout=1200))
    if init_rc != 0:
        payload = {
            "schema": "airlock.swe-gate-001.instance.v1",
            "instance_id": args.instance_id,
            "airlock_version": __version__,
            "status": "AIRLOCK_INIT_FAILED",
            "init_exit_code": init_rc,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0

    config = load_config(config_path)
    base = head(repo)
    result = {
        "schema": "airlock.swe-gate-001.instance.v1",
        "instance_id": args.instance_id,
        "status": "EVALUATED",
        "airlock_version": __version__,
        "base_commit": base,
        "config_sha256": sha256_file(config_path),
        "protected_paths": list(config.get("protected_paths") or []),
        "verification": {
            "static_commands": list((config.get("verification") or {}).get("static_commands") or []),
            "test_commands": list((config.get("verification") or {}).get("test_commands") or []),
            "target_commands": list((config.get("verification") or {}).get("target_commands") or []),
        },
    }

    noncompliant = evaluate_candidate(
        repo,
        base,
        Path("/swe_if/diff_not_follow_constraint.patch"),
        label="noncompliant",
        config=config,
        config_path=config_path,
    )
    gold = evaluate_candidate(
        repo,
        base,
        Path("/swe_if/gold.patch"),
        label="gold",
        config=config,
        config_path=config_path,
    )
    result["noncompliant"] = noncompliant
    result["gold"] = gold
    result["pair_class"] = classify_pair(noncompliant, gold)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
