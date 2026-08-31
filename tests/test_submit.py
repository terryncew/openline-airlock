from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
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

    def test_10b_service_side_effect_guard_compares_against_existing_candidate_state(self):
        from airlock_submit import worker as worker_mod

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "config", "user.name", "Airlock Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "airlock@example.invalid"], cwd=repo, check=True)
            tracked = repo / "demo.py"
            tracked.write_text("value = 1\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            tracked.write_text("value = 2\n")
            subprocess.run(["git", "add", "demo.py"], cwd=repo, check=True)

            clean_record = {"argv": ["python", "-c", "pass"], "exit_code": 0, "timed_out": False}
            with mock.patch("airlock_submit.worker._docker_result", return_value=clean_record.copy()):
                result = worker_mod._run_group(repo, "image:test", [["python", "-c", "pass"]], cfg(), kind="static")
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["commands"][0]["tracked_side_effect"])

            def mutate(*args, **kwargs):
                tracked.write_text("value = 3\n")
                return clean_record.copy()

            with mock.patch("airlock_submit.worker._docker_result", side_effect=mutate):
                result = worker_mod._run_group(repo, "image:test", [["python", "-c", "pass"]], cfg(), kind="static")
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["reason"], "EVALUATOR_SIDE_EFFECT")

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


class Submit002Tests(unittest.TestCase):
    def _submission(self):
        return {
            "id": "sub_release001",
            "repo": "owner/repo",
            "issue_number": 7,
            "issue_title": "Fix parser edge case",
            "submitter": "alice",
            "source_repo": "alice/repo",
            "source_sha": "b" * 40,
            "base_sha": "a" * 40,
        }

    def test_13_protected_cheat_is_recorded_without_starting_docker(self):
        from airlock_submit.seal import load_verified
        from airlock_submit.worker import evaluate_submission

        class CP:
            returncode = 0
            stdout = ""
            stderr = ""

        with tempfile.TemporaryDirectory() as td, \
             mock.patch("airlock_submit.worker._git", return_value=""), \
             mock.patch("airlock_submit.worker._run", return_value=CP()), \
             mock.patch("airlock_submit.worker._base_airlock_config", return_value={
                 "schema": "airlock.config.v1",
                 "protected_paths": ["tests/**", ".github/**", ".airlock/**"],
                 "verification": {"target_commands": [], "static_commands": [], "test_commands": []},
             }), \
             mock.patch("airlock_submit.worker._changed_paths", return_value=[".github/workflows/pwn.yml"]), \
             mock.patch("airlock_submit.worker._docker_result") as docker_mock:
            artifact = Path(td) / "artifacts"
            result = evaluate_submission(self._submission(), config=cfg(), artifact_dir=artifact, evaluation_key="key")
            self.assertEqual(result["decision"], "BLOCKED")
            self.assertEqual(result["reason"], "PROTECTED_FILES_CHANGED")
            self.assertFalse(result["execution_attempted"])
            docker_mock.assert_not_called()
            outcome = load_verified(artifact / "outcome.json", "key")
            self.assertEqual(outcome["decision"], "BLOCKED")
            self.assertFalse(outcome["execution_attempted"])
            self.assertEqual(outcome["protected_touches"], [".github/workflows/pwn.yml"])

    def test_14_every_public_decision_can_leave_a_signed_outcome_record(self):
        from airlock_submit.seal import load_verified
        from airlock_submit.worker import _write_outcome

        for decision in ("BLOCKED", "NEEDS_EVIDENCE", "SURVIVED"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as td:
                artifact = Path(td)
                result = _write_outcome(
                    artifact_dir=artifact,
                    submission=self._submission(),
                    evaluation_key="key",
                    decision=decision,
                    reason="TEST",
                    changed_paths=["src/x.py"],
                    protected_paths=["tests/**"],
                    checks=[],
                    execution_attempted=decision != "BLOCKED",
                )
                payload = load_verified(artifact / "outcome.json", "key")
                self.assertEqual(payload["decision"], decision)
                self.assertEqual(payload["submission_id"], self._submission()["id"])
                self.assertEqual(result["outcome_sha256"], hashlib.sha256((artifact / "outcome.json").read_bytes()).hexdigest())

    def test_15_base_move_transitions_survivor_to_reopen_and_opens_no_pr(self):
        from airlock.util import write_json
        from airlock_submit.opener import open_pr
        from airlock_submit.seal import file_binding, load_verified, seal

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_path = root / "submit.json"
            config_path.write_text(json.dumps(cfg()))
            db_path = root / "submit.db"
            store = Store(db_path)
            row = store.create(
                repo="owner/repo", issue_number=7, issue_title="Fix parser edge case",
                submitter="alice", source_repo="alice/repo", source_sha="b"*40, base_sha="a"*40,
                delivery_id="drift-1",
            )
            artifact = root / "artifacts" / row["id"]
            artifact.mkdir(parents=True)
            patch = artifact / "candidate.patch"
            patch.write_text("diff --git a/src/x.py b/src/x.py\n")
            evaluation = {
                "schema": "airlock.submit.evaluation.v1", "submission_id": row["id"],
                "base_sha": "a"*40, "source_sha": "b"*40, "decision": "SURVIVED",
                "changed_paths": ["src/x.py"], "protected_paths": ["tests/**"],
                "protected_touches": [], "airlock_config_sha256": "d"*64,
                "container_image": "airlock-test:latest", "checks": [], "expected_tree": "e"*40,
            }
            evaluation_path = artifact / "evaluation.json"
            write_json(evaluation_path, evaluation)
            outcome_path = artifact / "outcome.json"
            write_json(outcome_path, seal({
                "schema": "airlock.submit.outcome.v1", "submission_id": row["id"],
                "decision": "SURVIVED", "base_sha": "a"*40, "source_sha": "b"*40,
            }, "key"))
            write_json(artifact / "bundle.json", seal({
                "schema": "airlock.submit.bundle.v1", "submission_id": row["id"],
                "patch": file_binding(patch), "evaluation": file_binding(evaluation_path),
                "outcome": file_binding(outcome_path), "expected_tree": "e"*40,
            }, "key"))
            store.transition(row["id"], "SURVIVED", artifact_dir=str(artifact))
            store.close()

            def fake_must(argv, cwd, timeout=120):
                if "ls-remote" in argv:
                    return "c"*40 + "\trefs/heads/main\n"
                return ""

            with mock.patch("airlock_submit.opener.shutil.which", return_value="/usr/bin/gh"), \
                 mock.patch("airlock_submit.opener._must", side_effect=fake_must), \
                 mock.patch("airlock_submit.opener._run") as run_mock:
                result = open_pr(submission_id=row["id"], config_path=config_path, db_path=db_path, evaluation_key="key")
                self.assertEqual(result["state"], "REOPEN")
                self.assertEqual(result["reason"], "BASE_MOVED")
                self.assertFalse(result["pr_opened"])
                self.assertTrue(result["requires_fresh_evaluation"])
                run_mock.assert_not_called()

            store = Store(db_path)
            current = store.get(row["id"])
            self.assertEqual(current["state"], "REOPEN")
            store.close()
            reopen = load_verified(Path(result["reopen_record"]), "key")
            self.assertEqual(reopen["decision"], "REOPEN")
            self.assertFalse(reopen["rebase_performed"])
            self.assertFalse(reopen["pr_opened"])

    def test_16_reopen_state_releases_submitter_issue_slot_for_fresh_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / "s.db")
            first = store.create(repo="owner/repo", issue_number=7, issue_title="x", submitter="alice",
                                 source_repo="alice/repo", source_sha="b"*40, base_sha="a"*40, delivery_id="d1")
            store.transition(first["id"], "SURVIVED")
            store.transition(first["id"], "REOPEN")
            second = store.create(repo="owner/repo", issue_number=7, issue_title="x", submitter="alice",
                                  source_repo="alice/repo", source_sha="c"*40, base_sha="d"*40, delivery_id="d2")
            self.assertEqual(second["state"], "QUEUED")
            store.close()


if __name__ == "__main__":
    unittest.main()
