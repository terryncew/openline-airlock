#!/usr/bin/env python3
"""OBSTRUCTION-001: Evaluator.

Runs hidden tests against a proposed fix. Mechanical, no human judgment.
Used by the experimenter to score solver attempts.

Usage:
  python evaluate.py <problem_id> <solution_file>
  
Reads ground_truth.json for hidden tests. Outputs JSON with pass/fail.
The solver never runs this directly during the experiment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

def evaluate(problem_id: str, solution_code: str, truth_file: str = "evaluator/ground_truth.json") -> dict:
    """Run hidden tests. Returns {passed, failed, total, failures}."""
    truth = json.loads((HERE / truth_file).read_text())
    if problem_id not in truth:
        return {"error": f"Unknown problem: {problem_id}"}
    
    prob_truth = truth[problem_id]
    hidden_tests = prob_truth["hidden_tests"]
    template = prob_truth.get("template", problem_id.split("_")[0].lower())
    
    # Extract function name from problem_id or template
    # Problem IDs are like A_00, B_01, H_00. Template is in solver problems.
    # For now, derive from the correct code.
    correct_code = prob_truth["correct_code"]
    # Find "def <name>("
    import re
    m = re.search(r"def (\w+)\(", correct_code)
    if not m:
        return {"error": "Could not find function name"}
    func_name = m.group(1)
    
    namespace = {}
    try:
        exec(solution_code, namespace)
    except Exception as e:
        return {"passed": 0, "failed": len(hidden_tests),
                "total": len(hidden_tests),
                "failures": [{"error": f"Code does not execute: {e}"}]}
    
    if func_name not in namespace:
        return {"passed": 0, "failed": len(hidden_tests),
                "total": len(hidden_tests),
                "failures": [{"error": f"Function {func_name} not defined"}]}
    
    func = namespace[func_name]
    failures = []
    passed = 0
    
    for args, expected in hidden_tests:
        try:
            result = func(*args)
            if result == expected:
                passed += 1
            else:
                failures.append({
                    "args": args,
                    "expected": expected,
                    "got": result,
                })
        except Exception as e:
            failures.append({
                "args": args,
                "expected": expected,
                "got": f"EXCEPTION: {type(e).__name__}: {e}",
            })
    
    return {
        "passed": passed,
        "failed": len(failures),
        "total": len(hidden_tests),
        "failures": failures,
        "solved": len(failures) == 0,
    }

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <problem_id> <solution_file>")
        sys.exit(1)
    
    problem_id = sys.argv[1]
    solution_file = Path(sys.argv[2])
    solution_code = solution_file.read_text()
    
    # Check if it's a holdout problem
    truth_file = "evaluator/ground_truth.json"
    if problem_id.startswith("H_"):
        truth_file = "evaluator/holdout_truth.json"
    
    result = evaluate(problem_id, solution_code, truth_file)
    print(json.dumps(result, indent=2))
    
    # Exit code 0 if solved, 1 otherwise
    sys.exit(0 if result.get("solved") else 1)

if __name__ == "__main__":
    main()
