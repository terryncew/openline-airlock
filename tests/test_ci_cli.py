from __future__ import annotations

import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from airlock import command
from airlock import entry
from airlock import ci


class CIRecorderCLITests(unittest.TestCase):
    def test_top_level_help_exposes_ci_without_mutating_frozen_entry_router(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(command.main(["--help"]), 0)
        self.assertIn("airlock ci <github-actions-run-url-or-id>", out.getvalue())
        with mock.patch("airlock.ci_github.main", return_value=7) as ci_main:
            self.assertEqual(command.main(["ci", "123"]), 7)
            ci_main.assert_called_once_with(["123"])

        # Existing commands still pass through the frozen v0.3 router.
        with mock.patch("airlock.entry.main", return_value=9) as old_main:
            self.assertEqual(command.main(["review"]), 9)
            old_main.assert_called_once_with(["review"])

    def test_url_identity_conflict_with_local_origin_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git","init","-q"], cwd=td, check=True)
            subprocess.run(["git","remote","add","origin","https://github.com/example/right.git"], cwd=td, check=True)
            with self.assertRaises(ci.UnsupportedInput):
                ci.resolve_target("https://github.com/example/wrong/actions/runs/123", None, cwd=repo)

    def test_numeric_id_infers_local_github_origin(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git","init","-q"], cwd=td, check=True)
            subprocess.run(["git","remote","add","origin","git@github.com:example/right.git"], cwd=td, check=True)
            target = ci.resolve_target("123", None, cwd=repo)
            self.assertEqual((target.repo, target.run_id), ("example/right", 123))

    def test_cli_exit_codes_describe_recorder_operation(self):
        target = ci.RunTarget("example/right", 123, None, None)
        with mock.patch("airlock.ci.resolve_target", return_value=target), mock.patch("airlock.ci._token_from_environment", return_value=None):
            with mock.patch("airlock.ci.build_source_bundle", side_effect=ci.RetrievalIncomplete("incomplete")):
                self.assertEqual(ci.main(["123", "--repo", "example/right"]), 3)
            with mock.patch("airlock.ci.build_source_bundle", side_effect=ci.ProviderFailure("provider")):
                self.assertEqual(ci.main(["123", "--repo", "example/right"]), 4)
        self.assertEqual(ci.main(["not-a-run"]), 2)


if __name__ == "__main__":
    unittest.main()
