from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from airlock import ci, ci_doctor, command
from airlock.util import canonical_json_bytes, sha256_bytes
from airlock.verification import sign


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if cp.returncode:
        raise RuntimeError(cp.stderr)
    return cp.stdout.strip()


def make_repo(*, failing: bool = True) -> tuple[tempfile.TemporaryDirectory, Path, bytes, str]:
    td = tempfile.TemporaryDirectory(prefix="airlock-ci-doctor-")
    repo = Path(td.name)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "remote", "add", "origin", "https://github.com/example/repo.git")
    (repo / ".airlock").mkdir()
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "widget.py").write_text("def value():\n    return 1\n" if failing else "def value():\n    return 2\n")
    check = ["python", "-c", "import pathlib,sys;sys.exit(0 if 'return 2' in pathlib.Path('src/widget.py').read_text() else 1)"]
    config = {
        "schema": "airlock.config.v1",
        "parallelism": 1,
        "protected_paths": [".github/**", ".airlock/**", "tests/**", "pyproject.toml"],
        "verification": {"target_commands": [], "static_commands": [], "test_commands": [check], "timeout_seconds": 30},
        "providers": {"fake": {"command": ["fake", "{prompt}"], "pass_env": []}},
        "init_baseline": {"green": True},
    }
    (repo / ".airlock" / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    key = bytes.fromhex("22" * 32)
    (repo / ".airlock" / "verification.key").write_bytes(key)
    git(repo, "add", "src/widget.py", ".airlock/config.json")
    git(repo, "commit", "-q", "-m", "base")
    return td, repo, key, git(repo, "rev-parse", "HEAD")


def write_ci_receipt(repo: Path, key: bytes, head: str, *, disposition: str = "CODE_REPAIR_ALLOWED", repo_name: str = "example/repo", tamper: bool = False) -> Path:
    finding = {
        "job_id": 1,
        "job": "test (3.13)",
        "matrix": "UNKNOWN",
        "role": "PRIMARY",
        "step_number": 8,
        "step": "Run unit tests",
        "cause_class": "CODE_REGRESSION" if disposition == "CODE_REPAIR_ALLOWED" else "ENVIRONMENT",
        "reason_code": "TEST_FAILURE" if disposition == "CODE_REPAIR_ALLOWED" else "RUNNER_FILESYSTEM",
        "rule_id": "CI-CODE-001" if disposition == "CODE_REPAIR_ALLOWED" else "CI-ENV-001",
        "patch_implicated": "UNKNOWN",
        "local_reproduction": "NOT_ATTEMPTED",
        "evidence_grade": "DIRECT",
        "stability": "UNKNOWN",
        "evidence_summary": "a concrete test failure was recorded",
        "evidence_ref": "job:1:step:8",
    }
    payload = {
        "schema_version": ci.SCHEMA_VERSION,
        "provider": ci.PROVIDER,
        "source_bundle_sha256": "11" * 32,
        "rule_set_version": "airlock.ci.rules.v1",
        "rule_set_sha256": "33" * 32,
        "run": {
            "repository": repo_name,
            "run_id": 123,
            "run_attempt": 1,
            "workflow_id": 9,
            "workflow_name": "CI",
            "workflow_path": ".github/workflows/ci.yml",
            "workflow_file_sha256": "44" * 32,
            "event": "push",
            "provider_run_head_sha": head,
            "provider_run_head_ref": "main",
            "triggering_sha": "UNKNOWN",
            "triggering_ref": "UNKNOWN",
            "execution_sha": head,
            "execution_ref": "refs/heads/main",
            "base_ref": "UNKNOWN",
            "base_sha": "UNKNOWN",
            "status": "completed",
            "conclusion": "failure",
        },
        "findings": [finding],
        "disposition": disposition,
        "authorization": {
            "result": disposition,
            "code_repair": disposition == "CODE_REPAIR_ALLOWED",
            "retry": disposition == "RETRY_RECOMMENDED",
            "merge": False,
            "deployment": False,
            "baseline_change": False,
            "workflow_repair": False,
            "scope": "possible next process only",
        },
        "evidence_references": [],
    }
    payload["canonical_payload_sha256"] = sha256_bytes(canonical_json_bytes(payload))
    receipt = sign(payload, key)
    if tamper:
        receipt["payload"]["source_bundle_sha256"] = "ff" * 32
    path = repo / ".airlock" / "ci" / "source.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    return path


def repair_runner(argv, cwd, *, env, timeout):
    assert "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env
    (Path(cwd) / "src" / "widget.py").write_text("def value():\n    return 2\n")
    report = Path(env["AIRLOCK_AGENT_REPORT"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"reported_cost_usd": 0.05, "provider": "fake"}))
    return {"argv": argv, "exit_code": 0, "stdout": "done\n", "stderr": "", "duration_seconds": 0.01, "timed_out": False}


