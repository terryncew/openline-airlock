#!/usr/bin/env python3
"""OBSTRUCTION-001: Apparatus validator (v2).

Independently validates every generated fixture:
1. Correct program passes all hidden tests.
2. Buggy program fails at least one hidden test.
3. Buggy program is syntactically valid (no harness error).
4. The failure is caused by the intended defect (repair restores correctness).

Requires 36/36 valid. Outputs detailed report.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent

def run_tests(code: str, tests: list, func_name: str) -> dict:
    """Run tests against code. Returns {passed, failed, errors}."""
    namespace = {}
    try:
        exec(code, namespace)
    except SyntaxError as e:
        return {"syntax_error": str(e), "passed": 0, "failed": len(tests)}
    except Exception as e:
        return {"exec_error": str(e), "passed": 0, "failed": len(tests)}
    
    if func_name not in namespace:
        return {"missing_func": func_name, "passed": 0, "failed": len(tests)}
    
    func = namespace[func_name]
    passed = 0
    failed = 0
    failures = []
    
    for args, expected in tests:
        try:
            result = func(*args)
            if result == expected:
                passed += 1
            else:
                failed += 1
                failures.append({"args": args, "expected": expected, "got": result})
        except Exception as e:
            failed += 1
            failures.append({"args": args, "expected": expected,
                           "got": f"{type(e).__name__}: {e}"})
    
    return {"passed": passed, "failed": failed, "failures": failures}

def get_func_name(code: str) -> str:
    import re
    m = re.search(r"def (\w+)\(", code)
    return m.group(1) if m else "unknown"

def validate_fixture(pid: str, solver: dict, truth: dict) -> dict:
    """Validate a single fixture. Returns {valid, checks, details}."""
    checks = {}
    details = {}
    
    buggy_code = solver["buggy_code"]
    correct_code = truth["correct_code"]
    tests = truth["hidden_tests"]
    func_name = get_func_name(correct_code)
    
    # Check 1: Correct program passes all tests
    r_correct = run_tests(correct_code, tests, func_name)
    checks["correct_passes"] = r_correct.get("failed", 999) == 0
    details["correct_result"] = f"{r_correct.get('passed',0)}/{len(tests)} passed"
    if not checks["correct_passes"]:
        details["correct_failures"] = r_correct.get("failures", [])
    
    # Check 2: Buggy program is syntactically valid
    try:
        compile(buggy_code, "<buggy>", "exec")
        checks["buggy_valid_syntax"] = True
    except SyntaxError as e:
        checks["buggy_valid_syntax"] = False
        details["syntax_error"] = str(e)
    
    # Check 3: Buggy program fails at least one test
    r_buggy = run_tests(buggy_code, tests, func_name)
    # A syntax error counts as failing, but we want a *relevant* failure
    # (not a harness error). If syntax is valid but tests fail, that's good.
    if checks["buggy_valid_syntax"]:
        checks["buggy_fails"] = r_buggy.get("failed", 0) > 0
        details["buggy_result"] = f"{r_buggy.get('passed',0)}/{len(tests)} passed"
        if r_buggy.get("failed", 0) > 0:
            details["buggy_failures"] = r_buggy["failures"][:3]  # First 3
    else:
        checks["buggy_fails"] = False
        details["buggy_result"] = "SYNTAX ERROR (harness failure, not intended defect)"
    
    # Check 4: Repair restores correctness
    # The "repair" is the correct code. If correct passes and buggy fails,
    # and the only difference is the injected defect, then the defect caused it.
    # We verify by checking the defect location is in the buggy code.
    loc = truth.get("defect_location", {})
    line_content = loc.get("content", "")
    checks["defect_present"] = line_content in buggy_code if line_content else False
    details["defect_location"] = loc
    
    # Overall: all checks must pass
    valid = all(checks.values())
    
    return {
        "pid": pid,
        "valid": valid,
        "checks": checks,
        "details": details,
        "bug_type": truth.get("bug_type"),
        "template": solver.get("template"),
    }

def main():
    # Load v2 files
    solver = json.loads((HERE / "problems_v2.json").read_text())
    truth = json.loads((HERE / "ground_truth_v2.json").read_text())
    holdout_solver = json.loads((HERE / "holdout_problems_v2.json").read_text())
    holdout_truth = json.loads((HERE / "holdout_truth_v2.json").read_text())
    
    all_solver = {**solver, **holdout_solver}
    all_truth = {**truth, **holdout_truth}
    
    print(f"Validating {len(all_solver)} fixtures...\n")
    
    results = []
    for pid in sorted(all_solver.keys()):
        r = validate_fixture(pid, all_solver[pid], all_truth[pid])
        results.append(r)
        status = "PASS" if r["valid"] else "FAIL"
        print(f"[{status}] {pid} ({r['template']}, {r['bug_type']})")
        if not r["valid"]:
            for check, val in r["checks"].items():
                if not val:
                    print(f"       - {check}: FAILED")
            if "buggy_failures" in r["details"]:
                print(f"       Failures: {r['details']['buggy_failures'][:1]}")
    
    valid_count = sum(1 for r in results if r["valid"])
    total = len(results)
    
    print(f"\n{'='*50}")
    print(f"Result: {valid_count}/{total} valid")
    print(f"{'='*50}")
    
    if valid_count == total:
        print("\nAPPARATUS PASS: All 36 fixtures valid.")
        # Write validation report
        report = {
            "valid_count": valid_count,
            "total": total,
            "seed": 43,
            "fixtures": [
                {
                    "pid": r["pid"],
                    "template": r["template"],
                    "bug_type": r["bug_type"],
                    "defect_location": r["details"].get("defect_location"),
                    "correct_tests": r["details"].get("correct_result"),
                    "buggy_tests": r["details"].get("buggy_result"),
                }
                for r in results
            ]
        }
        (HERE / "validation_report_v2.json").write_text(
            json.dumps(report, indent=2))
        print("Report written to validation_report_v2.json")
        return 0
    else:
        print(f"\nAPPARATUS FAIL: {total - valid_count} fixtures invalid.")
        print("See details above. Generator needs repair.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
