from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from airlock import ci, ci_retry, command, nightshift_ci
from airlock.ci import PROVIDER, SCHEMA_VERSION
from airlock.util import canonical_json_bytes, sha256_bytes
from airlock.verification import sign


def make_repo() -> tuple[tempfile.TemporaryDirectory, Path, bytes]:
    td = tempfile.TemporaryDirectory(prefix="airlock-nightshift-ci-")
    repo = Path(td.name)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], cwd=repo, check=True)
    (repo / ".airlock").mkdir()
    key = bytes.fromhex("22" * 32)
    (repo / ".airlock" / "verification.key").write_bytes(key)
    return td, repo, key


def write_receipt(repo: Path, key: bytes, disposition: str, *, tamper: bool = False, grant_merge: bool = False) -> Path:
    authorization = {
        "result": disposition,
        "code_repair": disposition == "CODE_REPAIR_ALLOWED",
        "retry": disposition == "RETRY_RECOMMENDED",
        "merge": grant_merge,
        "deployment": False,
        "baseline_change": False,
        "workflow_repair": False,
        "scope": "possible next process only",
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider": PROVIDER,
        "source_bundle_sha256": "11" * 32,
        "rule_set_version": "airlock.ci.rules.v1",
        "rule_set_sha256": "33" * 32,
        "run": {
            "repository": "example/repo",
            "run_id": 123,
            "run_attempt": 1,
            "provider_run_head_sha": "44" * 20,
        },
        "findings": [],
        "disposition": disposition,
        "authorization": authorization,
        "evidence_references": [],
    }
    payload["canonical_payload_sha256"] = sha256_bytes(canonical_json_bytes(payload))
    receipt = sign(payload, key)
    if tamper:
        receipt["payload"]["source_bundle_sha256"] = "ff" * 32
    path = repo / ".airlock" / "ci-receipt.json"
    path.write_bytes(canonical_json_bytes(receipt) + b"\n")
    return path