class CIDoctorTests(unittest.TestCase):
    def test_router_exposes_doctor_without_touching_frozen_entry(self):
        self.assertIn("airlock doctor", command._help_text())
        with mock.patch("airlock.ci_doctor.main", return_value=7) as doctor:
            self.assertEqual(command.main(["doctor", "r.json", "--budget", "1"]), 7)
            doctor.assert_called_once()

    def test_non_code_receipt_refuses_before_agent(self):
        td, repo, key, head = make_repo()
        try:
            receipt = write_ci_receipt(repo, key, head, disposition="REPORT_ONLY")
            with self.assertRaises(ci_doctor.DoctorNotAuthorized):
                ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=mock.Mock())
        finally:
            td.cleanup()

    def test_tampered_receipt_refuses_before_agent(self):
        td, repo, key, head = make_repo()
        try:
            receipt = write_ci_receipt(repo, key, head, tamper=True)
            runner = mock.Mock()
            with self.assertRaises(ci_doctor.DoctorEvidenceIncomplete):
                ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=runner)
            runner.assert_not_called()
        finally:
            td.cleanup()

    def test_repo_and_head_identity_are_bound(self):
        td, repo, key, head = make_repo()
        try:
            wrong_repo = write_ci_receipt(repo, key, head, repo_name="other/repo")
            with self.assertRaisesRegex(ci_doctor.DoctorNotAuthorized, "identity"):
                ci_doctor.run_doctor(repo, wrong_repo, model="fake", budget=1, agent_runner=mock.Mock())
            correct = write_ci_receipt(repo, key, "f" * 40)
            with self.assertRaisesRegex(ci_doctor.DoctorNotAuthorized, "HEAD"):
                ci_doctor.run_doctor(repo, correct, model="fake", budget=1, agent_runner=mock.Mock())
        finally:
            td.cleanup()

    def test_green_local_base_refuses_to_spend(self):
        td, repo, key, head = make_repo(failing=False)
        try:
            receipt = write_ci_receipt(repo, key, head)
            runner = mock.Mock()
            result = ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=runner)
            self.assertEqual(result["decision"], "NO_LOCAL_REPRODUCTION")
            self.assertFalse(result["worker_started"])
            runner.assert_not_called()
            self.assertTrue(ci_doctor.verify_doctor_receipt(result["receipt_path"], key)["valid"])
        finally:
            td.cleanup()

    def test_reproduced_failure_can_earn_ready_branch(self):
        td, repo, key, head = make_repo()
        old_gh = os.environ.get("GH_TOKEN")
        old_github = os.environ.get("GITHUB_TOKEN")
        os.environ["GH_TOKEN"] = "secret-gh"
        os.environ["GITHUB_TOKEN"] = "secret-github"
        try:
            receipt = write_ci_receipt(repo, key, head)
            result = ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=repair_runner)
            self.assertEqual(result["decision"], "READY_FOR_REVIEW")
            self.assertTrue(result["ready_branch"].startswith("airlock/doctor-ready/"))
            self.assertEqual(git(repo, "show", f"{result['ready_branch']}:src/widget.py"), "def value():\n    return 2")
            self.assertTrue(ci_doctor.verify_doctor_receipt(result["receipt_path"], key)["valid"])
            record = json.loads(result["receipt_path"].read_text())["payload"]
            self.assertEqual(record["local_reproduction"]["status"], "REPRODUCED")
            self.assertFalse(record["authority"]["github_write"])
            self.assertFalse(record["authority"]["merge"])
        finally:
            if old_gh is None: os.environ.pop("GH_TOKEN", None)
            else: os.environ["GH_TOKEN"] = old_gh
            if old_github is None: os.environ.pop("GITHUB_TOKEN", None)
            else: os.environ["GITHUB_TOKEN"] = old_github
            td.cleanup()

    def test_protected_test_change_never_earns_review(self):
        td, repo, key, head = make_repo()
        try:
            receipt = write_ci_receipt(repo, key, head)
            def bad_runner(argv, cwd, *, env, timeout):
                (Path(cwd) / "tests").mkdir(exist_ok=True)
                (Path(cwd) / "tests" / "cheat.py").write_text("pass\n")
                (Path(cwd) / "src" / "widget.py").write_text("def value():\n    return 2\n")
                return {"argv": argv, "exit_code": 0, "stdout": "", "stderr": "", "duration_seconds": 0.01, "timed_out": False}
            result = ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=bad_runner)
            self.assertEqual(result["decision"], "NO_PATCH_READY")
            record = json.loads(result["receipt_path"].read_text())["payload"]
            self.assertEqual(record["reason"], "PROTECTED_FILES_CHANGED")
            self.assertIsNone(result["ready_branch"])
        finally:
            td.cleanup()

    def test_workflow_and_airlock_paths_are_structurally_protected_even_if_config_omits_them(self):
        td, repo, key, head = make_repo()
        try:
            config_path = repo / ".airlock" / "config.json"
            config = json.loads(config_path.read_text())
            config["protected_paths"] = ["tests/**"]
            config_path.write_text(json.dumps(config, indent=2) + "\n")
            git(repo, "add", ".airlock/config.json")
            git(repo, "commit", "-q", "-m", "narrow config")
            head = git(repo, "rev-parse", "HEAD")
            receipt = write_ci_receipt(repo, key, head)

            def workflow_runner(argv, cwd, *, env, timeout):
                worktree = Path(cwd)
                (worktree / "src" / "widget.py").write_text("def value():\n    return 2\n")
                workflow = worktree / ".github" / "workflows" / "ci.yml"
                workflow.parent.mkdir(parents=True, exist_ok=True)
                workflow.write_text("name: cheated\n")
                return {"argv": argv, "exit_code": 0, "stdout": "", "stderr": "", "duration_seconds": 0.01, "timed_out": False}

            result = ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=workflow_runner)
            self.assertEqual(result["decision"], "NO_PATCH_READY")
            record = json.loads(result["receipt_path"].read_text())["payload"]
            self.assertEqual(record["reason"], "PROTECTED_FILES_CHANGED")
            self.assertIn(".github/**", record["protected_paths"])
            self.assertIn(".airlock/**", record["protected_paths"])
        finally:
            td.cleanup()

    def test_agent_failure_is_a_sealed_product_result(self):
        td, repo, key, head = make_repo()
        try:
            receipt = write_ci_receipt(repo, key, head)
            def fail(argv, cwd, *, env, timeout):
                return {"argv": argv, "exit_code": 1, "stdout": "", "stderr": "agent failed", "duration_seconds": 0.01, "timed_out": False}
            result = ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=fail)
            self.assertEqual(result["decision"], "GENERATOR_FAILED")
            self.assertTrue(ci_doctor.verify_doctor_receipt(result["receipt_path"], key)["valid"])
        finally:
            td.cleanup()

    def test_doctor_receipt_tamper_fails_integrity(self):
        td, repo, key, head = make_repo(failing=False)
        try:
            receipt = write_ci_receipt(repo, key, head)
            result = ci_doctor.run_doctor(repo, receipt, model="fake", budget=1, agent_runner=mock.Mock())
            value = json.loads(result["receipt_path"].read_text())
            value["payload"]["decision"] = "READY_FOR_REVIEW"
            result["receipt_path"].write_text(json.dumps(value))
            self.assertFalse(ci_doctor.verify_doctor_receipt(result["receipt_path"], key)["valid"])
        finally:
            td.cleanup()

    def test_budget_must_be_positive_before_spend(self):
        td, repo, key, head = make_repo()
        try:
            receipt = write_ci_receipt(repo, key, head)
            runner = mock.Mock()
            with self.assertRaises(ci_doctor.DoctorNotAuthorized):
                ci_doctor.run_doctor(repo, receipt, model="fake", budget=0, agent_runner=runner)
            runner.assert_not_called()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
