from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CIRecorderColdInstallTests(unittest.TestCase):
    def test_installed_distribution_contains_frozen_rules_and_cold_analyzer_needs_no_repo_state(self):
        repo = Path(__file__).resolve().parents[1]
        fixture = repo / "examples" / "ci-flight-recorder" / "pr60-source-bundle.json"

        # CI installs the candidate distribution before running this suite. Inspect
        # that installed distribution directly instead of recursively asking pip to
        # rebuild the project from inside its own tests. The old recursive build
        # accidentally depended on setuptools being importable in the outer runner
        # environment, which is not guaranteed on Python 3.12/3.13.
        files = importlib.metadata.files("openline-airlock")
        self.assertIsNotNone(files)
        names = {str(path).replace("\\", "/") for path in files or ()}
        self.assertIn("airlock/ci_rules.v1.json", names)
        self.assertIn("airlock/ci_receipt.v1.schema.json", names)

        with tempfile.TemporaryDirectory() as td:
            script = (
                "import json; "
                "from airlock.ci import analyze_bundle,verify_ci_receipt; "
                f"b=json.load(open({str(fixture)!r})); "
                "k=bytes.fromhex('11'*32); r=analyze_bundle(b,key=k); "
                "assert r['payload']['disposition']=='RETRY_RECOMMENDED'; "
                "assert verify_ci_receipt(r,k)['valid']"
            )
            cp = subprocess.run(
                [sys.executable, "-I", "-c", script],
                cwd=td,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
