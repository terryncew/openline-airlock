from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.autopilot import _eligible, _list_labeled_issues, run_autopilot


class AutopilotTests(unittest.TestCase):
    def issue(self, number: int, updated: str = "2026-09-01T00:00:00Z") -> dict:
        return {
            "number": number,
            "title": f"issue {number}",
            "url": f"https://github.com/alice/demo/issues/{number}",
            "updated_at": updated,
        }

    def test_unchanged_terminal_issue_is_skipped(self):
        issue = self.issue(7)
        state = {
            "issues": {
                issue["url"]: {"updated_at": issue["updated_at"], "exit_code": 3},
            }
        }
        self.assertFalse(_eligible(issue, state, retry_unchanged=False))
        self.assertTrue(_eligible(issue, state, retry_unchanged=True))

    def test_changed_issue_becomes_eligible_again(self):
        issue = self.issue(7, "2026-09-01T01:00:00Z")
        state = {
            "issues": {
                issue["url"]: {"updated_at": "2026-09-01T00:00:00Z", "exit_code": 0},
            }
        }
        self.assertTrue(_eligible(issue, state, retry_unchanged=False))

    def test_queue_is_bounded_and_budget_is_split_across_selected_issues(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            issues = [self.issue(3), self.issue(1), self.issue(2)]
            calls = []

            def solve(url: str, budget: float | None) -> int:
                calls.append((url, budget))
                return 0

            report = run_autopilot(
                repo,
                label="airlock",
                max_issues=2,
                budget=6.0,
                retry_unchanged=False,
                solve_issue=solve,
                issue_loader=lambda _repo, _label: sorted(issues, key=lambda row: row["number"]),
                now=lambda: "2026-09-01T02:00:00+00:00",
            )

            self.assertEqual(report["attempted"], 2)
            self.assertEqual([url for url, _ in calls], [issues[1]["url"], issues[2]["url"]])
            self.assertEqual([budget for _, budget in calls], [3.0, 3.0])
            self.assertEqual(report["per_issue_budget_usd"], 3.0)

    def test_state_prevents_repeating_unchanged_work_on_next_run(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            issue = self.issue(11)
            state_path = repo / ".airlock" / "autopilot" / "state.json"
            first_calls = []
            second_calls = []

            first = run_autopilot(
                repo,
                label="airlock",
                max_issues=3,
                budget=None,
                retry_unchanged=False,
                solve_issue=lambda url, budget: first_calls.append(url) or 3,
                state_path=state_path,
                issue_loader=lambda _repo, _label: [issue],
                now=lambda: "2026-09-01T02:00:00+00:00",
            )
            second = run_autopilot(
                repo,
                label="airlock",
                max_issues=3,
                budget=None,
                retry_unchanged=False,
                solve_issue=lambda url, budget: second_calls.append(url) or 0,
                state_path=state_path,
                issue_loader=lambda _repo, _label: [issue],
                now=lambda: "2026-09-01T03:00:00+00:00",
            )

            self.assertEqual(first["attempted"], 1)
            self.assertEqual(second["attempted"], 0)
            self.assertEqual(second["skipped_unchanged"], 1)
            self.assertEqual(len(first_calls), 1)
            self.assertEqual(second_calls, [])

    def test_environment_error_stops_before_spending_on_rest_of_queue(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            issues = [self.issue(1), self.issue(2), self.issue(3)]
            calls = []

            def solve(url: str, budget: float | None) -> int:
                calls.append(url)
                return 2

            report = run_autopilot(
                repo,
                label="airlock",
                max_issues=3,
                budget=9.0,
                retry_unchanged=False,
                solve_issue=solve,
                issue_loader=lambda _repo, _label: issues,
                now=lambda: "2026-09-01T02:00:00+00:00",
            )
            self.assertTrue(report["stopped_on_error"])
            self.assertEqual(report["attempted"], 1)
            self.assertEqual(len(calls), 1)

    def test_no_review_ready_does_not_stop_next_authorized_issue(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            issues = [self.issue(1), self.issue(2)]
            exits = iter([3, 0])
            report = run_autopilot(
                repo,
                label="airlock",
                max_issues=2,
                budget=None,
                retry_unchanged=False,
                solve_issue=lambda _url, _budget: next(exits),
                issue_loader=lambda _repo, _label: issues,
                now=lambda: "2026-09-01T02:00:00+00:00",
            )
            self.assertEqual([row["status"] for row in report["results"]], ["NO_REVIEW_READY", "READY"])
            self.assertFalse(report["stopped_on_error"])

    def test_github_queue_loader_is_plain_issue_list_and_sorts_oldest_number_first(self):
        payload = json.dumps([
            {"number": 9, "title": "nine", "url": "https://github.com/alice/demo/issues/9", "updatedAt": "b"},
            {"number": 4, "title": "four", "url": "https://github.com/alice/demo/issues/4", "updatedAt": "a"},
        ])
        result = {"exit_code": 0, "stdout": payload, "stderr": ""}
        with (
            mock.patch("airlock.autopilot.shutil.which", return_value="/usr/bin/gh"),
            mock.patch("airlock.autopilot.run", return_value=result) as run_mock,
        ):
            rows = _list_labeled_issues(Path("/tmp/repo"), "airlock")
        self.assertEqual([row["number"] for row in rows], [4, 9])
        argv = run_mock.call_args.args[0]
        self.assertEqual(argv[:4], ["gh", "issue", "list", "--state"])
        self.assertIn("airlock", argv)

    def test_invalid_bounds_fail_before_any_issue_work(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            with self.assertRaisesRegex(ValueError, "max-issues"):
                run_autopilot(
                    repo,
                    label="airlock",
                    max_issues=0,
                    budget=None,
                    retry_unchanged=False,
                    solve_issue=lambda _url, _budget: 0,
                    issue_loader=lambda _repo, _label: [],
                )


if __name__ == "__main__":
    unittest.main()