class NightshiftCIIntegrationTests(unittest.TestCase):
    def test_command_router_intercepts_only_nightshift_ci_surface(self) -> None:
        with mock.patch("airlock.nightshift_ci.main", return_value=7) as integration:
            self.assertEqual(command.main(["nightshift", "--ci", "123"]), 7)
            integration.assert_called_once_with(["--ci", "123"])
        with mock.patch("airlock.nightshift_ci.main", return_value=8) as integration:
            self.assertEqual(command.main(["nightshift", "--retry-ci"]), 8)
            integration.assert_called_once_with(["--retry-ci"])
        with mock.patch("airlock.entry.main", return_value=9) as frozen:
            self.assertEqual(command.main(["nightshift", "--budget", "2"]), 9)
            frozen.assert_called_once_with(["nightshift", "--budget", "2"])

    def test_red_ci_routes_stop_before_frozen_nightshift(self) -> None:
        for disposition, next_process in (
            ("CODE_REPAIR_ALLOWED", "CODE_REPAIR_PROCESS"),
            ("RETRY_RECOMMENDED", "BOUNDED_RETRY_PROCESS"),
            ("REPORT_ONLY", "REPORT_ONLY"),
        ):
            with self.subTest(disposition=disposition):
                td, repo, key = make_repo()
                try:
                    receipt_path = write_receipt(repo, key, disposition)
                    out = io.StringIO()
                    with mock.patch("airlock.ci.record_run", return_value={"receipt_path": receipt_path}), \
                         mock.patch("airlock.entry.main") as frozen_nightshift, \
                         contextlib.redirect_stdout(out):
                        rc = nightshift_ci.main(["--ci", "123", "--repo", str(repo), "--budget", "2"])
                    self.assertEqual(rc, 0)
                    frozen_nightshift.assert_not_called()
                    self.assertIn(f"Disposition: {disposition}", out.getvalue())
                    self.assertIn(f"Next process: {next_process}", out.getvalue())
                    self.assertIn("Hermes started: NO", out.getvalue())
                    self.assertIn("No retry was started", out.getvalue())
                finally:
                    td.cleanup()

    def test_no_action_is_only_route_that_delegates_to_ordinary_nightshift(self) -> None:
        td, repo, key = make_repo()
        try:
            receipt_path = write_receipt(repo, key, "NO_ACTION")
            with mock.patch("airlock.ci.record_run", return_value={"receipt_path": receipt_path}), \
                 mock.patch("airlock.entry.main", return_value=5) as frozen_nightshift:
                rc = nightshift_ci.main(["--ci=123", "--repo", str(repo), "--budget", "2"])
            self.assertEqual(rc, 5)
            frozen_nightshift.assert_called_once_with(["nightshift", "--repo", str(repo), "--budget", "2"])
        finally:
            td.cleanup()

    def test_tampered_receipt_and_manufactured_authority_fail_before_worker(self) -> None:
        for kwargs, message in (({"tamper": True}, "integrity"), ({"grant_merge": True}, "merge authority")):
            td, repo, key = make_repo()
            try:
                receipt_path = write_receipt(repo, key, "REPORT_ONLY", **kwargs)
                with mock.patch("airlock.ci.record_run", return_value={"receipt_path": receipt_path}), \
                     mock.patch("airlock.entry.main") as frozen_nightshift:
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        rc = nightshift_ci.main(["--ci", "123", "--repo", str(repo)])
                self.assertEqual(rc, 3)
                frozen_nightshift.assert_not_called()
                self.assertIn(message, err.getvalue())
            finally:
                td.cleanup()

    def test_ci_and_verify_cannot_be_combined(self) -> None:
        td, repo, _ = make_repo()
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = nightshift_ci.main(["--ci", "123", "--verify", "report.json", "--repo", str(repo)])
            self.assertEqual(rc, 3)
            self.assertIn("cannot be combined", err.getvalue())
        finally:
            td.cleanup()

    def test_explicit_retry_mode_consumes_only_retry_recommended_receipt(self) -> None:
        td, repo, key = make_repo()
        try:
            receipt_path = write_receipt(repo, key, "RETRY_RECOMMENDED")
            fake_result = {
                "retry_attempt": 2,
                "retry_disposition": "NO_ACTION",
                "original_receipt_path": receipt_path,
                "retry_receipt_path": repo / ".airlock" / "retry.json",
                "retry_record_path": repo / ".airlock" / "retry-record.json",
            }
            with mock.patch("airlock.ci.record_run", return_value={"receipt_path": receipt_path, "receipt": json.loads(receipt_path.read_text())}), \
                 mock.patch("airlock.ci_retry.bounded_retry", return_value=fake_result) as bounded, \
                 mock.patch("airlock.entry.main") as frozen_nightshift:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = nightshift_ci.main(["--ci", "123", "--retry-ci", "--repo", str(repo)])
            self.assertEqual(rc, 0)
            bounded.assert_called_once()
            frozen_nightshift.assert_not_called()
            self.assertIn("Retry submitted: YES", out.getvalue())
            self.assertIn("Retry budget remaining: 0", out.getvalue())
            self.assertIn("Hermes started: NO", out.getvalue())
        finally:
            td.cleanup()

    def test_retry_flag_never_overrides_report_only(self) -> None:
        td, repo, key = make_repo()
        try:
            receipt_path = write_receipt(repo, key, "REPORT_ONLY")
            with mock.patch("airlock.ci.record_run", return_value={"receipt_path": receipt_path}), \
                 mock.patch("airlock.ci_retry.bounded_retry") as bounded, \
                 mock.patch("airlock.entry.main") as frozen_nightshift:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = nightshift_ci.main(["--ci", "123", "--retry-ci", "--repo", str(repo)])
            self.assertEqual(rc, 0)
            bounded.assert_not_called()
            frozen_nightshift.assert_not_called()
            self.assertIn("Retry submitted: NO", out.getvalue())
        finally:
            td.cleanup()

    def test_retry_flag_requires_ci(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = nightshift_ci.main(["--retry-ci"])
        self.assertEqual(rc, 3)
        self.assertIn("requires --ci", err.getvalue())


if __name__ == "__main__":
    unittest.main()
