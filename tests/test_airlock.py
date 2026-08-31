from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.cli import main
from airlock.receipt import verify_offline
from airlock.runner import run_tournament, _cost_summary
from airlock.util import scrub_agent_env

PY = sys.executable


def sh(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


class Fixture:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="airlock-test-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", str(self.repo))
        sh("git", "-C", str(self.repo), "config", "user.name", "Airlock Test")
        sh("git", "-C", str(self.repo), "config", "user.email", "test@example.invalid")
        (self.repo / "src").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "src" / "calc.py").write_text(
            "def add(a, b):\n"
            "    return a - b\n\n"
            "def stable():\n"
            "    return 'stable'\n"
        )
        (self.repo / "tests" / "regression_check.py").write_text(
            "from pathlib import Path\n"
            "ns={}\n"
            "exec(Path('src/calc.py').read_text(), ns)\n"
            "raise SystemExit(0 if ns['stable']() == 'stable' else 1)\n"
        )
        (self.repo / "tests" / "target_check.py").write_text(
            "from pathlib import Path\n"
            "ns={}\n"
            "exec(Path('src/calc.py').read_text(), ns)\n"
            "raise SystemExit(0 if ns['add'](2,3) == 5 else 1)\n"
        )
        (self.repo / ".gitignore").write_text(
            ".airlock/runs/\n.airlock/proofs/\n.airlock/index.json\n.airlock/receipt.key\n"
        )
        sh("git", "-C", str(self.repo), "add", ".")
        sh("git", "-C", str(self.repo), "commit", "-qm", "base")
        (self.repo / ".airlock").mkdir()

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def script(self, body: str, name: str = "agent.py") -> Path:
        path = self.tmp / name
        path.write_text(body)
        return path

    def config(self, agent: Path, *, target=True, tests=True, protected=None, providers=None) -> Path:
        protected = protected or ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"]
        provider_map = providers or {
            "fake": {
                "command": [PY, str(agent)],
                "pass_env": [],
                "timeout_seconds": 30,
            }
        }
        data = {
            "schema": "airlock.config.v1",
            "parallelism": 4,
            "protected_paths": protected,
            "verification": {
                "static_commands": [[PY, "-m", "py_compile", "src/calc.py"]],
                "test_commands": [[PY, "tests/regression_check.py"]] if tests else [],
                "target_commands": [[PY, "tests/target_check.py"]] if target else [],
                "timeout_seconds": 30,
                "sufficiency_mode": "baseline-test-reference-heuristic",
            },
            "providers": provider_map,
            "init_baseline": {},
        }
        path = self.repo / ".airlock" / "config.json"
        path.write_text(json.dumps(data, indent=2))
        return path


class AirlockTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()

    def tearDown(self):
        self.fx.close()

    def good_agent(self, cost="0.47"):
        return self.fx.script(
            "import json, os\n"
            "from pathlib import Path\n"
            "Path('src/calc.py').write_text(\"def add(a,b):\\n    return a+b\\n\\ndef stable():\\n    return 'stable'\\n\")\n"
            f"Path(os.environ['AIRLOCK_AGENT_REPORT']).write_text(json.dumps({{'reported_cost_usd':'{cost}','local_checks_passed':True}}))\n"
        )

    def test_01_good_patch_is_admitted_and_proof_verifies(self):
        agent = self.good_agent()
        config = self.fx.config(agent)
        report = run_tournament(self.fx.repo, "fix add", agents=1, models=["fake"], budget=1.0, open_pr=False, config_path=config)
        self.assertEqual(report["status"], "ADMITTED")
        proof = self.fx.repo / report["proof"]
        verified = verify_offline(self.fx.repo, proof, self.fx.repo / ".airlock" / "receipt.key")
        self.assertTrue(verified["valid"])

    def test_02_protected_test_edit_is_purged(self):
        agent = self.fx.script(
            "from pathlib import Path\n"
            "Path('src/calc.py').write_text(\"def add(a,b):\\n    return a+b\\n\\ndef stable():\\n    return 'stable'\\n\")\n"
            "Path('tests/target_check.py').write_text('raise SystemExit(0)\\n')\n"
        )
        config = self.fx.config(agent)
        report = run_tournament(self.fx.repo, "cheat", agents=1, models=["fake"], budget=None, open_pr=False, config_path=config)
        row = report["candidates"][0]
        self.assertEqual(row["disposition"], "PURGED")
        self.assertEqual(row["reason"], "PROTECTED_SURFACE")

    def test_03_remote_regression_is_purged(self):
        agent = self.fx.script(
            "from pathlib import Path\n"
            "Path('src/calc.py').write_text(\"def add(a,b):\\n    return a+b\\n\\ndef stable():\\n    return 'broken'\\n\")\n"
        )
        config = self.fx.config(agent)
        report = run_tournament(self.fx.repo, "local lure", agents=1, models=["fake"], budget=None, open_pr=False, config_path=config)
        row = report["candidates"][0]
        self.assertEqual(row["disposition"], "PURGED")
        self.assertEqual(row["reason"], "REGRESSION")

    def test_04_no_target_and_no_test_reference_is_insufficient(self):
        agent = self.fx.script(
            "from pathlib import Path\n"
            "Path('src/uncovered.py').write_text('def answer():\\n    return 42\\n')\n"
        )
        config = self.fx.config(agent, target=False)
        report = run_tournament(self.fx.repo, "add uncovered module", agents=1, models=["fake"], budget=None, open_pr=False, config_path=config)
        row = report["candidates"][0]
        self.assertEqual(row["disposition"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report["status"], "NO_PATCH_ADMITTED")

    def test_05_multiple_survivors_fail_closed(self):
        agent = self.good_agent()
        config = self.fx.config(agent)
        report = run_tournament(self.fx.repo, "fix add twice", agents=2, models=["fake"], budget=None, open_pr=False, config_path=config)
        self.assertEqual(report["status"], "MULTIPLE_SURVIVORS")
        self.assertIsNone(report["admitted_candidate_id"])
        self.assertNotIn("proof", report)

    def test_06_no_patch_is_purged(self):
        agent = self.fx.script("pass\n")
        config = self.fx.config(agent)
        report = run_tournament(self.fx.repo, "do nothing", agents=1, models=["fake"], budget=None, open_pr=False, config_path=config)
        self.assertEqual(report["candidates"][0]["reason"], "NO_PATCH")

    def test_07_tampered_receipt_is_invalid(self):
        agent = self.good_agent()
        config = self.fx.config(agent)
        report = run_tournament(self.fx.repo, "fix", agents=1, models=["fake"], budget=None, open_pr=False, config_path=config)
        proof = self.fx.repo / report["proof"]
        obj = json.loads(proof.read_text())
        obj["payload"]["candidate_commit"] = "0" * 40
        proof.write_text(json.dumps(obj))
        verified = verify_offline(self.fx.repo, proof, self.fx.repo / ".airlock" / "receipt.key")
        self.assertFalse(verified["valid"])

    def test_08_release_credentials_are_not_forwarded_to_agents(self):
        with mock.patch.dict(os.environ, {
            "GITHUB_TOKEN": "github",
            "AIRLOCK_RECEIPT_KEY": "receipt",
            "OPENROUTER_API_KEY": "provider",
        }, clear=False):
            env = scrub_agent_env(
                ["GITHUB_TOKEN", "AIRLOCK_RECEIPT_KEY", "OPENROUTER_API_KEY"],
                home=self.fx.tmp / "home",
                extra={},
            )
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("AIRLOCK_RECEIPT_KEY", env)
        self.assertEqual(env["OPENROUTER_API_KEY"], "provider")
        self.assertEqual(env["AIRLOCK_RELEASE_AUTHORITY"], "ABSENT")

    def test_09_missing_cost_stays_unknown(self):
        summary = _cost_summary([
            {"agent_report": {"reported_cost_usd": "0.47"}},
            {"agent_report": {"reported_cost_usd": "0.47"}},
            {"agent_report": {}},
        ])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["unknown_candidates"], 1)
        self.assertEqual(summary["reported_cost_usd_total"], "0.94")

    def test_10_dirty_base_refused(self):
        agent = self.good_agent()
        config = self.fx.config(agent)
        (self.fx.repo / "dirty.txt").write_text("x")
        with self.assertRaisesRegex(RuntimeError, "working tree is dirty"):
            run_tournament(self.fx.repo, "fix", agents=1, models=["fake"], budget=None, open_pr=False, config_path=config)

    def test_11_init_discovers_pytest_and_writes_config(self):
        # Make the repo a normal green pytest repo for init discovery.
        (self.fx.repo / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
        sh("git", "-C", str(self.fx.repo), "add", ".")
        sh("git", "-C", str(self.fx.repo), "commit", "-qm", "add pytest smoke")
        shutil.rmtree(self.fx.repo / ".airlock", ignore_errors=True)
        code = main(["init", "--repo", str(self.fx.repo), "--timeout", "30"])
        self.assertEqual(code, 0)
        config = json.loads((self.fx.repo / ".airlock" / "config.json").read_text())
        self.assertTrue(any(cmd[:1] == ["pytest"] for cmd in config["verification"]["test_commands"]))
        self.assertTrue(config["init_baseline"]["green"])

    def test_12_cli_surface_has_exact_three_commands(self):
        from airlock.cli import build_parser
        parser = build_parser()
        action = next(a for a in parser._actions if isinstance(a, __import__('argparse')._SubParsersAction))
        self.assertEqual(set(action.choices), {"init", "run", "verify"})


if __name__ == "__main__":
    unittest.main()
