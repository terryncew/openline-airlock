from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from retry_policy import may_retry


class RetryPolicyTests(unittest.TestCase):
    def test_zero_retry_budget_stops_after_initial_failure(self):
        self.assertFalse(may_retry(1, 0))

    def test_one_retry_budget_allows_exactly_one_retry(self):
        self.assertTrue(may_retry(1, 1))
        self.assertFalse(may_retry(2, 1))


if __name__ == "__main__":
    unittest.main()

