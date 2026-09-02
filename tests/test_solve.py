from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.cli import _build_solve_parser, _resolve_solve_target, main


class SolveCommandTests(unittest.TestCase):
    def test_solve_parser_has_bounded_defaults(self):
        args = _build_solve_parser().parse_args(["417"])
        self.assertEqual(args.issue_or_prompt, "417")
        self.assertEqual(args.agents, 4)
        self.assertEqual(args.rounds, 2)
        self.assertIsNone(args.budget)
        self.assertFalse(args.no_pr)

    def test_issue_number_resolves_through_gh(self):
        repo = Path("/tmp/example")
        result = {
            "exit_code": 0,
            "stdout": json.dumps({"url": "https://github.com/alice/demo/issues/417"}),
            "stderr": "",
        }
        with (
            mock.patch("airlock.cli.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("airlock.cli.run", return_value=result) as run_mock,
        ):
            resolved = _resolve_solve_target(repo, "#417")
        self.assertEqual(resolved, "https://github.com/alice/demo/issues/417")
        run_mock.assert_called_once_with(
            ["gh", "issue", "view", "417", "--json", "url"],
            repo,
            timeout=30,
        )

    def test_prompt_is_left_untouched(self):
        with mock.patch("airlock.cli.shutil.which") as which:
            self.assertEqual(_resolve_solve_target(Path("/tmp/example"), "fix the parser"), "fix the parser")
        which.assert_not_called()

    def test_solve_auto_initializes_once_then_runs_swarm(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)

            def init_side_effect(args: argparse.Namespace) -> int:
                config = repo / ".airlock" / "config.json"
                config.parent.mkdir()
                config.write_text("{}")
                return 0

            report = {
                "status": "READY",
                "pull_request": {"status": "CREATED", "url": "https://github.com/alice/demo/pull/9"},
            }
            with (
                mock.patch("airlock.cli.root", return_value=repo),
                mock.patch("airlock.cli.command_init", side_effect=init_side_effect) as init_mock,
                mock.patch("airlock.cli._resolve_solve_target", return_value="https://github.com/alice/demo/issues/417"),
                mock.patch("airlock.cli.builtin_providers", return_value={}),
                mock.patch("airlock.cli.run_swarm", return_value=report) as swarm_mock,
            ):
                rc = main(["solve", "417", "--repo", str(repo), "--agents", "3", "--rounds", "2"])

            self.assertEqual(rc, 0)
            init_mock.assert_called_once()
            kwargs = swarm_mock.call_args.kwargs
            self.assertEqual(kwargs["agents"], 3)
            self.assertEqual(kwargs["rounds"], 2)
            self.assertTrue(kwargs["open_pr"])
            self.assertEqual(kwargs["models"], [])
            self.assertEqual(kwargs["config_path"], repo / ".airlock" / "config.json")

    def test_existing_empty_provider_map_uses_current_installed_adapters_without_rewriting_rules(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            config = repo / ".airlock" / "config.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"providers": {}}))
            with (
                mock.patch("airlock.cli.root", return_value=repo),
                mock.patch("airlock.cli._resolve_solve_target", return_value="fix bug"),
                mock.patch("airlock.cli.load_config", return_value={"providers": {}}),
                mock.patch("airlock.cli.builtin_providers", return_value={"codex": {"command": ["codex"]}}),
                mock.patch("airlock.cli.run_swarm", return_value={"status": "NO_PATCH_READY"}) as swarm_mock,
            ):
                rc = main(["solve", "fix bug", "--repo", str(repo), "--no-pr"])
            self.assertEqual(rc, 3)
            self.assertEqual(swarm_mock.call_args.kwargs["models"], ["codex"])
            self.assertEqual(json.loads(config.read_text()), {"providers": {}})

    def test_existing_starter_rules_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            config = repo / ".airlock" / "config.json"
            config.parent.mkdir()
            config.write_text("{}")
            with (
                mock.patch("airlock.cli.root", return_value=repo),
                mock.patch("airlock.cli.command_init") as init_mock,
                mock.patch("airlock.cli._resolve_solve_target", return_value="fix bug"),
                mock.patch("airlock.cli.run_swarm", return_value={"status": "NO_PATCH_READY"}),
            ):
                rc = main(["solve", "fix bug", "--repo", str(repo), "--no-pr"])
            self.assertEqual(rc, 3)
            init_mock.assert_not_called()

    def test_numeric_issue_fails_cleanly_without_gh(self):
        with mock.patch("airlock.cli.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "GitHub CLI"):
                _resolve_solve_target(Path("/tmp/example"), "417")


if __name__ == "__main__":
    unittest.main()
