#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from airlock import ci, ci_doctor
from airlock.config import load as load_config
from airlock.gitops import changed_paths, git, head
from airlock.sandbox import WorktreeSandbox
from airlock.sieve import protected_files_check, run_checks, sufficiency_check
from airlock.util import canonical_json_bytes, sha256_bytes, sha256_file
from airlock.verification import sign, verify_signature


SCHEMA = "airlock.ci-live-repair-001.result.v1"
ALLOWED_CHANGED_PATH = "experiments/ci-code-path-001/fixture/src/retry_policy.py"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _only(paths: list[Path], what: str) -> Path:
    if len(paths) != 1:
        raise RuntimeError(f"expected exactly one {what}, found {len(paths)}")
    return paths[0]


def _ci_receipt_path(repo: Path, run_id: int, attempt: int) -> Path:
    candidates = sorted((repo / ".airlock" / "ci").glob(f"*-{run_id}-attempt-{attempt}.json"))
    return _only(candidates, "Recorder receipt")


def _doctor_receipt_path(repo: Path) -> Path:
    candidates = sorted((repo / ".airlock" / "doctor").glob("*/doctor.json"))
    return _only(candidates, "Doctor receipt")


def _ordinary_evaluation(repo: Path, base: str, candidate: str, paths: list[str]) -> dict[str, Any]:
    config = load_config(repo / ".airlock" / "config.json")
    verification = config.get("verification") or {}
    timeout = int(verification.get("timeout_seconds", 1200))
    checks: list[dict[str, Any]] = [protected_files_check(paths, list(config.get("protected_paths", [])))]
    if checks[0].get("status") != "PASS":
        return {"status": "BLOCKED", "reason": "PROTECTED_FILES_CHANGED", "checks": checks}

    with WorktreeSandbox(repo, candidate, prefix="airlock-ci-live-repair-eval-") as worktree:
        for kind, commands in (
            ("target", verification.get("target_commands", [])),
            ("static", verification.get("static_commands", [])),
            ("regression", verification.get("test_commands", [])),
        ):
            check = run_checks(worktree, list(commands or []), timeout=timeout, kind=kind)
            checks.append(check)
            if check.get("status") != "PASS":
                return {"status": "BLOCKED", "reason": f"{kind.upper()}_FAILED", "checks": checks}

    sufficiency = sufficiency_check(
        repo,
        base,
        paths,
        [],
        list(verification.get("target_commands", [])),
    )
    checks.append(sufficiency)
    if sufficiency.get("status") != "PASS":
        return {"status": "NEEDS_EVIDENCE", "reason": sufficiency.get("basis"), "checks": checks}
    return {"status": "SURVIVED", "reason": "ALL_CONFIGURED_CHECKS_PASSED", "checks": checks}


def _doctor_valid(record: dict[str, Any], key: bytes, scratch: Path) -> bool:
    path = scratch / "doctor-verify.json"
    path.write_bytes(canonical_json_bytes(record) + b"\n")
    return bool(ci_doctor.verify_doctor_receipt(path, key).get("valid"))


