from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock import entry
from airlock.review import build_review, main, render_review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.repo = Path(self.td.name)
        (self.repo / ".airlock" / "verification.key").parent.mkdir(parents=True)
        (self.repo / ".airlock" / "verification.key").write_bytes(b"k" * 32)

    def tearDown(self):
        self.td.cleanup()

    def write_ready(self, sid: str, *, run_id: str | None = None, candidate: str = "candidate-01") -> Path:
        run_id = run_id or f"run-{sid}"
        swarm_path = self.repo / ".airlock" / "swarms" / sid / "swarm.json"
        swarm_path.parent.mkdir(parents=True, exist_ok=True)
        verification = self.repo / ".airlock" / "records" / f"{run_id}.json"
        verification.parent.mkdir(parents=True, exist_ok=True)
        branch = f"airlock/ready/{run_id}"
        payload = {
            "schema": "airlock.verification.v1",
            "decision": "READY_FOR_REVIEW",
            "run_id": run_id,
            "base_commit": "a" * 40,
            "candidate_commit": "b" * 40,
            "candidate_branch": branch,
            "source_candidate_id": candidate,
            "model": "codex",
            "changed_paths": ["src/demo.py"],
            "protected_patterns": ["tests/**"],
            "evidence": {
                "commands": [{
                    "argv": ["pytest", "-q"],
                    "kind": "regression",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_seconds": 1.25,
                    "stdout_sha256": "c" * 64,
                    "stderr_sha256": "d" * 64,
                    "stdout_tail": "secret-noise-that-review-should-not-copy",
                }],
                "coverage_check": {"status": "PASS", "basis": "target_command_present"},
            },
            "config_sha256": "e" * 64,
            "prompt_sha256": "f" * 64,
            "reported_cost": "0.47",
        }
        verification.write_text(json.dumps({"alg": "HMAC-SHA256", "payload": payload, "signature": "sig"}))
        swarm_path.write_text(json.dumps({
            "schema": "airlock.swarm.v1",
            "swarm_id": sid,
            "status": "READY",
            "final_run_id": run_id,
            "ready_candidate_id": candidate,
            "ready_branch": branch,
            "verification_file": str(verification.relative_to(self.repo)),
            "pull_request": {"status": "CREATED", "url": "https://github.com/alice/demo/pull/9"},
        }))
        prompt = self.repo / ".airlock" / "runs" / run_id / "prompt.txt"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text("Fix it\n\nSource: https://github.com/alice/demo/issues/7\n")
        return swarm_path

    def verified(self):
        return {
            "valid": True,
            "record_sha256": "1" * 64,
            "checks": [
                {"check": "signature", "ok": True},
                {"check": "git_diff_boundary", "ok": True},
                {"check": "protected_paths", "ok": True},
            ],
        }

    def test_latest_ready_swarm_becomes_review_packet(self):
        self.write_ready("20260901-010000-a")
        self.write_ready("20260901-020000-b")
        with mock.patch("airlock.review.verify_offline", return_value=self.verified()):
            report = build_review(self.repo)
        self.assertEqual(report["swarm_id"], "20260901-020000-b")
        self.assertTrue(report["receipt_valid"])
        self.assertEqual(report["issue"], "https://github.com/alice/demo/issues/7")
        self.assertEqual(report["pr_url"], "https://github.com/alice/demo/pull/9")
        self.assertEqual(report["commands"][0]["command"], "pytest -q")
        self.assertNotIn("stdout_tail", report["commands"][0])

    def test_invalid_signed_record_fails_closed(self):
        self.write_ready("20260901-010000-a")
        invalid = {"valid": False, "record_sha256": "x", "checks": [{"check": "signature", "ok": False}]}
        with mock.patch("airlock.review.verify_offline", return_value=invalid):
            with self.assertRaisesRegex(RuntimeError, "signature"):
                build_review(self.repo)

    def test_swarm_record_binding_mismatch_is_rejected(self):
        path = self.write_ready("20260901-010000-a")
        obj = json.loads(path.read_text())
        obj["final_run_id"] = "different-run"
        path.write_text(json.dumps(obj))
        with mock.patch("airlock.review.verify_offline", return_value=self.verified()):
            with self.assertRaisesRegex(RuntimeError, "run id"):
                build_review(self.repo, swarm_file=str(path.relative_to(self.repo)))

    def test_explicit_non_ready_swarm_is_rejected(self):
        path = self.repo / ".airlock" / "swarms" / "zero" / "swarm.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema": "airlock.swarm.v1", "status": "NO_PATCH_READY"}))
        with self.assertRaisesRegex(RuntimeError, "not READY"):
            build_review(self.repo, swarm_file=str(path.relative_to(self.repo)))

    def test_record_path_cannot_escape_repo(self):
        path = self.repo / ".airlock" / "swarms" / "bad" / "swarm.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "schema": "airlock.swarm.v1",
            "status": "READY",
            "verification_file": "../../outside.json",
        }))
        with self.assertRaisesRegex(RuntimeError, "outside the repository"):
            build_review(self.repo, swarm_file=str(path.relative_to(self.repo)))

    def test_human_render_is_compact_and_receipt_first(self):
        self.write_ready("20260901-010000-a")
        with mock.patch("airlock.review.verify_offline", return_value=self.verified()):
            text = render_review(build_review(self.repo))
        self.assertIn("Receipt: VALID", text)
        self.assertIn("✓ pytest -q (1.25s)", text)
        self.assertIn("Reported cost: $0.47", text)
        self.assertNotIn("secret-noise", text)

    def test_json_cli_emits_machine_readable_packet(self):
        self.write_ready("20260901-010000-a")
        stdout = io.StringIO()
        with (
            mock.patch("airlock.review.verify_offline", return_value=self.verified()),
            contextlib.redirect_stdout(stdout),
        ):
            rc = main(["--repo", str(self.repo), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue())["schema"], "airlock.review.v1")

    def test_entry_routes_review_and_preserves_existing_cli(self):
        with mock.patch("airlock.review.main", return_value=7) as review_main:
            self.assertEqual(entry.main(["review", "--json"]), 7)
            review_main.assert_called_once_with(["--json"])
        with mock.patch("airlock.cli.main", return_value=9) as cli_main:
            self.assertEqual(entry.main(["solve", "417"]), 9)
            cli_main.assert_called_once_with(["solve", "417"])


if __name__ == "__main__":
    unittest.main()
