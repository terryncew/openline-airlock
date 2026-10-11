#!/usr/bin/env python3
"""OBSTRUCTION-001: Regression tests for apparatus failures.

Reproduces:
1. v1 no-op failure: bug injectors producing bugs that don't manifest.
2. v2 condition-imbalance failure: uneven problems per condition.

These tests guard against regressions in future generator changes.
Run: python -m pytest test_apparatus_regression.py -v
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from validate_v2 import run_tests, get_func_name

def test_v1_noop_regression():
    """v1 failure: 12/36 fixtures had no-op bugs (didn't fail tests).
    
    Regression test: every buggy fixture must fail at least one hidden test.
    """
    # Load v3 (should pass)
    solver = json.loads((HERE / "problems_v3.json").read_text())
    truth = json.loads((HERE / "ground_truth_v3.json").read_text())
    holdout_solver = json.loads((HERE / "holdout_problems_v3.json").read_text())
    holdout_truth = json.loads((HERE / "holdout_truth_v3.json").read_text())
    
    all_solver = {**solver, **holdout_solver}
    all_truth = {**truth, **holdout_truth}
    
    noop_count = 0
    for pid in all_solver:
        s = all_solver[pid]
        t = all_truth[pid]
        buggy = s["buggy_code"]
        tests = t["hidden_tests"]
        func_name = get_func_name(t["correct_code"])
        
        r = run_tests(buggy, tests, func_name)
        if r.get("failed", 0) == 0:
            noop_count += 1
    
    assert noop_count == 0, (
        f"v1 no-op regression: {noop_count}/36 fixtures have no-op bugs "
        f"(buggy code passes all tests)"
    )

def test_v2_imbalance_regression():
    """v2 failure: conditions had 9/7/4/4 problems instead of 6/6/6/6.
    
    Regression test: each condition must have exactly 6 problems.
    """
    truth = json.loads((HERE / "ground_truth_v3.json").read_text())
    
    by_cond = Counter(t["condition"] for t in truth.values())
    
    for cond in ["A", "B", "C", "D"]:
        assert by_cond[cond] == 6, (
            f"v2 imbalance regression: condition {cond} has "
            f"{by_cond[cond]} problems, expected 6"
        )

def test_bug_type_coverage():
    """Each condition must have all 6 bug types (no systematic missing).
    
    v2 failure: C and D were missing MISSING_BASE and SWAPPED_ARGS.
    """
    truth = json.loads((HERE / "ground_truth_v3.json").read_text())
    
    BUG_TYPES = ["OFF_BY_ONE", "WRONG_OP", "MISSING_BASE", "WRONG_VAR",
                 "SWAPPED_ARGS", "MISSING_RETURN"]
    
    matrix = defaultdict(Counter)
    for t in truth.values():
        matrix[t["condition"]][t["bug_type"]] += 1
    
    for cond in ["A", "B", "C", "D"]:
        for bt in BUG_TYPES:
            assert matrix[cond][bt] == 1, (
                f"Bug coverage regression: condition {cond} has "
                f"{matrix[cond][bt]} of bug type {bt}, expected 1"
            )

def test_holdout_separation():
    """Holdout must be 12 problems, 2 per bug type, IDs start with H_."""
    holdout_solver = json.loads((HERE / "holdout_problems_v3.json").read_text())
    holdout_truth = json.loads((HERE / "holdout_truth_v3.json").read_text())
    
    assert len(holdout_solver) == 12
    assert len(holdout_truth) == 12
    assert all(pid.startswith("H_") for pid in holdout_solver)
    
    bugs = Counter(t["bug_type"] for t in holdout_truth.values())
    for bt in ["OFF_BY_ONE", "WRONG_OP", "MISSING_BASE", "WRONG_VAR",
               "SWAPPED_ARGS", "MISSING_RETURN"]:
        assert bugs[bt] == 2, f"Holdout bug {bt}: {bugs[bt]} != 2"

if __name__ == "__main__":
    # Simple runner (no pytest dependency)
    tests = [
        ("v1 no-op regression", test_v1_noop_regression),
        ("v2 imbalance regression", test_v2_imbalance_regression),
        ("bug type coverage", test_bug_type_coverage),
        ("holdout separation", test_holdout_separation),
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}")
        except AssertionError as e:
            print(f"[FAIL] {name}: {e}")
            failed += 1
    sys.exit(1 if failed else 0)
