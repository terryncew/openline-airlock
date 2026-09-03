#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterator

from airlock import ci, ci_doctor
from airlock.config import load as load_config
from airlock.gitops import changed_paths, git, head, tracked_files
from airlock.sandbox import WorktreeSandbox
from airlock.sieve import protected_files_check, run_checks, sufficiency_check
from airlock.util import canonical_json_bytes, matches_any, run, sha256_bytes, sha256_file, worktree_env
from airlock.verification import sign, verify_signature


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = HERE / "fixture"
PREREG = HERE / "CI_CODE_PATH_001_PREREGISTRATION.json"
KEY_PATH = HERE / "CI_CODE_PATH_001_VERIFICATION.key"
RESULT_NAME = "CI_CODE_PATH_001_RESULT.json"
PATCH_NAME = "CI_CODE_PATH_001_SURVIVOR.patch"
REPOSITORY = "openline/ci-code-path-001-fixture"
RUN_ID = 1001
JOB_ID = 2001
FIXED_BASE_DATE = "2026-09-03T00:00:00+00:00"
FIXED_CANDIDATE_DATE = "2026-09-03T00:01:00+00:00"


def _key(path: Path = KEY_PATH) -> bytes:
    token = path.read_text().strip()
    value = bytes.fromhex(token)
    if len(value) != 32:
        raise RuntimeError("CI-CODE-PATH-001 verification key must decode to 32 bytes")
    return value


def _tree_sha(path: Path) -> str:
    rows = []
    files = (
        p for p in path.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )
    for file in sorted(files, key=lambda p: p.relative_to(path).as_posix()):
        rows.append({
            "path": file.relative_to(path).as_posix(),
            "sha256": sha256_file(file),
            "size": file.stat().st_size,
        })
    return sha256_bytes(canonical_json_bytes(rows))


def _git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _git_commit_exists(commit: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def verify_frozen_inputs() -> dict[str, Any]:
    prereg = json.loads(PREREG.read_text())
    if prereg.get("schema") != "airlock.ci-code-path-001.preregistration.v1":
        raise RuntimeError("unexpected CI-CODE-PATH-001 preregistration schema")
    frozen = prereg.get("frozen_sha256") or {}
    observed = {
        "fixture_tree": _tree_sha(FIXTURE),
        "runner": sha256_file(Path(__file__)),
        "src/airlock/ci.py": sha256_file(ROOT / "src/airlock/ci.py"),
        "src/airlock/ci_doctor.py": sha256_file(ROOT / "src/airlock/ci_doctor.py"),
        "src/airlock/ci_rules.v1.json": sha256_file(ROOT / "src/airlock/ci_rules.v1.json"),
        "src/airlock/sieve.py": sha256_file(ROOT / "src/airlock/sieve.py"),
    }
    mismatches = {name: {"expected": frozen.get(name), "observed": value} for name, value in observed.items() if frozen.get(name) != value}
    if mismatches:
        raise RuntimeError("frozen CI-CODE-PATH-001 input mismatch: " + json.dumps(mismatches, sort_keys=True))
    product_base = str(prereg.get("product_base_commit") or "")
    current = git(ROOT, "rev-parse", "HEAD")
    if current == product_base:
        lineage = "EXACT_BASE"
    elif not _git_commit_exists(product_base):
        # GitHub's default shallow checkout can omit the parent object. Exact
        # component hashes remain the binding when ancestry is unavailable.
        lineage = "BASE_OBJECT_UNAVAILABLE_IN_SHALLOW_CHECKOUT"
    elif _git_is_ancestor(product_base, current):
        lineage = "DESCENDANT"
    else:
        raise RuntimeError("current tree is not descended from the preregistered product base")
    return {
        "preregistration": prereg,
        "observed_sha256": observed,
        "current_product_commit": current,
        "product_lineage": lineage,
    }


def _git_commit(repo: Path, message: str, date: str) -> str:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Airlock Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@airlock.local",
        "GIT_COMMITTER_NAME": "Airlock Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@airlock.local",
        "GIT_AUTHOR_DATE": date,
        "GIT_COMMITTER_DATE": date,
    })
    cp = subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or "fixture commit failed")
    return git(repo, "rev-parse", "HEAD")


