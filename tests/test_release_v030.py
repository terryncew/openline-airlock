from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

from airlock import __version__
from airlock import entry


class V030ReleaseTests(unittest.TestCase):
    def test_public_version_is_030(self):
        self.assertEqual(__version__, "0.3.0")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = entry.main(["--version"])
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue().strip(), "0.3.0")

    def test_top_level_help_exposes_the_normal_loop(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = entry.main(["--help"])
        self.assertEqual(rc, 0)
        text = stdout.getvalue()
        for command in ("init", "solve", "autopilot", "inbox", "review"):
            self.assertIn(command, text)
        self.assertLess(text.index("init"), text.index("solve"))
        self.assertLess(text.index("solve"), text.index("autopilot"))
        self.assertLess(text.index("autopilot"), text.index("inbox"))
        self.assertLess(text.index("inbox"), text.index("review"))

    def test_review_stays_receipt_side_and_other_commands_pass_through(self):
        with mock.patch("airlock.review.main", return_value=7) as review_main:
            self.assertEqual(entry.main(["review", "--json"]), 7)
            review_main.assert_called_once_with(["--json"])

        with mock.patch("airlock.cli.main", return_value=9) as cli_main:
            self.assertEqual(entry.main(["solve", "417"]), 9)
            cli_main.assert_called_once_with(["solve", "417"])

    def test_repository_release_verifier_passes(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts" / "verify_v030_release.py"
        spec = importlib.util.spec_from_file_location("airlock_v030_release_verify", script)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        self.assertEqual(module.verify(repo), [])


if __name__ == "__main__":
    unittest.main()
