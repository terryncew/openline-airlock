from __future__ import annotations

from pathlib import Path
import re
import unittest

from airlock import ci


class CILiveRepairHarnessTests(unittest.TestCase):
    def test_fixture_failure_step_is_recognized_as_test_failure_stage(self):
        workflow = Path(".github/workflows/ci-live-repair-001-fixture.yml").read_text()
        match = re.search(r"- name: (Run frozen retry-policy regression[^\n]*)", workflow)
        self.assertIsNotNone(match)
        step_name = match.group(1)

        rule_set, _ = ci.load_rule_set()
        rule, classes = ci._match_rule(
            "AssertionError: True is not false",
            rule_set,
            step_name=step_name,
        )

        self.assertEqual(classes, ["CODE_REGRESSION"])
        self.assertIsNotNone(rule)
        self.assertEqual(rule["id"], "CI-CODE-001")


if __name__ == "__main__":
    unittest.main()
