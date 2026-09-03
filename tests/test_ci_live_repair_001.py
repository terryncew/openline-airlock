from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from airlock.gitops import ensure_clean


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_WORKFLOW = ROOT / ".github/workflows/ci-live-repair-001-fixture.yml"
DOGFOOD_WORKFLOW = ROOT / ".github/workflows/ci-live-repair-001-dogfood.yml"
CONFIG = ROOT / "dogfood/ci-live-repair-001/config.json"
VERIFIER = ROOT / "scripts/verify_ci_live_repair_001.py"
FIXTURE_TEST = ROOT / "experiments/ci-code-path-001/fixture/tests/test_retry_policy.py"
HERMES_COMMIT = "29112bef099274229cadff79cdff7bf7b99c4b77"


def _git(repo: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return cp.stdout


class CILiveRepair001Tests(unittest.TestCase):
    def test_frozen_fixture_is_a_real_code_failure(self) -> None:
        cp = subprocess.run(
            ["python", "-m", "unittest", "discover", "-s", str(FIXTURE_TEST.parent), "-p", FIXTURE_TEST.name, "-v"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("AssertionError", cp.stdout + cp.stderr)

    def test_dogfood_config_leaves_only_the_fixture_source_in_scope(self) -> None:
        config = json.loads(CONFIG.read_text())
        self.assertEqual(config["schema"], "airlock.config.v1")
        self.assertEqual(config["parallelism"], 1)
        self.assertEqual(config["providers"]["hermes"]["pass_env"], ["HERMES_HOME"])
        self.assertEqual(
            config["providers"]["hermes"]["command"],
            ["hermes", "-z", "{prompt}", "--toolsets", "terminal,file"],
        )
        protected = config["protected_paths"]
        for required in (
            ".github/**",
            ".airlock/**",
            "src/**",
            "tests/**",
            "dogfood/**",
            "experiments/ci-code-path-001/fixture/tests/**",
            "experiments/ci-code-path-001/fixture/tools/**",
        ):
            self.assertIn(required, protected)
        self.assertNotIn("experiments/ci-code-path-001/fixture/src/**", protected)
        command = config["verification"]["test_commands"][0]
        self.assertIn("experiments/ci-code-path-001/fixture/tests", command)
        self.assertEqual(config["verification"]["target_commands"], config["verification"]["test_commands"])

    def test_receiver_local_tracked_config_is_not_false_repo_dirt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            _git(repo, "init", "-b", "main")
            _git(repo, "config", "user.name", "Airlock Test")
            _git(repo, "config", "user.email", "airlock@example.invalid")
            (repo / ".airlock").mkdir()
            config_path = repo / ".airlock/config.json"
            config_path.write_text('{"kind":"production"}\n')
            tracked = repo / "tracked.txt"
            tracked.write_text("sealed\n")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "sealed")

            config_path.write_text('{"kind":"receiver-local"}\n')
            raw = _git(repo, "status", "--porcelain", "--untracked-files=all")
            self.assertEqual(raw, " M .airlock/config.json\n")
            ensure_clean(repo)

            tracked.write_text("ordinary dirt\n")
            with self.assertRaisesRegex(RuntimeError, "working tree is dirty"):
                ensure_clean(repo)

    def test_failure_workflow_is_isolated_and_read_only(self) -> None:
        text = FIXTURE_WORKFLOW.read_text()
        self.assertIn('name: AIRLOCK-CI-LIVE-REPAIR-001 expected code failure', text)
        self.assertIn('"dogfood/ci-live-repair-*"', text)
        self.assertIn('"dogfood/CI_LIVE_REPAIR_001_START.txt"', text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("Run frozen retry-policy regression", text)
        self.assertNotIn("OPENAI_API_KEY", text)

    def test_consumer_binds_exact_failed_run_and_has_no_github_write_authority(self) -> None:
        text = DOGFOOD_WORKFLOW.read_text()
        self.assertIn('"AIRLOCK-CI-LIVE-REPAIR-001 expected code failure"', text)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'", text)
        self.assertIn("startsWith(github.event.workflow_run.head_branch, 'dogfood/ci-live-repair-')", text)
        self.assertIn("ref: ${{ github.event.workflow_run.head_sha }}", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("contents: read", text)
        self.assertIn("actions: read", text)
        for forbidden in ("contents: write", "actions: write", "pull-requests: write", "git push", "gh pr create", "gh pr merge"):
            self.assertNotIn(forbidden, text)

    def test_consumer_installs_receiver_rules_only_in_ignored_airlock_metadata(self) -> None:
        text = DOGFOOD_WORKFLOW.read_text()
        self.assertIn("cp dogfood/ci-live-repair-001/config.json .airlock/config.json", text)
        self.assertIn("if not path.startswith('.airlock/')", text)
        self.assertIn("assert not outside_airlock", text)
        self.assertNotIn("cmp -s dogfood/ci-live-repair-001/config.json .airlock/config.json", text)

    def test_consumer_runs_exactly_one_explicit_doctor_path(self) -> None:
        text = DOGFOOD_WORKFLOW.read_text()
        self.assertIn("airlock nightshift", text)
        self.assertIn("--repair-ci", text)
        self.assertIn('--budget "$AIRLOCK_DOCTOR_BUDGET_USD"', text)
        self.assertNotIn("--retry-ci", text)
        self.assertNotIn("--agents", text)
        self.assertNotIn("--profiles", text)
        self.assertIn("SOURCE_RUN_ID: ${{ github.event.workflow_run.id }}", text)
        self.assertIn("SOURCE_RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt }}", text)
        self.assertIn("SOURCE_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}", text)

    def test_live_artifact_keeps_doctor_reason_and_receipt(self) -> None:
        text = DOGFOOD_WORKFLOW.read_text()
        self.assertIn("Expose bounded Doctor disposition", text)
        self.assertIn("Doctor reason:", text)
        self.assertIn("find .airlock/doctor", text)
        self.assertIn("-name 'doctor.json'", text)
        self.assertIn("-name 'prompt.txt'", text)
        self.assertIn("-name 'agent-report.json'", text)

    def test_real_worker_is_pinned_and_secret_is_not_forwarded_as_worker_env(self) -> None:
        text = DOGFOOD_WORKFLOW.read_text()
        self.assertIn(f"HERMES_COMMIT: {HERMES_COMMIT}", text)
        self.assertIn("HERMES_MODEL: gpt-5.6-sol", text)
        self.assertIn("OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}", text)
        self.assertIn("printf 'OPENAI_API_KEY=%s\\n' \"$OPENAI_API_KEY\" > \"$HERMES_HOME/.env\"", text)
        config = json.loads(CONFIG.read_text())
        self.assertNotIn("OPENAI_API_KEY", config["providers"]["hermes"]["pass_env"])

    def test_verifier_reuses_airlock_receipt_primitives_and_requires_exact_patch_scope(self) -> None:
        text = VERIFIER.read_text()
        self.assertIn("ci.verify_ci_receipt", text)
        self.assertIn("ci_doctor.verify_doctor_receipt", text)
        self.assertIn("from airlock.verification import sign, verify_signature", text)
        self.assertIn('ALLOWED_CHANGED_PATH = "experiments/ci-code-path-001/fixture/src/retry_policy.py"', text)
        self.assertIn('"LIVE_CODE_REPAIR_PATH_EARNED"', text)
        self.assertIn("head(repo).lower() != expected_head", text)
        self.assertIn("ordinary = _ordinary_evaluation", text)


if __name__ == "__main__":
    unittest.main()
