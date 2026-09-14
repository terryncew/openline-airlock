from __future__ import annotations

from decimal import Decimal
import importlib.util
from pathlib import Path
import sys
import unittest

RUNNER = Path(__file__).resolve().parents[1] / "run_ril_001d.py"
spec = importlib.util.spec_from_file_location("ril001d_runner_for_limit_tests", RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class LimitBindingTests(unittest.TestCase):
    def test_decimal_format_equivalence(self) -> None:
        self.assertTrue(runner.numeric_limit_equal("0.50", Decimal("0.5")))
        self.assertTrue(runner.numeric_limit_equal(0.5, "0.500"))

    def test_integer_representation_equivalence(self) -> None:
        self.assertTrue(runner.numeric_limit_equal("18", 18))
        self.assertTrue(runner.numeric_limit_equal("180000.0", 180000))

    def test_mismatch_rejected(self) -> None:
        self.assertFalse(runner.numeric_limit_equal("0.51", "0.5"))
        self.assertFalse(runner.numeric_limit_equal(17, 18))

    def test_non_numeric_and_boolean_rejected(self) -> None:
        self.assertFalse(runner.numeric_limit_equal("not-a-number", "0.5"))
        self.assertFalse(runner.numeric_limit_equal(False, 0))
        self.assertFalse(runner.numeric_limit_equal(None, 0))

    def test_complete_binding(self) -> None:
        recorded = {
            "max_iterations": "18",
            "max_output_tokens_per_request": 4096,
            "max_reported_total_tokens": "180000.0",
            "max_estimated_usd": "0.50",
        }
        expected = {
            "max_iterations": 18,
            "max_output_tokens_per_request": 4096,
            "max_reported_total_tokens": 180000,
            "max_estimated_usd": Decimal("0.5"),
        }
        self.assertTrue(runner.verify_limit_bindings(recorded, expected))
        recorded["max_estimated_usd"] = "0.5001"
        self.assertFalse(runner.verify_limit_bindings(recorded, expected))


if __name__ == "__main__":
    unittest.main()
