from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from airlock.inbox import build_inbox


class InboxTests(unittest.TestCase):
    def make_repo(self):
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        return td, repo

    def write_swarm(self, repo: Path, sid: str, *, status: str, survivors: int = 0, pr_url: str | None = None, source: str | None = None):
        path = repo / ".airlock" / "swarms" / sid / "swarm.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        run_id = f"run-{sid}"
        report = {
            "schema": "airlock.swarm.v1",
            "swarm_id": sid,
            "status": status,
            "final_run_id": run_id,
            "final_survivor_count": survivors,
            "ready_branch": "airlock/ready/example" if status == "READY" else None,
            "pull_request": {"status": "CREATED", "url": pr_url} if pr_url else None,
        }
        path.write_text(json.dumps(report))
        if source:
            prompt = repo / ".airlock" / "runs" / run_id / "prompt.txt"
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(f"Fix the bug\n\nSource: {source}\n")

    def test_empty_inbox_means_zero_human_work(self):
        td, repo = self.make_repo()
        try:
            report = build_inbox(repo)
            self.assertEqual(report["needs_human"], 0)
            self.assertEqual(report["items"], [])
        finally:
            td.cleanup()

    def test_ready_survivor_is_a_review_item_with_pr(self):
        td, repo = self.make_repo()
        try:
            source = "https://github.com/alice/demo/issues/7"
            pr = "https://github.com/alice/demo/pull/9"
            self.write_swarm(repo, "20260901-010000-a", status="READY", survivors=1, pr_url=pr, source=source)
            report = build_inbox(repo)
            self.assertEqual(report["needs_human"], 1)
            self.assertEqual(report["items"][0]["action"], "REVIEW")
            self.assertEqual(report["items"][0]["source"], source)
            self.assertEqual(report["items"][0]["pr_url"], pr)
        finally:
            td.cleanup()

    def test_multiple_survivors_require_choice(self):
        td, repo = self.make_repo()
        try:
            self.write_swarm(repo, "20260901-010000-b", status="MULTIPLE_SURVIVORS", survivors=3)
            report = build_inbox(repo)
            self.assertEqual(report["items"][0]["action"], "CHOOSE")
            self.assertIn("3 patches", report["items"][0]["detail"])
        finally:
            td.cleanup()

    def test_no_patch_ready_is_hidden_by_default_but_auditable(self):
        td, repo = self.make_repo()
        try:
            self.write_swarm(repo, "20260901-010000-c", status="NO_PATCH_READY")
            compact = build_inbox(repo)
            audit = build_inbox(repo, include_all=True)
            self.assertEqual(compact["items"], [])
            self.assertEqual(compact["machine_only_results"], 1)
            self.assertEqual(audit["items"][0]["action"], "NONE")
        finally:
            td.cleanup()

    def test_red_baseline_is_human_attention(self):
        td, repo = self.make_repo()
        try:
            self.write_swarm(repo, "20260901-010000-d", status="BASELINE_NOT_GREEN")
            report = build_inbox(repo)
            self.assertEqual(report["items"][0]["action"], "FIX_BASELINE")
        finally:
            td.cleanup()

    def test_autopilot_environment_error_is_surfaced(self):
        td, repo = self.make_repo()
        try:
            path = repo / ".airlock" / "autopilot" / "state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            url = "https://github.com/alice/demo/issues/12"
            path.write_text(json.dumps({
                "schema": "airlock.autopilot.v1",
                "issues": {
                    url: {
                        "status": "ERROR",
                        "title": "broken environment",
                        "attempted_at": "2026-09-01T02:00:00+00:00",
                    },
                    "https://github.com/alice/demo/issues/13": {
                        "status": "NO_REVIEW_READY",
                        "title": "normal zero",
                        "attempted_at": "2026-09-01T02:01:00+00:00",
                    },
                },
            }))
            report = build_inbox(repo)
            self.assertEqual(report["needs_human"], 1)
            self.assertEqual(report["items"][0]["action"], "FIX_ENV")
            self.assertEqual(report["items"][0]["source"], url)
        finally:
            td.cleanup()

    def test_bad_record_is_visible_instead_of_silently_dropped(self):
        td, repo = self.make_repo()
        try:
            path = repo / ".airlock" / "swarms" / "20260901-bad" / "swarm.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not-json")
            report = build_inbox(repo)
            self.assertEqual(report["items"][0]["action"], "FIX_RECORD")
        finally:
            td.cleanup()

    def test_limit_applies_after_attention_filter(self):
        td, repo = self.make_repo()
        try:
            for i in range(4):
                self.write_swarm(repo, f"20260901-01000{i}-x", status="READY", survivors=1)
            self.write_swarm(repo, "20260901-020000-zero", status="NO_PATCH_READY")
            report = build_inbox(repo, limit=2)
            self.assertEqual(report["needs_human"], 4)
            self.assertEqual(len(report["items"]), 2)
        finally:
            td.cleanup()

    def test_invalid_limit_fails_before_reading_artifacts(self):
        td, repo = self.make_repo()
        try:
            with self.assertRaisesRegex(ValueError, "limit"):
                build_inbox(repo, limit=0)
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
