from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.cli import _build_nightshift_parser
from airlock.gitops import head
from airlock.improvement import verify_improvement_report
from airlock.nightshift import nightshift_models, run_nightshift
from airlock.providers import resolve_provider

PYTHON = sys.executable


def sh(*args: str, cwd: Path | None = None) -> str:
    cp = subprocess.run(
        list(args), cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return cp.stdout.strip()


class NightshiftFixture:
    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="airlock-nightshift-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", str(self.repo))
        sh("git", "-C", str(self.repo), "config", "user.name", "Airlock Test")
        sh("git", "-C", str(self.repo), "config", "user.email", "test@example.invalid")
        (self.repo / "src").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / ".airlock" / "objectives").mkdir(parents=True)
        (self.repo / "src" / "value.py").write_text("VALUE = 0\n")
        (self.repo / "tests" / "check.py").write_text(
            "from src.value import VALUE\n"
            "raise SystemExit(0 if isinstance(VALUE, int) and VALUE >= 0 else 1)\n"
        )
        measure = self.repo / ".airlock" / "objectives" / "measure.py"
        measure.write_text(
            "import json\n"
            "from src.value import VALUE\n"
            "print(json.dumps({'value': VALUE}))\n"
        )
        objective = {
            "schema": "airlock.objective.v1",
            "name": "fixture value",
            "goal": "Increase fixture value by one without changing the evaluator.",
            "measure": {
                "command": [PYTHON, ".airlock/objectives/measure.py"],
                "direction": "maximize",
                "unit": "points",
                "repeats": 1,
                "timeout_seconds": 30,
                "pass_env": [],
                "protected_evaluator_paths": [".airlock/objectives/measure.py"],
            },
            "bounds": {"max_generations": 2, "max_changed_files": 2, "max_changed_lines": 20},
            "selection": {
                "minimum_gain": "1",
                "complexity_penalty_per_changed_line": "0",
                "minimum_score_gap": "0",
            },
        }
        (self.repo / ".airlock" / "objective.json").write_text(json.dumps(objective, indent=2) + "\n")
        config = {
            "schema": "airlock.config.v1",
            "parallelism": 2,
            "protected_paths": ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"],
            "verification": {
                "static_commands": [[PYTHON, "-m", "py_compile", "src/value.py"]],
                "test_commands": [[PYTHON, "tests/check.py"]],
                "target_commands": [[PYTHON, "tests/check.py"]],
                "timeout_seconds": 30,
                "coverage_mode": "changed-module-reference",
            },
            "providers": {
                "hermes": {
                    "command": ["hermes", "-z", "{prompt}"],
                    "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"],
                    "timeout_seconds": 30,
                }
            },
            "init_baseline": {"green": True},
        }
        (self.repo / ".airlock" / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        (self.repo / ".gitignore").write_text(
            ".airlock/runs/\n.airlock/records/\n.airlock/improvements/\n.airlock/verification.key\n.airlock/index.json\n"
        )
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "base", cwd=self.repo)
        self.base = head(self.repo)

        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        hermes = self.bin / "hermes"
        hermes.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "if len(sys.argv) < 3 or sys.argv[1] != '-z': raise SystemExit(20)\n"
            "if os.environ.get('OPENROUTER_API_KEY') != 'model-secret': raise SystemExit(21)\n"
            "if os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN'): raise SystemExit(22)\n"
            "if os.environ.get('AIRLOCK_RELEASE_AUTHORITY') != 'ABSENT': raise SystemExit(23)\n"
            "Path('src/value.py').write_text('VALUE = 1\\n')\n"
            "Path(os.environ['AIRLOCK_AGENT_REPORT']).write_text(json.dumps({\n"
            "  'reported_cost_usd': '0.07', 'provider': 'openrouter', 'model': 'fake-hermes'\n"
            "}))\n"
            "print('patched')\n"
        )
        hermes.chmod(hermes.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.hermes_home = self.tmp / "hermes-home"
        self.hermes_home.mkdir()

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class NightshiftBoundaryTests(unittest.TestCase):
    def test_cli_defaults_to_one_hermes_attempt_per_generation(self) -> None:
        args = _build_nightshift_parser().parse_args([])
        self.assertEqual(args.agents, 1)
        self.assertEqual(args.objective, ".airlock/objective.json")
        self.assertIsNone(args.profiles)
        self.assertIsNone(args.generations)

    def test_default_is_one_persistent_worker(self) -> None:
        models, profiles = nightshift_models(1, [])
        self.assertEqual(models, ["hermes"])
        self.assertEqual(profiles, [])

    def test_parallel_competition_requires_unique_profiles(self) -> None:
        with self.assertRaisesRegex(ValueError, "one explicitly isolated profile per attempt"):
            nightshift_models(2, [])
        with self.assertRaisesRegex(ValueError, "distinct profiles"):
            nightshift_models(2, ["worker", "worker"])
        models, profiles = nightshift_models(2, ["worker_a", "worker_b"])
        self.assertEqual(models, ["hermes@worker_a", "hermes@worker_b"])
        self.assertEqual(profiles, ["worker_a", "worker_b"])

    def test_profile_alias_uses_hermes_global_profile_selector(self) -> None:
        config = {
            "providers": {
                "hermes": {
                    "command": ["hermes", "-z", "{prompt}"],
                    "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"],
                }
            }
        }
        provider = resolve_provider(config, "hermes@worker_a")
        self.assertEqual(provider["command"], ["hermes", "-p", "worker_a", "-z", "{prompt}"])
        self.assertEqual(provider["hermes_profile"], "worker_a")
        self.assertEqual(provider["pass_env"], ["HERMES_HOME", "OPENROUTER_API_KEY"])

    def test_fake_external_hermes_crosses_exact_gate_without_repo_authority(self) -> None:
        fx = NightshiftFixture()
        try:
            env = {
                "PATH": str(fx.bin) + os.pathsep + os.environ.get("PATH", ""),
                "HERMES_HOME": str(fx.hermes_home),
                "OPENROUTER_API_KEY": "model-secret",
                "GITHUB_TOKEN": "repo-secret-that-must-not-cross",
                "GH_TOKEN": "gh-secret-that-must-not-cross",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                report = run_nightshift(
                    fx.repo,
                    objective_path=".airlock/objective.json",
                    generations=1,
                    agents=1,
                    profiles=[],
                    budget=0.10,
                )

            self.assertEqual(report["accepted_generations"], 1)
            self.assertEqual(report["status"], "COMPLETED_LIMIT")
            self.assertEqual(head(fx.repo), fx.base)
            self.assertFalse(report["starting_ref_updated_by_airlock"])
            self.assertEqual(report["run_context"]["worker"], "hermes")
            self.assertEqual(report["run_context"]["scripted_interface"], "-z")
            self.assertEqual(report["run_context"]["attempts_per_generation"], 1)
            self.assertEqual(report["worker_usage"][0]["reported_cost"]["reported_cost_usd_total"], "0.07")
            self.assertTrue(report["worker_usage"][0]["reported_cost"]["complete"])

            report_path = fx.repo / report["report_file"]
            verified = verify_improvement_report(report_path, fx.repo / ".airlock" / "verification.key")
            self.assertTrue(verified["valid"])

            receipt = json.loads((report_path.parent / "generation-01.json").read_text())["payload"]
            candidate = receipt["candidates"][0]
            self.assertEqual(candidate["worker"]["model"], "hermes")
            self.assertEqual(candidate["worker"]["agent_report"]["provider"], "openrouter")
            self.assertEqual(candidate["worker"]["agent_report"]["model"], "fake-hermes")
            self.assertEqual(candidate["worker"]["agent_report"]["reported_cost_usd"], "0.07")
            self.assertEqual(candidate["disposition"], "ELIGIBLE")
        finally:
            fx.close()


if __name__ == "__main__":
    unittest.main()
