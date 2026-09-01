from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "experiments" / "airlock-self-001" / "run_self_001.py"
EVALUATOR_PATH = ROOT / ".airlock" / "self-001" / "evaluator.py"


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip())
    return cp.stdout.strip()


class AirlockSelf001HarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_script(RUNNER_PATH, "airlock_self_001_runner")
        cls.evaluator = load_script(EVALUATOR_PATH, "airlock_self_001_evaluator")

    def test_frozen_hashes_match_repaired_harness(self) -> None:
        prereg = json.loads((ROOT / ".airlock" / "self-001" / "preregistration.json").read_text())
        paths = {
            "autonomous_runner": RUNNER_PATH,
            "config": ROOT / ".airlock" / "self-001" / "config.json",
            "evaluator": EVALUATOR_PATH,
            "protected_checks": ROOT / ".airlock" / "self-001" / "protected_checks.py",
            "scope_registry": ROOT / ".airlock" / "self-001" / "scope_registry.json",
        }
        for name, path in paths.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), prereg["frozen_sha256"][name], name)

    def test_baseline_failure_is_infrastructure_not_a_scientific_no(self) -> None:
        observed = self.runner.infrastructure_status({
            "status": "BASELINE_NOT_GREEN",
            "baseline": {"green": False, "commands": [{"exit_code": 1}]},
        })
        self.assertFalse(observed["valid"])
        self.assertEqual(observed["reason"], "BASELINE_NOT_GREEN")

    def test_failed_worker_process_is_infrastructure(self) -> None:
        observed = self.runner.infrastructure_status({
            "status": "NO_PATCH_READY",
            "candidates": [{
                "candidate_id": "candidate-01",
                "agent_execution": {"exit_code": 1, "timed_out": False},
                "agent_report": {"provider": "hermes"},
            }],
        })
        self.assertFalse(observed["valid"])
        self.assertEqual(observed["reason"], "WORKER_EXECUTION_FAILED")

    def test_completed_worker_can_validly_earn_no_winner(self) -> None:
        observed = self.runner.infrastructure_status({
            "status": "NO_PATCH_READY",
            "baseline": {"green": True},
            "candidates": [{
                "candidate_id": "candidate-01",
                "agent_execution": {"exit_code": 0, "timed_out": False},
            }],
        })
        self.assertTrue(observed["valid"])
        self.assertEqual(observed["reason"], "WORKER_EXECUTION_COMPLETED")

    def test_shared_hermes_profile_is_serial_and_local_checks_are_frozen(self) -> None:
        config = json.loads((ROOT / ".airlock" / "self-001" / "config.json").read_text())
        self.assertEqual(config["parallelism"], 1)
        expected = [["python", ".airlock/self-001/protected_checks.py"]]
        self.assertEqual(config["verification"]["test_commands"], expected)
        self.assertEqual(config["verification"]["target_commands"], expected)

        workflow = (ROOT / ".github" / "workflows" / "airlock-self-001.yml").read_text()
        self.assertIn("Full repository baseline", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("A valid negative result is evidence, not a broken workflow", workflow)

    def test_additional_path_is_rejected_even_if_file_budget_is_relaxed(self) -> None:
        repo = Path(tempfile.mkdtemp(prefix="airlock-self001-scope-"))
        try:
            git(repo.parent, "init", "-q", str(repo))
            git(repo, "config", "user.name", "Airlock Test")
            git(repo, "config", "user.email", "test@example.invalid")
            target = repo / "experiments" / "airlock-self-001" / "office_ops.py"
            target.parent.mkdir(parents=True)
            target.write_text((ROOT / "experiments" / "airlock-self-001" / "office_ops.py").read_text())
            (repo / "notes.txt").write_text("base\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "base")
            base = git(repo, "rev-parse", "HEAD")

            target.write_text((ROOT / "experiments" / "airlock-self-001" / "fixtures" / "office_ops_good.py").read_text())
            (repo / "notes.txt").write_text("candidate\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "candidate")
            candidate = git(repo, "rev-parse", "HEAD")

            registry = json.loads((ROOT / ".airlock" / "self-001" / "scope_registry.json").read_text())
            registry["bounds"]["max_changed_files"] = 2
            result = self.evaluator.evaluate(repo, base, candidate, registry)
            self.assertEqual(result["reason"], "OUT_OF_SCOPE_PATH")
            self.assertEqual(result["disposition"], "REJECT")
        finally:
            shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
