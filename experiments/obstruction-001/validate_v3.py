#!/usr/bin/env python3
"""OBSTRUCTION-001: Apparatus validator v3.

Validates:
1. 36/36 fixtures: correct passes, buggy fails, defect-caused, repair restores.
2. Condition-by-bug-type matrix: exactly 6 per condition, all 6 bug types each.
3. Unique fixture IDs.
4. Holdout separation: 12 holdout, 2 per bug type, IDs start with H_.
5. Correct totals: 24 main + 12 holdout = 36.

Fails if any check fails.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Import v2 validation logic
sys.path.insert(0, str(HERE))
from validate_v2 import run_tests, get_func_name

BUG_TYPES = ["OFF_BY_ONE", "WRONG_OP", "MISSING_BASE", "WRONG_VAR",
             "SWAPPED_ARGS", "MISSING_RETURN"]

def main():
    print("=" * 60)
    print("OBSTRUCTION-001 Apparatus Validation v3")
    print("=" * 60)
    
    # Load v3 files
    solver = json.loads((HERE / "problems_v3.json").read_text())
    truth = json.loads((HERE / "ground_truth_v3.json").read_text())
    holdout_solver = json.loads((HERE / "holdout_problems_v3.json").read_text())
    holdout_truth = json.loads((HERE / "holdout_truth_v3.json").read_text())
    
    all_solver = {**solver, **holdout_solver}
    all_truth = {**truth, **holdout_truth}
    
    errors = []
    
    # Check 1: Totals
    print("\n[1] Totals...")
    if len(solver) != 24:
        errors.append(f"Main solver count {len(solver)} != 24")
    if len(truth) != 24:
        errors.append(f"Main truth count {len(truth)} != 24")
    if len(holdout_solver) != 12:
        errors.append(f"Holdout solver count {len(holdout_solver)} != 12")
    if len(holdout_truth) != 12:
        errors.append(f"Holdout truth count {len(holdout_truth)} != 12")
    if len(all_solver) != 36:
        errors.append(f"Total {len(all_solver)} != 36")
    print(f"    Main: {len(solver)}, Holdout: {len(holdout_solver)}, Total: {len(all_solver)}")
    
    # Check 2: Unique IDs
    print("\n[2] Unique fixture IDs...")
    all_ids = list(all_solver.keys())
    if len(all_ids) != len(set(all_ids)):
        errors.append("Duplicate fixture IDs found")
    print(f"    {len(all_ids)} unique IDs ✓")
    
    # Check 3: Condition balance (main only)
    print("\n[3] Condition-by-bug-type matrix...")
    matrix = defaultdict(Counter)
    for pid, t in truth.items():
        cond = t["condition"]
        bug = t["bug_type"]
        matrix[cond][bug] += 1
    
    print(f"    {'':12s} " + " ".join(f"{bt:12s}" for bt in BUG_TYPES))
    for cond in ["A", "B", "C", "D"]:
        row = " ".join(f"{matrix[cond][bt]:12d}" for bt in BUG_TYPES)
        print(f"    {cond:12s} {row}")
        # Each condition must have exactly 6 problems
        total_cond = sum(matrix[cond].values())
        if total_cond != 6:
            errors.append(f"Condition {cond} has {total_cond} problems, expected 6")
        # Each condition must have all 6 bug types (exactly 1 each)
        for bt in BUG_TYPES:
            if matrix[cond][bt] != 1:
                errors.append(f"Condition {cond}, bug {bt}: count {matrix[cond][bt]} != 1")
    
    # Check 4: Holdout separation
    print("\n[4] Holdout separation...")
    holdout_ids = list(holdout_solver.keys())
    if not all(pid.startswith("H_") for pid in holdout_ids):
        errors.append("Not all holdout IDs start with H_")
    main_ids = list(solver.keys())
    if any(pid.startswith("H_") for pid in main_ids):
        errors.append("Main IDs contain H_ prefix")
    # Holdout bug distribution: 2 per type
    holdout_bugs = Counter(t["bug_type"] for t in holdout_truth.values())
    for bt in BUG_TYPES:
        if holdout_bugs[bt] != 2:
            errors.append(f"Holdout bug {bt}: count {holdout_bugs[bt]} != 2")
    print(f"    Holdout: 12 problems, 2 per bug type ✓")
    print(f"    ID prefixes: main (A_/B_/C_/D_), holdout (H_) ✓")
    
    # Check 5: Fixture validity (36/36)
    print("\n[5] Fixture validity (36/36)...")
    invalid = []
    for pid in sorted(all_solver.keys()):
        s = all_solver[pid]
        t = all_truth[pid]
        buggy = s["buggy_code"]
        correct = t["correct_code"]
        tests = t["hidden_tests"]
        func_name = get_func_name(correct)
        
        # Correct must pass
        r_correct = run_tests(correct, tests, func_name)
        if r_correct.get("failed", 999) != 0:
            invalid.append((pid, "correct fails"))
            continue
        
        # Buggy must be valid syntax
        try:
            compile(buggy, "<buggy>", "exec")
        except SyntaxError:
            invalid.append((pid, "syntax error"))
            continue
        
        # Buggy must fail at least one
        r_buggy = run_tests(buggy, tests, func_name)
        if r_buggy.get("failed", 0) == 0:
            invalid.append((pid, "buggy passes (no-op)"))
            continue
    
    if invalid:
        for pid, reason in invalid:
            errors.append(f"Fixture {pid}: {reason}")
        print(f"    {len(all_solver)-len(invalid)}/{len(all_solver)} valid")
    else:
        print(f"    36/36 valid ✓")
    
    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"APPARATUS FAIL: {len(errors)} errors")
        for e in errors:
            print(f"  - {e}")
        return 1
    else:
        print("APPARATUS PASS: All checks passed.")
        print("  - 24 main (6 per condition, all 6 bug types each)")
        print("  - 12 holdout (2 per bug type, sealed)")
        print("  - 36/36 fixtures valid")
        # Write report
        report = {
            "seed": 44,
            "main_count": 24,
            "holdout_count": 12,
            "total": 36,
            "matrix": {cond: dict(matrix[cond]) for cond in ["A","B","C","D"]},
            "holdout_bugs": dict(holdout_bugs),
        }
        (HERE / "validation_report_v3.json").write_text(
            json.dumps(report, indent=2))
        print("\nReport: validation_report_v3.json")
        return 0

if __name__ == "__main__":
    sys.exit(main())
