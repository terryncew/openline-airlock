from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from airlock import ci, ci_retry
from airlock.util import canonical_json_bytes, sha256_bytes
from airlock.verification import sign


def make_repo() -> tuple[tempfile.TemporaryDirectory, Path, bytes]:
    td = tempfile.TemporaryDirectory(prefix="airlock-ci-retry-")
    repo = Path(td.name)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], cwd=repo, check=True)
    (repo / ".airlock").mkdir()
    key = bytes.fromhex("52" * 32)
    (repo / ".airlock" / "verification.key").write_bytes(key)
    return td, repo, key


def receipt(repo: Path, key: bytes, *, disposition: str = "RETRY_RECOMMENDED", attempt: int = 1) -> tuple[dict, Path]:
    authorization = {
        "result": disposition,
        "code_repair": disposition == "CODE_REPAIR_ALLOWED",
        "retry": disposition == "RETRY_RECOMMENDED",
        "merge": False,
        "deployment": False,
        "baseline_change": False,
        "workflow_repair": False,
        "scope": "possible next process only",
    }
    payload = {
        "schema_version": ci.SCHEMA_VERSION,
        "provider": ci.PROVIDER,
        "source_bundle_sha256": "11" * 32,
        "rule_set_version": "airlock.ci.rules.v1",
        "rule_set_sha256": "22" * 32,
        "run": {
            "repository": "example/repo",
            "run_id": 123,
            "run_attempt": attempt,
            "provider_run_head_sha": "33" * 20,
        },
        "findings": [],
        "disposition": disposition,
        "authorization": authorization,
        "evidence_references": [],
    }
    payload["canonical_payload_sha256"] = sha256_bytes(canonical_json_bytes(payload))
    record = sign(payload, key)
    path = repo / ".airlock" / "ci" / f"example-repo-123-attempt-{attempt}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(record) + b"\n")
    return record, path


def recorded(repo: Path, key: bytes, *, disposition: str = "RETRY_RECOMMENDED", attempt: int = 1) -> dict:
    record, path = receipt(repo, key, disposition=disposition, attempt=attempt)
    return {
        "target": ci.RunTarget("example/repo", 123, attempt, repo),
        "receipt": record,
        "receipt_path": path,
        "key_path": repo / ".airlock" / "verification.key",
    }


class FakeRetryClient:
    def __init__(self, *, stale_attempt: int | None = None, conflict: bool = False, fail_post: bool = False):
        self.attempt = stale_attempt or 1
        self.status = "completed"
        self.conflict = conflict
        self.fail_post = fail_post
        self.posts = 0
        self.gets = 0

    def run_metadata(self, repo: str, run_id: int) -> dict:
        self.gets += 1
        return {"id": run_id, "run_attempt": self.attempt, "status": self.status, "conclusion": "failure" if self.attempt == 1 else "success"}

    def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        self.posts += 1
        if self.fail_post:
            raise ci_retry.RetryProviderFailure("simulated provider ambiguity")
        self.attempt = 3 if self.conflict else 2
        self.status = "completed"


def retry_recorder(repo: Path, key: bytes):
    def _record(run: str, *, cwd: Path, client=None, **kwargs):
        if not run.endswith("/attempts/2"):
            raise AssertionError(run)
        record, path = receipt(repo, key, disposition="NO_ACTION", attempt=2)
        return {"receipt": record, "receipt_path": path, "target": ci.RunTarget("example/repo", 123, 2, repo)}
    return _record