def _make_repo(parent: Path, key: bytes) -> tuple[Path, str]:
    repo = parent / "repo"
    shutil.copytree(FIXTURE, repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Airlock Fixture")
    git(repo, "config", "user.email", "fixture@airlock.local")
    git(repo, "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
    (repo / ".airlock/verification.key").write_bytes(key)
    git(repo, "add", "-A")
    base = _git_commit(repo, "fixture: failing retry boundary", FIXED_BASE_DATE)
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("fixture base is not clean")
    return repo, base


class FixtureActionsReadClient:
    """Provider-shaped read adapter backed by one real local failing process."""

    def __init__(self, *, base: str, log: bytes, workflow: bytes):
        self.base = base
        self.log = log
        self.workflow = workflow
        self.calls: list[str] = []

    def run(self, repo: str, run_id: int) -> dict[str, Any]:
        self.calls.append("run")
        return {
            "id": run_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": self.base,
            "head_branch": "main",
            "event": "push",
            "path": ".github/workflows/ci.yml",
            "workflow_id": 3001,
            "name": "CI code path fixture",
            "pull_requests": [],
            "created_at": "2026-09-03T00:02:00Z",
            "run_started_at": "2026-09-03T00:02:01Z",
            "updated_at": "2026-09-03T00:02:04Z",
        }

    def jobs(self, repo: str, run_id: int, attempt: int) -> list[dict[str, Any]]:
        self.calls.append("jobs")
        return [{
            "id": JOB_ID,
            "name": "test",
            "status": "completed",
            "conclusion": "failure",
            "labels": ["ubuntu-24.04"],
            "started_at": "2026-09-03T00:02:01Z",
            "completed_at": "2026-09-03T00:02:04Z",
            "steps": [
                {
                    "number": 1,
                    "name": "Set up job",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-09-03T00:02:01Z",
                    "completed_at": "2026-09-03T00:02:02Z",
                },
                {
                    "number": 2,
                    "name": "Run unit tests",
                    "status": "completed",
                    "conclusion": "failure",
                    "started_at": "2026-09-03T00:02:02Z",
                    "completed_at": "2026-09-03T00:02:04Z",
                },
            ],
            "check_run_url": None,
        }]

    def workflow_file(self, repo: str, path: str | None, ref: str) -> dict[str, Any]:
        self.calls.append("workflow_file")
        return {"available": True, "bytes": self.workflow}

    def job_log(self, repo: str, job_id: int) -> dict[str, Any]:
        self.calls.append("job_log")
        return {"available": True, "bytes": self.log}

    def annotations(self, repo: str, check_run_url: str | None) -> dict[str, Any]:
        self.calls.append("annotations")
        return {"available": False, "reason": "NO_CHECK_RUN_ID"}


@contextmanager
def _doctor_environment() -> Iterator[None]:
    names = (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "SSH_AUTH_SOCK",
        "OPENLINE_RELEASE_KEY",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_DATE",
    )
    old = {name: os.environ.get(name) for name in names}
    os.environ.update({
        "GH_TOKEN": "must-not-reach-worker",
        "GITHUB_TOKEN": "must-not-reach-worker",
        "SSH_AUTH_SOCK": "/must/not/reach/worker",
        "OPENLINE_RELEASE_KEY": "must-not-reach-worker",
        "GIT_AUTHOR_DATE": FIXED_CANDIDATE_DATE,
        "GIT_COMMITTER_DATE": FIXED_CANDIDATE_DATE,
    })
    try:
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _ordinary_evaluation(repo: Path, base: str, candidate: str, paths: list[str]) -> dict[str, Any]:
    config = load_config(repo / ".airlock/config.json")
    verification = config["verification"]
    timeout = int(verification.get("timeout_seconds", 1200))
    protected = list(config["protected_paths"])
    checks: list[dict[str, Any]] = [protected_files_check(paths, protected)]
    with WorktreeSandbox(repo, candidate, prefix="airlock-ci-code-path-eval-") as worktree:
        for kind, commands in (
            ("target", verification.get("target_commands", [])),
            ("static", verification.get("static_commands", [])),
            ("regression", verification.get("test_commands", [])),
        ):
            check = run_checks(worktree, list(commands or []), timeout=timeout, kind=kind)
            checks.append(check)
            if check.get("status") != "PASS":
                return {"status": "BLOCKED", "reason": f"{kind.upper()}_FAILED", "checks": checks}
    test_patterns = [pattern for pattern in protected if pattern.startswith(("tests/", "test/", "spec/", "__tests__/"))]
    test_files = [path for path in tracked_files(repo, base) if matches_any(path, test_patterns)]
    coverage = sufficiency_check(repo, base, paths, test_files, list(verification.get("target_commands", [])))
    checks.append(coverage)
    if coverage.get("status") != "PASS":
        return {"status": "NEEDS_EVIDENCE", "reason": coverage.get("basis"), "checks": checks}
    return {"status": "SURVIVED", "reason": "ALL_CONFIGURED_CHECKS_PASSED", "checks": checks}


def _doctor_record_valid(record: dict[str, Any], key: bytes) -> bool:
    with tempfile.TemporaryDirectory(prefix="airlock-ci-code-path-verify-") as td:
        path = Path(td) / "doctor.json"
        path.write_bytes(canonical_json_bytes(record) + b"\n")
        return bool(ci_doctor.verify_doctor_receipt(path, key).get("valid"))


def run_dogfood(out_dir: Path) -> dict[str, Any]:
    frozen = verify_frozen_inputs()
    key = _key()
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="airlock-ci-code-path-001-") as td:
        repo, base = _make_repo(Path(td), key)
        config = load_config(repo / ".airlock/config.json")
        test_command = list(config["verification"]["test_commands"][0])
        baseline_check = run(test_command, repo, env=worktree_env(repo), timeout=30)
        baseline_log = (baseline_check["stdout"] + "\n" + baseline_check["stderr"]).encode()
        if baseline_check["exit_code"] == 0 or b"AssertionError" not in baseline_log:
            raise RuntimeError("fixture did not produce the required real assertion failure")

        client = FixtureActionsReadClient(
            base=base,
            log=baseline_log,
            workflow=(repo / ".github/workflows/ci.yml").read_bytes(),
        )
        recorder_path = repo / ".airlock/ci/fixture-run.json"
        recorded = ci.record_run(
            str(RUN_ID), repo_arg=REPOSITORY, cwd=repo, out=recorder_path, client=client
        )
        recorder = recorded["receipt"]
        recorder_payload = recorder["payload"]

        before = {
            "head": head(repo),
            "source_sha256": sha256_file(repo / "src/retry_policy.py"),
            "git_config_sha256": sha256_file(repo / ".git/config"),
            "origin": git(repo, "remote", "get-url", "origin"),
            "tracked_worktree_changes": git(repo, "status", "--porcelain", "--untracked-files=no"),
        }
        with _doctor_environment():
            doctor_result = ci_doctor.run_doctor(
                repo, recorder_path, model="fixture-worker", budget=0.01
            )
        doctor = json.loads(doctor_result["receipt_path"].read_text())
        doctor_payload = doctor["payload"]
        candidate = str(doctor_result.get("candidate_commit") or "")
        paths = changed_paths(repo, base, candidate) if candidate else []

        after = {
            "head": head(repo),
            "source_sha256": sha256_file(repo / "src/retry_policy.py"),
            "git_config_sha256": sha256_file(repo / ".git/config"),
            "origin": git(repo, "remote", "get-url", "origin"),
            "tracked_worktree_changes": git(repo, "status", "--porcelain", "--untracked-files=no"),
        }
        baseline_after = run(test_command, repo, env=worktree_env(repo), timeout=30)
        ordinary = _ordinary_evaluation(repo, base, candidate, paths)
        patch_bytes = subprocess.run(
            ["git", "diff", "--binary", "--full-index", f"{base}..{candidate}"],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        ).stdout
        (out_dir / PATCH_NAME).write_bytes(patch_bytes)

        recorder_valid = bool(ci.verify_ci_receipt(recorder, key).get("valid"))
        doctor_valid = _doctor_record_valid(doctor, key)
        primary = [row for row in recorder_payload.get("findings", []) if row.get("role") == "PRIMARY"]
        authority = doctor_payload.get("authority") or {}
        worker_boundary_clean = "CI_CODE_PATH_001_WORKER_BOUNDARY_CLEAN" in str(
            (doctor_payload.get("agent_execution") or {}).get("stdout_tail") or ""
        )
        required_calls = ["run", "workflow_file", "jobs", "job_log", "annotations"]
        invariants = {
            "real_failure_observed": baseline_check["exit_code"] != 0 and b"AssertionError" in baseline_log,
            "provider_read_boundary_complete": client.calls == required_calls,
            "recorder_receipt_valid": recorder_valid,
            "recorder_code_repair_only": (
                recorder_payload.get("disposition") == "CODE_REPAIR_ALLOWED"
                and (recorder_payload.get("authorization") or {}).get("code_repair") is True
                and (recorder_payload.get("authorization") or {}).get("retry") is False
            ),
            "doctor_receipt_valid": doctor_valid,
            "doctor_reproduced_before_worker": (doctor_payload.get("local_reproduction") or {}).get("status") == "REPRODUCED",
            "worker_boundary_clean": worker_boundary_clean,
            "candidate_isolated_from_main": candidate not in {"", base} and after["head"] == base,
            "trusted_baseline_unchanged": before == after,
            "trusted_baseline_still_reproduces_failure": baseline_after["exit_code"] != 0,
            "only_expected_source_changed": paths == ["src/retry_policy.py"],
            "ordinary_evaluation_survived": ordinary.get("status") == "SURVIVED",
            "github_write_authority_absent": authority.get("github_write") is False,
            "merge_authority_absent": authority.get("merge") is False,
            "deployment_authority_absent": authority.get("deployment") is False,
            "workflow_repair_authority_absent": authority.get("workflow_repair") is False,
            "baseline_change_authority_absent": authority.get("baseline_change") is False,
        }
        route_ok = (
            len(primary) == 1
            and primary[0].get("cause_class") == "CODE_REGRESSION"
            and primary[0].get("reason_code") == "TEST_FAILURE"
            and doctor_result.get("decision") == "READY_FOR_REVIEW"
            and ordinary.get("status") == "SURVIVED"
        )
        earned = route_ok and all(invariants.values())
        payload = {
            "schema": "airlock.ci-code-path-001.result.v1",
            "experiment": "CI-CODE-PATH-001",
            "verdict": "END_TO_END_CODE_REPAIR_PATH_EARNED" if earned else "CONTROL_PATH_FAILED",
            "product_under_test": {
                "base_commit": frozen["preregistration"]["product_base_commit"],
                "observed_head": frozen["current_product_commit"],
                "lineage": frozen["product_lineage"],
                "component_sha256": frozen["observed_sha256"],
                "preregistration_sha256": sha256_file(PREREG),
            },
            "fixture": {
                "repository": REPOSITORY,
                "base_commit": base,
                "baseline_test_exit_code": baseline_check["exit_code"],
                "baseline_stdout_sha256": sha256_bytes(baseline_check["stdout"].encode()),
                "baseline_stderr_sha256": sha256_bytes(baseline_check["stderr"].encode()),
                "provider_read_calls": client.calls,
            },
            "route": {
                "recorder_disposition": recorder_payload.get("disposition"),
                "recorder_primary_class": primary[0].get("cause_class") if len(primary) == 1 else None,
                "recorder_reason": primary[0].get("reason_code") if len(primary) == 1 else None,
                "doctor_decision": doctor_result.get("decision"),
                "doctor_reason": doctor_result.get("reason"),
                "candidate_commit": candidate,
                "changed_paths": paths,
                "ordinary_evaluation": ordinary,
            },
            "invariants": invariants,
            "authority": authority,
            "receipt_chain": {
                "recorder_sha256": sha256_bytes(canonical_json_bytes(recorder)),
                "doctor_sha256": sha256_bytes(canonical_json_bytes(doctor)),
                "recorder": recorder,
                "doctor": doctor,
            },
            "survivor_patch": {
                "path": PATCH_NAME,
                "sha256": sha256_bytes(patch_bytes),
            },
            "claim_boundary": frozen["preregistration"]["claim_boundary"],
        }
        signed = sign(payload, key)
        (out_dir / RESULT_NAME).write_bytes(canonical_json_bytes(signed) + b"\n")
        if not earned:
            raise RuntimeError("CI-CODE-PATH-001 did not earn its end-to-end verdict")
        return signed


def verify_result(
    result_path: Path = HERE / RESULT_NAME,
    patch_path: Path = HERE / PATCH_NAME,
    key_path: Path = KEY_PATH,
) -> dict[str, Any]:
    key = _key(key_path)
    try:
        record = json.loads(result_path.read_text())
    except Exception:
        return {"valid": False, "checks": [{"check": "result_json", "ok": False}]}
    payload = record.get("payload") if isinstance(record, dict) else None
    chain = payload.get("receipt_chain") if isinstance(payload, dict) else {}
    recorder = chain.get("recorder") if isinstance(chain, dict) else None
    doctor = chain.get("doctor") if isinstance(chain, dict) else None
    patch = patch_path.read_bytes() if patch_path.is_file() else b""
    ordinary = ((payload or {}).get("route") or {}).get("ordinary_evaluation") or {}
    checks = [
        {"check": "result_signature", "ok": isinstance(record, dict) and verify_signature(record, key)},
        {"check": "result_schema", "ok": isinstance(payload, dict) and payload.get("schema") == "airlock.ci-code-path-001.result.v1"},
        {"check": "earned_verdict", "ok": isinstance(payload, dict) and payload.get("verdict") == "END_TO_END_CODE_REPAIR_PATH_EARNED"},
        {"check": "preregistration_binding", "ok": isinstance(payload, dict) and (payload.get("product_under_test") or {}).get("preregistration_sha256") == sha256_file(PREREG)},
        {"check": "survivor_patch_binding", "ok": isinstance(payload, dict) and ((payload.get("survivor_patch") or {}).get("sha256") == sha256_bytes(patch))},
        {"check": "recorder_receipt", "ok": isinstance(recorder, dict) and ci.verify_ci_receipt(recorder, key).get("valid") is True},
        {"check": "doctor_receipt", "ok": isinstance(doctor, dict) and _doctor_record_valid(doctor, key)},
        {"check": "receipt_hash_chain", "ok": (
            isinstance(recorder, dict)
            and isinstance(doctor, dict)
            and chain.get("recorder_sha256") == sha256_bytes(canonical_json_bytes(recorder))
            and chain.get("doctor_sha256") == sha256_bytes(canonical_json_bytes(doctor))
        )},
        {"check": "exact_changed_path", "ok": ((payload or {}).get("route") or {}).get("changed_paths") == ["src/retry_policy.py"]},
        {"check": "ordinary_evaluation", "ok": ordinary.get("status") == "SURVIVED" and all(row.get("status") == "PASS" for row in ordinary.get("checks", []))},
        {"check": "all_recorded_invariants", "ok": bool((payload or {}).get("invariants")) and all((payload or {})["invariants"].values())},
        {"check": "no_consequential_authority", "ok": all(((payload or {}).get("authority") or {}).get(name) is False for name in ("github_write", "merge", "deployment", "workflow_repair", "baseline_change", "retry"))},
    ]
    return {
        "valid": all(row["ok"] for row in checks),
        "checks": checks,
        "result_sha256": sha256_file(result_path) if result_path.is_file() else None,
        "patch_sha256": sha256_bytes(patch) if patch else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or verify CI-CODE-PATH-001.")
    parser.add_argument("--out", type=Path, help="Directory for a fresh result and survivor patch")
    parser.add_argument("--verify", action="store_true", help="Verify the committed result and patch offline")
    args = parser.parse_args(argv)
    if args.verify:
        result = verify_result()
    elif args.out:
        record = run_dogfood(args.out)
        result = {
            "valid": record["payload"]["verdict"] == "END_TO_END_CODE_REPAIR_PATH_EARNED",
            "verdict": record["payload"]["verdict"],
            "result": str(args.out.expanduser().resolve() / RESULT_NAME),
            "patch": str(args.out.expanduser().resolve() / PATCH_NAME),
        }
    else:
        parser.error("choose --out DIR or --verify")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") else 3


if __name__ == "__main__":
    raise SystemExit(main())
