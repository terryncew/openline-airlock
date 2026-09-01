from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock import __version__
from airlock.cli import main
from airlock.config import load as load_config
from airlock.discovery import discovery_metadata, discover_commands, protected_patterns
from airlock.util import run


def sh(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class StarterRepo:
    def __init__(self, files: dict[str, str] | None = None):
        self.tmp = Path(tempfile.mkdtemp(prefix="airlock-starter-rules-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", str(self.repo))
        sh("git", "-C", str(self.repo), "config", "user.name", "Airlock Test")
        sh("git", "-C", str(self.repo), "config", "user.email", "test@example.invalid")
        for name, content in (files or {}).items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.repo / "README.md").write_text("# fixture\n")
        sh("git", "-C", str(self.repo), "add", ".")
        sh("git", "-C", str(self.repo), "commit", "-qm", "base")

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def baseline_for(
    commands: dict[str, list[list[str]]],
    *,
    green: bool,
    failed: list[str] | None = None,
    pytest_count: int | None = None,
) -> dict:
    failed = failed or []
    records = []
    for kind in ("static", "tests"):
        for argv in commands[kind]:
            text = ""
            if pytest_count is not None and argv[:1] == ["pytest"]:
                text = f"{pytest_count} passed in 0.42s\n"
            records.append({
                "argv": argv,
                "kind": kind,
                "exit_code": 1 if argv[0] in failed else 0,
                "timed_out": False,
                "side_effect": False,
                "stdout_tail": text,
                "stderr_tail": "",
            })
    return {"commit": "a" * 40, "commands": records, "green": green}


class DiscoveryMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repos: list[StarterRepo] = []

    def tearDown(self) -> None:
        for repo in self.repos:
            repo.close()

    def make_repo(self, files: dict[str, str]) -> StarterRepo:
        repo = StarterRepo(files)
        self.repos.append(repo)
        return repo

    def test_python_metadata_names_pytest_ruff_mypy_and_exact_count(self):
        fixture = self.make_repo({
            "pyproject.toml": "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n",
            "tests/test_demo.py": "def test_demo():\n    assert True\n",
        })
        installed = {"pytest", "ruff", "mypy"}
        with mock.patch("airlock.discovery.shutil.which", side_effect=lambda name: f"/bin/{name}" if name in installed else None):
            commands = discover_commands(fixture.repo)
        baseline = baseline_for(commands, green=True, pytest_count=214)
        metadata = discovery_metadata(fixture.repo, commands, baseline)
        self.assertEqual(metadata["project_types"], ["Python"])
        self.assertEqual(metadata["test_runners"], ["pytest"])
        self.assertEqual(metadata["quality_tools"], ["Ruff", "mypy"])
        self.assertEqual(metadata["test_count"], 214)
        self.assertEqual(
            protected_patterns(fixture.repo)[:3],
            ["tests/**", ".github/**", ".airlock/**"],
        )

    def test_node_scripts_keep_existing_discovery_and_plain_names(self):
        fixture = self.make_repo({
            "package.json": json.dumps({
                "scripts": {"test": "vitest", "lint": "eslint .", "typecheck": "tsc --noEmit"},
            }),
            "tests/demo.test.js": "export const answer = 42;\n",
        })
        with mock.patch("airlock.discovery.shutil.which", side_effect=lambda name: "/bin/npm" if name == "npm" else None):
            commands = discover_commands(fixture.repo)
        metadata = discovery_metadata(fixture.repo, commands)
        self.assertEqual(commands["tests"], [["npm", "test"]])
        self.assertEqual(commands["static"], [
            ["npm", "run", "lint", "--if-present"],
            ["npm", "run", "typecheck", "--if-present"],
        ])
        self.assertEqual(metadata["project_types"], ["Node"])
        self.assertEqual(metadata["test_runners"], ["npm test"])
        self.assertEqual(metadata["quality_tools"], ["npm lint", "npm typecheck"])
        self.assertIsNone(metadata["test_count"])

    def test_rust_and_go_discovery_remains_available(self):
        fixture = self.make_repo({"Cargo.toml": "[package]\nname='demo'\n", "go.mod": "module example.test/demo\n"})
        with mock.patch("airlock.discovery.shutil.which", side_effect=lambda name: f"/bin/{name}" if name in {"cargo", "go"} else None):
            commands = discover_commands(fixture.repo)
        metadata = discovery_metadata(fixture.repo, commands)
        self.assertEqual(commands["tests"], [
            ["cargo", "test", "--all-targets"],
            ["go", "test", "./..."],
        ])
        self.assertEqual(metadata["project_types"], ["Rust", "Go"])
        self.assertEqual(metadata["test_runners"], ["cargo test", "go test"])

    def test_test_count_is_omitted_when_it_cannot_be_proved(self):
        fixture = self.make_repo({"pyproject.toml": "[project]\nname='demo'\n"})
        commands = {"static": [], "tests": [["pytest", "-q"]]}
        baseline = baseline_for(commands, green=True)
        self.assertIsNone(discovery_metadata(fixture.repo, commands, baseline)["test_count"])

    def test_missing_command_becomes_a_red_result_instead_of_a_traceback(self):
        fixture = self.make_repo({})
        result = run(["airlock-command-that-does-not-exist"], fixture.repo)
        self.assertEqual(result["exit_code"], 127)
        self.assertFalse(result["timed_out"])


class StarterRulesInitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = StarterRepo({
            "pyproject.toml": "[project]\nname='demo'\n[tool.pytest.ini_options]\n",
            "tests/test_demo.py": "def test_demo():\n    assert True\n",
        })

    def tearDown(self) -> None:
        self.fixture.close()

    def invoke(
        self,
        commands: dict[str, list[list[str]]],
        baseline: dict,
        *,
        protected: list[str] | None = None,
    ) -> tuple[int, str]:
        protected = protected or ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"]
        stdout = io.StringIO()
        with (
            mock.patch("airlock.cli.discover_commands", return_value=commands),
            mock.patch("airlock.cli.protected_patterns", return_value=protected),
            mock.patch("airlock.cli.run_baseline", return_value=baseline) as run_baseline_mock,
            mock.patch("airlock.cli.builtin_providers", return_value={}),
            contextlib.redirect_stdout(stdout),
        ):
            rc = main(["init", "--repo", str(self.fixture.repo)])
        self.last_run_baseline_mock = run_baseline_mock
        return rc, stdout.getvalue()

    def test_success_output_is_the_feature_and_config_format_stays_v1(self):
        commands = {
            "static": [["ruff", "check", "."], ["mypy", "."]],
            "tests": [["pytest", "-q"]],
        }
        rc, output = self.invoke(commands, baseline_for(commands, green=True, pytest_count=214))
        self.assertEqual(rc, 0)
        self.assertIn("Airlock found your project and set up Starter Rules.", output)
        self.assertIn("Project\n  ✓ Python / pytest\n  ✓ 214 tests found\n  ✓ Ruff\n  ✓ mypy", output)
        self.assertIn("Accepted patches cannot change\n  • tests/**\n  • .github/**\n  • .airlock/**\n  • pyproject.toml", output)
        self.assertIn(
            "Before a patch can reach you, it must pass\n"
            "  • pytest -q\n"
            "  • ruff check .\n"
            "  • mypy .",
            output,
        )
        self.assertIn("✓ Starting repo passes its checks", output)
        self.assertIn("Starter Rules saved to .airlock/config.json", output)
        self.assertIn("Next:\n  ", output)
        for term in ("policy", "admission", "mandate", "authority", "evaluator", "safe", "secure", "sandbox"):
            self.assertNotIn(term, output.casefold())

        config = load_config(self.fixture.repo / ".airlock/config.json")
        self.assertEqual(config["schema"], "airlock.config.v1")
        self.assertEqual(config["verification"]["test_commands"], [["pytest", "-q"]])
        self.assertEqual(config["verification"]["static_commands"], commands["static"])
        self.assertTrue(config["init_baseline"]["green"])

    def test_no_check_repo_saves_an_editable_draft_and_stops(self):
        commands = {"static": [], "tests": []}
        rc, output = self.invoke(commands, baseline_for(commands, green=False))
        self.assertEqual(rc, 2)
        self.assertIn("Airlock couldn't find enough checks to run unattended.", output)
        self.assertIn("✓ Python project", output)
        self.assertIn("✗ No test command", output)
        self.assertIn("✗ No lint or type check", output)
        self.assertIn("Starter Rules draft saved to .airlock/config.json.", output)
        self.assertIn("Add a check or edit .airlock/config.json, then run:\n  airlock init", output)
        self.assertNotIn("safe", output.casefold())
        self.assertTrue((self.fixture.repo / ".airlock/config.json").exists())

    def test_red_baseline_names_only_the_commands_that_failed(self):
        commands = {
            "static": [["ruff", "check", "."]],
            "tests": [["pytest", "-q"]],
        }
        baseline = baseline_for(commands, green=False, failed=["pytest"])
        rc, output = self.invoke(commands, baseline)
        self.assertEqual(rc, 2)
        self.assertIn("Airlock found your Starter Rules, but the repo does not currently pass them.", output)
        self.assertIn("Airlock won't start autonomous search from a broken starting point.", output)
        self.assertIn("Failed:\n  ✗ pytest -q", output)
        self.assertNotIn("✗ ruff check .", output)
        self.assertIn("Fix the starting repo and run airlock init again.", output)

    def test_existing_config_keeps_developer_rules_targets_providers_and_paths(self):
        config_path = self.fixture.repo / ".airlock/config.json"
        config_path.parent.mkdir()
        custom_test = [[sys.executable, "-c", "pass"]]
        existing = {
            "schema": "airlock.config.v1",
            "parallelism": 2,
            "protected_paths": ["tests/**", "docs/contracts/**"],
            "verification": {
                "static_commands": [],
                "test_commands": custom_test,
                "target_commands": [[sys.executable, "tests/issue_417.py"]],
                "timeout_seconds": 31,
                "coverage_mode": "changed-module-reference",
            },
            "providers": {"custom": {"command": ["custom-agent"], "pass_env": []}},
            "init_baseline": {"green": True},
        }
        config_path.write_text(json.dumps(existing, indent=2))
        discovered = {"static": [["ruff", "check", "."]], "tests": [["pytest", "-q"]]}
        baseline = baseline_for({"static": [], "tests": custom_test}, green=True)
        rc, _ = self.invoke(discovered, baseline, protected=[".github/**", ".airlock/**", "tests/**", "pyproject.toml"])
        self.assertEqual(rc, 0)
        self.last_run_baseline_mock.assert_called_once_with(
            self.fixture.repo,
            {"static": [], "tests": custom_test},
            timeout=31,
        )
        saved = load_config(config_path)
        self.assertEqual(saved["parallelism"], 2)
        self.assertEqual(saved["protected_paths"], ["tests/**", "docs/contracts/**"])
        self.assertEqual(saved["verification"]["test_commands"], custom_test)
        self.assertEqual(saved["verification"]["target_commands"], existing["verification"]["target_commands"])
        self.assertEqual(saved["providers"], existing["providers"])

    def test_rerunning_init_is_idempotent(self):
        commands = {"static": [], "tests": [["pytest", "-q"]]}
        baseline = baseline_for(commands, green=True, pytest_count=1)
        first_rc, first_output = self.invoke(commands, baseline)
        first_config = (self.fixture.repo / ".airlock/config.json").read_bytes()
        first_key = (self.fixture.repo / ".airlock/verification.key").read_bytes()
        second_rc, second_output = self.invoke(commands, baseline)
        self.assertEqual((first_rc, second_rc), (0, 0))
        self.assertEqual(first_output, second_output)
        self.assertEqual(first_config, (self.fixture.repo / ".airlock/config.json").read_bytes())
        self.assertEqual(first_key, (self.fixture.repo / ".airlock/verification.key").read_bytes())

    def test_generated_empty_config_can_pick_up_newly_discovered_checks(self):
        empty = {"static": [], "tests": []}
        first_rc, _ = self.invoke(
            empty,
            baseline_for(empty, green=False),
            protected=[".github/**", ".airlock/**", "docs/contracts/**"],
        )
        self.assertEqual(first_rc, 2)
        discovered = {"static": [], "tests": [["pytest", "-q"]]}
        second_rc, _ = self.invoke(discovered, baseline_for(discovered, green=True, pytest_count=1))
        self.assertEqual(second_rc, 0)
        saved = load_config(self.fixture.repo / ".airlock/config.json")
        self.assertEqual(saved["verification"]["test_commands"], [["pytest", "-q"]])
        self.assertIn("docs/contracts/**", saved["protected_paths"])
        self.assertIn("tests/**", saved["protected_paths"])

    def test_suggested_release_version_is_exposed(self):
        self.assertEqual(__version__, "0.3.0")

    def test_readme_and_show_hn_use_install_init_read_then_swarm(self):
        repo = Path(__file__).resolve().parents[1]
        for name in ("README.md", "SHOW_HN_DRAFT.md"):
            text = (repo / name).read_text()
            install_at = text.index("python -m pip install")
            init_at = text.index("airlock init", install_at)
            read_at = text.index("Read that output", init_at)
            swarm_at = text.index('airlock swarm "fix issue #417"', read_at)
            self.assertLess(install_at, init_at)
            self.assertLess(init_at, read_at)
            self.assertLess(read_at, swarm_at)


if __name__ == "__main__":
    unittest.main()
