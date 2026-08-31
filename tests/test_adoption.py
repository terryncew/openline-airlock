from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.adoption import install_github
from airlock.cli import build_parser
from airlock_submit import actions as actions_mod
from airlock_submit.actions import evaluate


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.repo = Path(self.td.name)
        (self.repo / ".airlock").mkdir()
        (self.repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.0.1'\n")
        (self.repo / ".airlock" / "config.json").write_text(json.dumps({
            "schema": "airlock.config.v1",
            "parallelism": 4,
            "protected_paths": [".github/**", ".airlock/**", "tests/**", "pyproject.toml"],
            "verification": {
                "static_commands": [],
                "test_commands": [["python", "-m", "unittest", "discover", "-s", "tests", "-v"]],
                "target_commands": [],
                "timeout_seconds": 1200,
                "coverage_mode": "changed-module-reference",
            },
            "providers": {},
            "init_baseline": {"green": True, "commit": "0" * 40, "commands": []},
        }, indent=2))

    def tearDown(self):
        self.td.cleanup()

    def test_install_is_actions_only_and_self_contained(self):
        result = install_github(self.repo, github_repo="alice/demo", base_branch="main")
        self.assertFalse(result["standing_service"])
        self.assertTrue((self.repo / ".github/workflows/airlock.yml").exists())
        self.assertTrue((self.repo / ".airlock/runtime/airlock_submit/actions.py").exists())
        self.assertTrue((self.repo / ".airlock/Dockerfile").exists())
        self.assertTrue((self.repo / "CONTRIBUTING.md").exists())

    def test_workflow_splits_read_only_evaluation_from_write_publisher(self):
        install_github(self.repo, github_repo="alice/demo")
        workflow = (self.repo / ".github/workflows/airlock.yml").read_text()
        self.assertIn("issue_comment:", workflow)
        self.assertIn("group: airlock-${{ github.repository }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn('GITHUB_TOKEN: ""', workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertNotIn("airlock-submit serve", workflow)
        self.assertNotIn("webhook", workflow.casefold())

    def test_submit_config_keeps_public_door_serial_and_capped(self):
        install_github(self.repo, github_repo="alice/demo")
        cfg = json.loads((self.repo / ".airlock/submit.json").read_text())
        self.assertEqual(cfg["mode"], "github-actions")
        self.assertEqual(cfg["max_active_submissions"], 1)
        self.assertEqual(cfg["max_daily_submissions_per_user"], 5)
        self.assertEqual(cfg["min_account_age_days"], 7)

    def test_blocked_admission_never_calls_docker_path(self):
        incoming = self.repo / "incoming"
        outgoing = self.repo / "outgoing"
        incoming.mkdir()
        admission = {
            "schema": "airlock.github.admission.v1",
            "status": "BLOCKED",
            "reason": "PROTECTED_FILES_CHANGED",
            "submission_comment_id": 123,
            "repo": "alice/demo",
            "issue_number": 7,
            "issue_title": "demo",
            "submitter": "bob",
            "source_repo": "bob/demo",
            "source_sha": "1" * 40,
            "base_sha": "2" * 40,
            "changed_paths": [".github/workflows/pwn.yml"],
            "protected_touches": [".github/workflows/pwn.yml"],
            "airlock_config_sha256": None,
            "patch_sha256": None,
        }
        outcome = {
            "schema": "airlock.github.outcome.v1",
            "submission_comment_id": 123,
            "repo": "alice/demo",
            "issue_number": 7,
            "submitter": "bob",
            "source_repo": "bob/demo",
            "source_sha": "1" * 40,
            "base_sha": "2" * 40,
            "decision": "BLOCKED",
            "reason": "PROTECTED_FILES_CHANGED",
            "execution_attempted": False,
        }
        (incoming / "admission.json").write_text(json.dumps(admission))
        (incoming / "outcome.json").write_text(json.dumps(outcome))
        with mock.patch("airlock_submit.actions._run") as run:
            result = evaluate(incoming, outgoing)
        run.assert_not_called()
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertFalse(result["execution_attempted"])

    def test_contributing_copy_is_idempotent(self):
        install_github(self.repo, github_repo="alice/demo")
        first = (self.repo / "CONTRIBUTING.md").read_text()
        install_github(self.repo, github_repo="alice/demo")
        second = (self.repo / "CONTRIBUTING.md").read_text()
        self.assertEqual(first, second)
        self.assertEqual(second.count("<!-- openline-airlock:begin -->"), 1)


    def test_generated_runtime_contains_no_webhook_server(self):
        install_github(self.repo, github_repo="alice/demo")
        runtime = self.repo / ".airlock/runtime/airlock_submit"
        self.assertTrue((runtime / "actions.py").exists())
        self.assertTrue((runtime / "policy.py").exists())
        self.assertFalse((runtime / "receiver.py").exists())
        self.assertFalse((runtime / "store.py").exists())

    def test_pagination_uncertainty_fails_closed(self):
        page = [{"id": i} for i in range(100)]
        with mock.patch("airlock_submit.actions._api", return_value=page):
            with self.assertRaisesRegex(RuntimeError, "too large"):
                actions_mod._paged_comments("token", "alice/demo", "/repos/alice/demo/issues/comments", max_pages=2)

    def test_evaluation_exception_becomes_error_outcome(self):
        incoming = self.repo / "admitted"
        outgoing = self.repo / "failed"
        incoming.mkdir()
        admission = {
            "schema": "airlock.github.admission.v1",
            "status": "ADMITTED",
            "reason": "STATIC_PREFLIGHT_PASSED",
            "submission_comment_id": 444,
            "repo": "alice/demo",
            "issue_number": 9,
            "issue_title": "demo",
            "submitter": "bob",
            "source_repo": "bob/demo",
            "source_sha": "1" * 40,
            "base_sha": "2" * 40,
            "changed_paths": ["src/demo.py"],
            "protected_paths": [".github/**", ".airlock/**", "tests/**"],
            "protected_touches": [],
            "airlock_config_sha256": "3" * 64,
            "patch_sha256": "4" * 64,
        }
        (incoming / "admission.json").write_text(json.dumps(admission))
        old = Path.cwd()
        try:
            import os
            os.chdir(self.repo)
            rc = actions_mod.main(["evaluate", "--in", str(incoming), "--out", str(outgoing)])
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0)
        outcome = json.loads((outgoing / "outcome.json").read_text())
        self.assertEqual(outcome["decision"], "ERROR")
        self.assertEqual(outcome["reason"], "EVALUATION_ERROR")

    def test_cli_keeps_core_commands_and_adds_install_github(self):
        parser = build_parser()
        import argparse
        action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(set(action.choices), {"init", "run", "verify", "install-github"})


if __name__ == "__main__":
    unittest.main()


class ActionsRuntimeProofTests(unittest.TestCase):
    def test_ci_runs_real_docker_runtime_proof(self):
        repo = Path(__file__).resolve().parents[1]
        workflow = (repo / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("Actions runtime integration", workflow)
        self.assertIn("docker version", workflow)
        self.assertIn("run_actions_runtime_selftest.py", workflow)
        self.assertIn("airlock-actions-runtime", workflow)

    def test_runtime_proof_script_freezes_three_expected_outcomes(self):
        repo = Path(__file__).resolve().parents[1]
        script = (repo / "scripts" / "run_actions_runtime_selftest.py").read_text()
        self.assertIn('!= "SURVIVED"', script)
        self.assertIn('!= "NEEDS_EVIDENCE"', script)
        self.assertIn('"PROTECTED_FILES_CHANGED"', script)
        self.assertIn('"execution_attempted": False', script)
        self.assertIn("container_received_no_github_token", script)
