from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

from airlock_submit.github_api import parse_submit_comment, verify_webhook_signature, validate_submitter_and_fork
from airlock_submit.opener import _receipt_markdown
from airlock_submit.policy import canonical_repo_path, protected_touches
from airlock_submit.receiver import handle_webhook
from airlock_submit.seal import seal, verify
from airlock_submit.store import Store
from airlock_submit.worker import _parse_name_status, _docker_result


class FakeGitHub:
    def __init__(self, *, created_days=100, public_repos=3, target="owner/repo", base="a"*40):
        self.created_days = created_days
        self.public_repos = public_repos
        self.target = target
        self.base = base

    def user(self, login):
        created = datetime.now(timezone.utc) - timedelta(days=self.created_days)
        return {"created_at": created.isoformat().replace("+00:00", "Z"), "public_repos": self.public_repos}

    def repo(self, full_name):
        owner = full_name.split("/", 1)[0]
        return {"fork": True, "owner": {"login": owner}, "parent": {"full_name": self.target}}

    def branch_head(self, full_name, branch):
        return self.base


def cfg(**kw):
    data = {
        "schema": "airlock.submit.v1", "repo": "owner/repo", "base_branch": "main",
        "container_image": "airlock-test:latest", "min_account_age_days": 7,
        "min_public_repos": 0, "max_daily_submissions_per_user": 5,
        "max_active_submissions": 10, "max_patch_files": 60, "max_patch_bytes": 2000000,
        "evaluation_timeout_seconds": 1200, "memory": "2g", "cpus": "2", "pids_limit": 512,
        "require_source_owner_matches_submitter": True,
    }
    data.update(kw)
    return data


