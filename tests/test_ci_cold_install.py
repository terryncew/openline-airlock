from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


class CIRecorderColdInstallTests(unittest.TestCase):
    def test_wheel_contains_frozen_rules_and_cold_analyzer_needs_no_repo_state(self):
        repo = Path(__file__).resolve().parents[1]
        fixture = repo / "examples" / "ci-flight-recorder" / "pr60-source-bundle.json"
        with tempfile.TemporaryDirectory() as td:
            wheel_dir = Path(td) / "wheel"
            wheel_dir.mkdir()
            cp = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(wheel_dir)],
                cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            wheel = next(wheel_dir.glob("*.whl"))
            with zipfile.ZipFile(wheel) as zf:
                names = set(zf.namelist())
                self.assertIn("airlock/ci_rules.v1.json", names)
                self.assertIn("airlock/ci_receipt.v1.schema.json", names)

            target = Path(td) / "site"
            target.mkdir()
            cp = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(target), str(wheel)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr)
            script = (
                "import json,sys; "
                f"sys.path.insert(0,{str(target)!r}); "
                "from airlock.ci import analyze_bundle,verify_ci_receipt; "
                f"b=json.load(open({str(fixture)!r})); "
                "k=bytes.fromhex('11'*32); r=analyze_bundle(b,key=k); "
                "assert r['payload']['disposition']=='RETRY_RECOMMENDED'; "
                "assert verify_ci_receipt(r,k)['valid']"
            )
            cp = subprocess.run([sys.executable, "-I", "-c", script], cwd=td, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
