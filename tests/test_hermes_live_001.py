from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from airlock.runner import _agent_report


class HermesLive001ReceiptTests(unittest.TestCase):
    def test_preexec_authority_audit_survives_into_signed_candidate_provenance(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="airlock-live001-audit-")) / "report.json"
        path.write_text(json.dumps({
            "provider": "hermes",
            "authority_audit": {
                "schema": "airlock.hermes-live-001.authority.v1",
                "worker": "hermes",
                "exec_interface": ["hermes", "-z", "<prompt>"],
                "forbidden_environment_names_present": [],
                "release_authority": "ABSENT",
                "hermes_home_present": True,
                "hermes_home_path_sha256": "a" * 64,
                "github_credential_present": False,
                "environment_names": ["PATH", "HERMES_HOME", "AIRLOCK_RELEASE_AUTHORITY"],
                "claim_boundary": "files inside HERMES_HOME are outside this audit",
            },
        }))
        report = _agent_report(path)
        self.assertEqual(report["provider"], "hermes")
        self.assertEqual(report["authority_audit"]["release_authority"], "ABSENT")
        self.assertFalse(report["authority_audit"]["github_credential_present"])
        self.assertEqual(report["authority_audit"]["forbidden_environment_names_present"], [])
        self.assertNotIn("environment_names", report["authority_audit"])
        self.assertEqual(len(report["authority_audit_sha256"]), 64)

    def test_frozen_preregistration_hashes_match_exact_files(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        prereg = json.loads((repo / ".airlock" / "hermes-live-001.json").read_text())
        self.assertEqual(prereg["schema"], "airlock.hermes-live-001.prereg.v1")
        for relative, expected in prereg["frozen_files"].items():
            payload = (repo / relative).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected, relative)

    def test_worker_wrapper_records_exact_boundary_and_hides_report_path_from_hermes(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        wrapper = repo / ".airlock" / "checks" / "hermes_live_001_worker.py"
        tmp = Path(tempfile.mkdtemp(prefix="airlock-live001-wrapper-"))
        fake = tmp / "hermes"
        marker = tmp / "child.json"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            f"open({str(marker)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'report_visible': 'AIRLOCK_AGENT_REPORT' in os.environ}}))\n"
        )
        fake.chmod(0o755)
        report = tmp / "authority.json"
        env = {
            "PATH": str(tmp) + os.pathsep + os.environ.get("PATH", ""),
            "HERMES_HOME": str(tmp / "hermes-home"),
            "AIRLOCK_AGENT_REPORT": str(report),
            "AIRLOCK_RELEASE_AUTHORITY": "ABSENT",
        }
        cp = subprocess.run(
            [sys.executable, str(wrapper), "work on the task"],
            cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        authority = json.loads(report.read_text())["authority_audit"]
        self.assertEqual(authority["forbidden_environment_names_present"], [])
        self.assertFalse(authority["github_credential_present"])
        self.assertEqual(authority["release_authority"], "ABSENT")
        child = json.loads(marker.read_text())
        self.assertEqual(child["argv"], ["-z", "work on the task"])
        self.assertFalse(child["report_visible"])

    def test_worker_wrapper_fails_closed_if_forbidden_authority_reaches_boundary(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        wrapper = repo / ".airlock" / "checks" / "hermes_live_001_worker.py"
        tmp = Path(tempfile.mkdtemp(prefix="airlock-live001-forbidden-"))
        report = tmp / "authority.json"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HERMES_HOME": str(tmp / "hermes-home"),
            "AIRLOCK_AGENT_REPORT": str(report),
            "AIRLOCK_RELEASE_AUTHORITY": "ABSENT",
            "GITHUB_TOKEN": "must-never-cross",
        }
        cp = subprocess.run(
            [sys.executable, str(wrapper), "work on the task"],
            cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode, 66)
        authority = json.loads(report.read_text())["authority_audit"]
        self.assertIn("GITHUB_TOKEN", authority["forbidden_environment_names_present"])
        self.assertTrue(authority["github_credential_present"])


if __name__ == "__main__":
    unittest.main()