class BoundedRetryTests(unittest.TestCase):
    def test_one_authorized_retry_preserves_both_receipts_and_seals_guard(self) -> None:
        td, repo, key = make_repo()
        try:
            source = recorded(repo, key)
            client = FakeRetryClient()
            result = ci_retry.bounded_retry(
                repo,
                source,
                retry_client=client,
                recorder=retry_recorder(repo, key),
                read_client_factory=lambda token: mock.Mock(),
                sleep=lambda _: None,
            )
            self.assertEqual(client.posts, 1)
            self.assertEqual(result["source_attempt"], 1)
            self.assertEqual(result["retry_attempt"], 2)
            self.assertEqual(result["retry_disposition"], "NO_ACTION")
            self.assertEqual(result["retry_budget"], {"maximum": 1, "consumed": 1, "remaining": 0})
            self.assertFalse(result["worker_started"])
            self.assertTrue(Path(result["original_receipt_path"]).exists())
            self.assertTrue(Path(result["retry_receipt_path"]).exists())
            guard = Path(result["retry_record_path"])
            self.assertTrue(ci_retry.verify_retry_record(guard, key)["valid"])
            payload = json.loads(guard.read_text())["payload"]
            self.assertEqual(payload["status"], "SEALED")
            self.assertEqual(payload["retry_budget"]["consumed"], 1)
        finally:
            td.cleanup()

    def test_same_source_attempt_can_never_spend_retry_budget_twice(self) -> None:
        td, repo, key = make_repo()
        try:
            source = recorded(repo, key)
            first = FakeRetryClient()
            ci_retry.bounded_retry(
                repo, source, retry_client=first, recorder=retry_recorder(repo, key),
                read_client_factory=lambda token: mock.Mock(), sleep=lambda _: None,
            )
            second = FakeRetryClient()
            with self.assertRaises(ci_retry.RetryAlreadyConsumed):
                ci_retry.bounded_retry(
                    repo, source, retry_client=second, recorder=retry_recorder(repo, key),
                    read_client_factory=lambda token: mock.Mock(), sleep=lambda _: None,
                )
            self.assertEqual(second.posts, 0)
        finally:
            td.cleanup()

    def test_non_retry_disposition_never_reaches_provider(self) -> None:
        td, repo, key = make_repo()
        try:
            source = recorded(repo, key, disposition="REPORT_ONLY")
            client = FakeRetryClient()
            with self.assertRaises(ci_retry.RetryNotAuthorized):
                ci_retry.bounded_retry(repo, source, retry_client=client, sleep=lambda _: None)
            self.assertEqual(client.posts, 0)
            self.assertFalse((repo / ".airlock" / "ci" / "retries").exists())
        finally:
            td.cleanup()

    def test_stale_source_attempt_fails_closed_without_post(self) -> None:
        td, repo, key = make_repo()
        try:
            source = recorded(repo, key)
            client = FakeRetryClient(stale_attempt=2)
            with self.assertRaises(ci_retry.RetryNotAuthorized):
                ci_retry.bounded_retry(repo, source, retry_client=client, sleep=lambda _: None)
            self.assertEqual(client.posts, 0)
            guards = list((repo / ".airlock" / "ci" / "retries").glob("*.json"))
            self.assertEqual(len(guards), 1)
            self.assertEqual(json.loads(guards[0].read_text())["payload"]["status"], "SOURCE_STALE")
        finally:
            td.cleanup()

    def test_ambiguous_provider_failure_consumes_reservation_instead_of_double_retrying(self) -> None:
        td, repo, key = make_repo()
        try:
            source = recorded(repo, key)
            client = FakeRetryClient(fail_post=True)
            with self.assertRaises(ci_retry.RetryProviderFailure):
                ci_retry.bounded_retry(repo, source, retry_client=client, sleep=lambda _: None)
            self.assertEqual(client.posts, 1)
            guard = next((repo / ".airlock" / "ci" / "retries").glob("*.json"))
            payload = json.loads(guard.read_text())["payload"]
            self.assertEqual(payload["status"], "SUBMISSION_UNKNOWN")
            self.assertEqual(payload["retry_budget"]["consumed"], 1)
            with self.assertRaises(ci_retry.RetryAlreadyConsumed):
                ci_retry.bounded_retry(repo, source, retry_client=FakeRetryClient(), sleep=lambda _: None)
        finally:
            td.cleanup()

    def test_concurrent_attempt_advance_is_incomplete_and_never_loops(self) -> None:
        td, repo, key = make_repo()
        try:
            source = recorded(repo, key)
            client = FakeRetryClient(conflict=True)
            with self.assertRaises(ci_retry.RetryIncomplete):
                ci_retry.bounded_retry(repo, source, retry_client=client, sleep=lambda _: None, poll_limit=1)
            self.assertEqual(client.posts, 1)
            guard = next((repo / ".airlock" / "ci" / "retries").glob("*.json"))
            self.assertEqual(json.loads(guard.read_text())["payload"]["status"], "ATTEMPT_CONFLICT")
        finally:
            td.cleanup()

    def test_writer_surface_is_one_exact_post_endpoint(self) -> None:
        seen = []

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b"{}"

        def opener(req, timeout=30):
            seen.append((req.get_method(), req.full_url, req.get_header("Authorization")))
            return Response()

        client = ci_retry.GitHubActionsRetryClient("secret-token", opener=opener)
        client.rerun_failed_jobs("example/repo", 123)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "POST")
        self.assertTrue(seen[0][1].endswith("/repos/example/repo/actions/runs/123/rerun-failed-jobs"))
        self.assertEqual(seen[0][2], "Bearer secret-token")
        self.assertEqual(client.request_methods, ["POST"])


if __name__ == "__main__":
    unittest.main()
