#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "experiments" / "airlock-self-001" / "office_ops.py"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("airlock_self_001_office_ops", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_module(module) -> dict[str, bool]:
    checks = {
        "first_over_budget_none": module.first_over_budget([1, 2, 3], 10) is None,
        "first_over_budget_exact_not_over": module.first_over_budget([5, 5], 10) is None,
        "first_over_budget_first_cross": module.first_over_budget([4, 4, 4], 10) == 2,
        "first_over_budget_negative_then_cross": module.first_over_budget([-5, 20], 10) == 1,
        "first_over_budget_generator": module.first_over_budget((x for x in [3, 3, 5]), 10) == 2,
        "invoice_total_empty": module.invoice_total([]) == 0,
        "invoice_total_values": module.invoice_total([105, 200, -5]) == 300,
        "discount_zero": module.discount_amount(1000, 0) == 0,
        "discount_floor": module.discount_amount(999, 333) == 33,
        "discount_full": module.discount_amount(12345, 10_000) == 12345,
    }
    return checks


def main() -> int:
    module = load_module(TARGET)
    checks = check_module(module)
    result = {
        "schema": "airlock.self001.protected-checks.v1",
        "checks": checks,
        "passed": all(checks.values()),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
