from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

from airlock.ci import (
    GitHubActionsReadClient,
    ProviderFailure,
    build_source_bundle,
)


class _Response:
    def __init__(self, body: bytes):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.body


class GitHubAdapterTests(unittest.TestCase):
    def test_http_adapter_uses_get_only_and_never_serializes_token(self):
        seen = []
        def opener(req, timeout=0):
            seen.append(req)
            return _Response(b'{"ok":true}')
        client = GitHubActionsReadClient(token="super-secret-token", opener=opener)
        self.assertEqual(client._json("/test"), {"ok": True})
        self.assertEqual(client.request_methods, ["GET"])
        self.assertEqual([req.get_method() for req in seen], ["GET"])
        self.assertEqual(seen[0].headers.get("Authorization"), "Bearer super-secret-token")
        self.assertNotIn("super-secret-token", repr(client))

    def test_auth_and_provider_failures_do_not_leak_credentials(self):
        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 403, "forbidden super-secret-token", {}, None)
        client = GitHubActionsReadClient(token="super-secret-token", opener=opener)
        with self.assertRaises(ProviderFailure) as ctx:
            client.run("example/widget", 7)
        self.assertNotIn("super-secret-token", str(ctx.exception))

    def test_exact_attempt_jobs_and_logs_are_not_blended(self):
        calls = []
        class Stub:
            def run(self, repo, run_id):
                return {
                    "id": run_id, "run_attempt": 2, "status": "completed", "conclusion": "success",
                    "head_sha": "a"*40, "head_branch": "main", "event": "push", "path": ".github/workflows/ci.yml",
                    "workflow_id": 9, "name": "CI", "pull_requests": [],
                }
            def attempt(self, repo, run_id, attempt):
                calls.append(("attempt", attempt))
                return {
                    "id": run_id, "run_attempt": attempt, "status": "completed", "conclusion": "failure" if attempt == 1 else "success",
                    "head_sha": "a"*40, "head_branch": "main", "event": "push", "path": ".github/workflows/ci.yml",
                    "workflow_id": 9, "name": "CI", "pull_requests": [],
                }
            def jobs(self, repo, run_id, attempt):
                calls.append(("jobs", attempt))
                return [{
                    "id": 101 if attempt == 1 else 202, "name": "test", "status":"completed",
                    "conclusion":"failure" if attempt == 1 else "success", "labels":["ubuntu-latest"],
                    "started_at":"2026-09-02T20:00:00Z", "completed_at":"2026-09-02T20:01:00Z",
                    "steps":[{"number":3,"name":"Run tests","status":"completed","conclusion":"failure" if attempt == 1 else "success"}],
                    "check_run_url":None,
                }]
            def workflow_file(self, repo, path, ref):
                return {"available":True,"bytes":b"jobs:\n  test:\n    runs-on: ubuntu-latest\n"}
            def job_log(self, repo, job_id):
                calls.append(("log", job_id))
                return {"available":True,"bytes":b"tests/test_x.py::test_x FAILED\nAssertionError"}
            def annotations(self, repo, check_run_url):
                return {"available":False,"reason":"NO_CHECK_RUN_ID"}
        bundle = build_source_bundle(Stub(), "example/widget", 77, requested_attempt=1)
        self.assertEqual(bundle["run_attempt"], 1)
        self.assertEqual([row["id"] for row in bundle["jobs"]], [101])
        self.assertIn(("jobs", 1), calls)
        self.assertIn(("jobs", 2), calls)  # comparison metadata only
        self.assertEqual([x for x in calls if x[0] == "log"], [("log", 101)])
        self.assertEqual(bundle["later_attempts"][0]["jobs"][0]["id"], 202)

    def test_job_log_uses_github_api_media_type_before_following_redirect(self):
        seen = []
        def opener(req, timeout=0):
            seen.append(req)
            if req.headers.get("Accept") != "application/vnd.github+json":
                raise urllib.error.HTTPError(req.full_url, 415, "unsupported media type", {}, None)
            return _Response(b"tests/test_x.py::test_x FAILED\nAssertionError\n")

        client = GitHubActionsReadClient(token="read-only-token", opener=opener)
        result = client.job_log("example/widget", 123)

        self.assertTrue(result["available"])
        self.assertIn(b"AssertionError", result["bytes"])
        self.assertEqual(client.request_methods, ["GET"])
        self.assertEqual(seen[0].headers.get("Accept"), "application/vnd.github+json")

    def test_authoritative_missing_job_log_is_preserved_as_missing_evidence(self):
        req = mock.Mock(full_url="https://api.github.com/repos/example/widget/actions/jobs/1/logs")
        def opener(request, timeout=0):
            raise urllib.error.HTTPError(request.full_url, 410, "gone", {}, None)
        client = GitHubActionsReadClient(opener=opener)
        result = client.job_log("example/widget", 1)
        self.assertEqual(result, {"available": False, "reason": "GITHUB_410"})


if __name__ == "__main__":
    unittest.main()