def verify_live_run(
    repo: Path,
    *,
    run_id: int,
    run_attempt: int,
    head_sha: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    repo = repo.resolve()
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    key_path = repo / ".airlock" / "verification.key"
    if not key_path.is_file():
        raise RuntimeError("local Airlock verification key is missing")
    key = key_path.read_bytes()

    ci_path = _ci_receipt_path(repo, run_id, run_attempt)
    doctor_path = _doctor_receipt_path(repo)
    ci_record = _load_json(ci_path)
    doctor_record = _load_json(doctor_path)
    if not ci.verify_ci_receipt(ci_record, key).get("valid"):
        raise RuntimeError("Recorder receipt failed integrity verification")
    scratch = artifact_dir / ".scratch"
    scratch.mkdir(exist_ok=True)
    if not _doctor_valid(doctor_record, key, scratch):
        raise RuntimeError("Doctor receipt failed integrity verification")

    ci_payload = ci_record["payload"]
    doctor_payload = doctor_record["payload"]
    run = ci_payload.get("run") or {}
    authorization = ci_payload.get("authorization") or {}
    findings = [row for row in ci_payload.get("findings", []) if isinstance(row, dict) and row.get("role") == "PRIMARY"]
    doctor_authority = doctor_payload.get("authority") or {}
    candidate = doctor_payload.get("candidate") or {}
    candidate_commit = str(candidate.get("commit") or "")
    ready_branch = str(candidate.get("ready_branch") or "")
    expected_head = head_sha.lower()

    if int(run.get("run_id") or 0) != run_id or int(run.get("run_attempt") or 0) != run_attempt:
        raise RuntimeError("Recorder receipt does not bind the requested run attempt")
    if str(run.get("provider_run_head_sha") or "").lower() != expected_head:
        raise RuntimeError("Recorder receipt head SHA does not match the failed run")
    if ci_payload.get("disposition") != "CODE_REPAIR_ALLOWED" or authorization.get("code_repair") is not True:
        raise RuntimeError("live Recorder did not earn CODE_REPAIR_ALLOWED")
    if not findings or any(row.get("cause_class") != "CODE_REGRESSION" for row in findings):
        raise RuntimeError("live Recorder primary findings are not exclusively code regressions")
    if any(row.get("reason_code") != "TEST_FAILURE" for row in findings):
        raise RuntimeError("live Recorder did not bind the failure to TEST_FAILURE")
    if authorization.get("retry") is True or any(authorization.get(k) is True for k in ("merge", "deployment", "baseline_change", "workflow_repair")):
        raise RuntimeError("Recorder receipt manufactured forbidden authority")

    if doctor_payload.get("decision") != "READY_FOR_REVIEW" or doctor_payload.get("worker_started") is not True:
        raise RuntimeError("live Doctor did not earn READY_FOR_REVIEW")
    if str((doctor_payload.get("ci_run") or {}).get("repair_base") or "").lower() != expected_head:
        raise RuntimeError("Doctor repair base does not match the failed run head")
    if head(repo).lower() != expected_head:
        raise RuntimeError("Doctor moved the trusted checkout HEAD")
    if not candidate_commit or not ready_branch:
        raise RuntimeError("Doctor did not preserve a local ready-for-review candidate")
    if git(repo, "rev-parse", ready_branch).lower() != candidate_commit.lower():
        raise RuntimeError("ready branch does not resolve to the sealed candidate commit")
    for forbidden in ("retry", "merge", "deployment", "baseline_change", "workflow_repair", "github_write"):
        if doctor_authority.get(forbidden) is True:
            raise RuntimeError(f"Doctor receipt unexpectedly grants {forbidden} authority")

    paths = changed_paths(repo, expected_head, candidate_commit)
    if paths != [ALLOWED_CHANGED_PATH]:
        raise RuntimeError(f"candidate escaped the frozen dogfood scope: {paths}")

    ordinary = _ordinary_evaluation(repo, expected_head, candidate_commit, paths)
    if ordinary.get("status") != "SURVIVED":
        raise RuntimeError("candidate failed independent ordinary Airlock evaluation")

    patch_path = artifact_dir / "candidate.patch"
    cp = subprocess.run(
        ["git", "diff", "--binary", "--full-index", f"{expected_head}..{candidate_commit}"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0 or not cp.stdout:
        raise RuntimeError("could not preserve the admitted candidate patch")
    patch_path.write_bytes(cp.stdout)

    result_payload = {
        "schema": SCHEMA,
        "source_run": {
            "repository": run.get("repository"),
            "run_id": run_id,
            "run_attempt": run_attempt,
            "head_sha": expected_head,
            "workflow_name": run.get("workflow_name"),
            "event": run.get("event"),
        },
        "route": {
            "recorder_disposition": ci_payload.get("disposition"),
            "doctor_decision": doctor_payload.get("decision"),
            "ordinary_evaluation": ordinary,
        },
        "candidate": {
            "commit": candidate_commit,
            "ready_branch": ready_branch,
            "changed_paths": paths,
            "patch_sha256": sha256_file(patch_path),
        },
        "receipts": {
            "ci_sha256": sha256_file(ci_path),
            "doctor_sha256": sha256_file(doctor_path),
            "verification_key_sha256": sha256_bytes(key),
        },
        "authority": {
            "github_write": False,
            "retry": False,
            "merge": False,
            "deployment": False,
            "workflow_repair": False,
            "baseline_change": False,
        },
        "invariants": {
            "exact_run_attempt_bound": True,
            "code_repair_authority_earned": True,
            "one_doctor_worker_started": True,
            "trusted_head_unchanged": True,
            "candidate_scope_exact": True,
            "ordinary_evaluation_survived": True,
            "github_write_authority_absent": True,
        },
        "verdict": "LIVE_CODE_REPAIR_PATH_EARNED",
    }
    signed = sign(result_payload, key)
    if not verify_signature(signed, key):
        raise RuntimeError("live dogfood result failed local integrity verification")
    result_path = artifact_dir / "CI_LIVE_REPAIR_001_RESULT.json"
    result_path.write_bytes(canonical_json_bytes(signed) + b"\n")
    (artifact_dir / "CI_LIVE_REPAIR_001_RESULT.sha256").write_text(sha256_file(result_path) + "\n")
    shutil.copy2(ci_path, artifact_dir / "ci-receipt.json")
    shutil.copy2(doctor_path, artifact_dir / "doctor-receipt.json")
    shutil.rmtree(scratch, ignore_errors=True)
    return {"valid": True, "result_path": result_path, "patch_path": patch_path, "payload": result_payload}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-run-attempt", type=int, required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_live_run(
            Path(args.repo),
            run_id=args.source_run_id,
            run_attempt=args.source_run_attempt,
            head_sha=args.source_head_sha,
            artifact_dir=Path(args.artifact_dir),
        )
    except Exception as exc:
        print(f"CI-LIVE-REPAIR-001: FAIL — {exc}")
        return 1
    print("CI-LIVE-REPAIR-001: PASS")
    print(f"Verdict: {result['payload']['verdict']}")
    print(f"Result: {result['result_path']}")
    print(f"Candidate patch: {result['patch_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