def webhook(secret, *, issue=7, submitter="alice", source="alice/repo", sha="b"*40):
    payload = {
        "action": "created",
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": issue, "title": "Fix parser edge case"},
        "sender": {"login": submitter},
        "comment": {"body": f"/airlock submit {source}@{sha}"},
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-hub-signature-256": sig, "x-github-event": "issue_comment", "x-github-delivery": "d1"}
    return body, headers


class SubmitTests(unittest.TestCase):
    def test_01_parse_submit_command_requires_full_sha(self):
        self.assertEqual(parse_submit_comment("/airlock submit alice/repo@" + "b"*40), ("alice/repo", "b"*40))
        self.assertIsNone(parse_submit_comment("/airlock submit alice/repo@deadbeef"))

    def test_02_webhook_signature(self):
        body = b"{}"; secret = "s"
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(secret, body, sig))
        self.assertFalse(verify_webhook_signature(secret, body+b"x", sig))

    def test_03_one_open_candidate_per_submitter_issue(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td)/"s.db")
            body, headers = webhook("secret")
            code, first = handle_webhook(body=body, headers=headers, config=cfg(), store=store,
                webhook_secret="secret", github_client=FakeGitHub())
            self.assertEqual(code, 202)
            code, second = handle_webhook(body=body, headers=headers, config=cfg(), store=store,
                webhook_secret="secret", github_client=FakeGitHub())
            self.assertEqual(code, 422)
            self.assertIn("already active", second["error"])
            store.close()

    def test_04_daily_cap(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td)/"s.db")
            body, headers = webhook("secret", issue=1)
            code, _ = handle_webhook(body=body, headers=headers, config=cfg(max_daily_submissions_per_user=1), store=store,
                webhook_secret="secret", github_client=FakeGitHub())
            self.assertEqual(code, 202)
            body2, headers2 = webhook("secret", issue=2)
            code, response = handle_webhook(body=body2, headers=headers2, config=cfg(max_daily_submissions_per_user=1), store=store,
                webhook_secret="secret", github_client=FakeGitHub())
            self.assertEqual(code, 429)
            store.close()


    def test_05_webhook_delivery_replay_is_rejected_even_after_final_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td)/"s.db")
            body, headers = webhook("secret", issue=9)
            code, first = handle_webhook(body=body, headers=headers, config=cfg(), store=store,
                webhook_secret="secret", github_client=FakeGitHub())
            self.assertEqual(code, 202)
            store.transition(first["submission_id"], "BLOCKED")
            code, response = handle_webhook(body=body, headers=headers, config=cfg(), store=store,
                webhook_secret="secret", github_client=FakeGitHub())
            self.assertEqual(code, 422)
            self.assertIn("already processed", response["error"])
            store.close()

    def test_06_account_age_and_fork_owner_policy(self):
        with self.assertRaisesRegex(RuntimeError, "too new"):
            validate_submitter_and_fork(FakeGitHub(created_days=1), cfg(), "alice", "alice/repo")
        with self.assertRaisesRegex(RuntimeError, "owned"):
            validate_submitter_and_fork(FakeGitHub(), cfg(), "alice", "bob/repo")

    def test_07_protected_paths_are_fail_closed_and_case_insensitive(self):
        touched = protected_touches([
            "src/x.py", ".github", ".github/workflows/release.yml", ".AIRLOCK/config.json", "tests", "tests/test_x.py"
        ], ["tests/**"])
        self.assertEqual(touched, [".AIRLOCK/config.json", ".github", ".github/workflows/release.yml", "tests", "tests/test_x.py"])
        with self.assertRaises(ValueError):
            canonical_repo_path("../outside")
        with self.assertRaises(ValueError):
            canonical_repo_path(".github\\workflows\\x.yml")

    def test_08_rename_parser_checks_both_old_and_new_paths(self):
        raw = b"R100\0tests/test_old.py\0src/new.py\0M\0src/core.py\0"
        self.assertEqual(_parse_name_status(raw), ["tests/test_old.py", "src/new.py", "src/core.py"])

    def test_09_evaluation_bundle_tamper_rejected(self):
        obj = seal({"patch": {"sha256": "abc"}}, "key")
        self.assertTrue(verify(obj, "key"))
        obj["payload"]["patch"]["sha256"] = "evil"
        self.assertFalse(verify(obj, "key"))

    def test_10_docker_command_has_no_network_or_secret_env(self):
        class CP:
            returncode=0; stdout="ok"; stderr=""
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("airlock_submit.worker.shutil.which", return_value="/usr/bin/docker"), \
             mock.patch("airlock_submit.worker.subprocess.run", return_value=CP()) as run_mock:
            result = _docker_result(Path(td), "image:tag", ["pytest", "-q"], cfg(), 10)
            argv = run_mock.call_args.args[0]
            env = run_mock.call_args.kwargs["env"]
            self.assertIn("none", argv)
            self.assertIn("no-new-privileges", argv)
            self.assertIn("--cap-drop", argv)
            self.assertIn("--read-only", argv)
            self.assertNotIn("GITHUB_TOKEN", env)
            self.assertEqual(result["exit_code"], 0)

    def test_11_pr_receipt_says_exactly_what_ran(self):
        submission = {"submitter":"alice", "issue_number":7}
        evaluation = {
            "base_sha":"a"*40, "source_sha":"b"*40, "patch_sha256":"c"*64,
            "airlock_config_sha256":"d"*64, "protected_touches":[],
            "checks":[{"rule":"regression","status":"PASS","commands":[{"argv":["pytest","-q"],"exit_code":0}]}],
        }
        md = _receipt_markdown(submission, evaluation, "e"*64, {"schema":"airlock.submit.receipt.v1","decision":"READY_FOR_HUMAN_REVIEW"})
        self.assertIn("pytest -q", md)
        self.assertIn("Airlock config SHA-256", md)
        self.assertIn("does not claim unknown behavior is correct", md)
        self.assertIn("Airlock receipt", md)
        self.assertIn("airlock.submit.receipt.v1", md)


if __name__ == "__main__":
    unittest.main()
