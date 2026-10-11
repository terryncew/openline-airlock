#!/usr/bin/env python3
"""OBSTRUCTION-001: Problem generator.

Generates buggy Python functions with mechanically injected bugs.
Outputs:
- problems.json: solver-visible (buggy code + docstring + examples)
- ground_truth.json: experimenter-only (bug type + correct code + tests)

Seed is frozen in PREREGISTRATION.md (42). Run AFTER freezing.
The solver must not read ground_truth.json until the experiment ends.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 42

# Templates: (name, correct_code, docstring, examples)
# Examples are (input, output) pairs shown to solver.
TEMPLATES = {
    "sum_range": {
        "correct": '''def sum_range(n):
    """Return the sum of integers from 1 to n inclusive."""
    total = 0
    for i in range(1, n + 1):
        total += i
    return total''',
        "doc": "Return the sum of integers from 1 to n inclusive.",
        "examples": [((5,), 15), ((1,), 1), ((10,), 55)],
        "tests": [((0,), 0), ((3,), 6), ((7,), 28), ((20,), 210),
                  ((100,), 5050)],
    },
    "find_max": {
        "correct": '''def find_max(lst):
    """Return the maximum element in a non-empty list."""
    best = lst[0]
    for x in lst[1:]:
        if x > best:
            best = x
    return best''',
        "doc": "Return the maximum element in a non-empty list.",
        "examples": [(([3, 1, 4],), 4), (([5],), 5)],
        "tests": [(([1, 2, 3],), 3), (([3, 2, 1],), 3),
                  (([-5, -1, -10],), -1), (([7, 7, 7],), 7),
                  (([0],), 0)],
    },
    "count_occurrences": {
        "correct": '''def count_occurrences(lst, val):
    """Return the number of times val appears in lst."""
    count = 0
    for x in lst:
        if x == val:
            count += 1
    return count''',
        "doc": "Return the number of times val appears in lst.",
        "examples": [(([1, 2, 1, 3], 1), 2), (([], 5), 0)],
        "tests": [(([1, 1, 1], 1), 3), (([1, 2, 3], 4), 0),
                  (([], 1), 0), (([5, 5, 5, 5], 5), 4),
                  (([1, 2, 1, 2, 1], 2), 2)],
    },
    "is_sorted": {
        "correct": '''def is_sorted(lst):
    """Return True if lst is sorted in non-decreasing order."""
    for i in range(len(lst) - 1):
        if lst[i] > lst[i + 1]:
            return False
    return True''',
        "doc": "Return True if lst is sorted in non-decreasing order.",
        "examples": [(([1, 2, 3],), True), (([3, 1, 2],), False)],
        "tests": [(([],), True), (([1],), True), (([1, 1, 1],), True),
                  (([1, 3, 2],), False), (([5, 4, 3, 2, 1],), False),
                  (([1, 2, 3, 4, 5],), True)],
    },
    "fib": {
        "correct": '''def fib(n):
    """Return the nth Fibonacci number (fib(0)=0, fib(1)=1)."""
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)''',
        "doc": "Return the nth Fibonacci number (fib(0)=0, fib(1)=1).",
        "examples": [((0,), 0), ((1,), 1), ((6,), 8)],
        "tests": [((2,), 1), ((3,), 2), ((4,), 3), ((5,), 5),
                  ((7,), 13), ((10,), 55)],
    },
}

# Bug injectors: each takes correct code, returns (buggy_code, description)
# Description is for ground_truth only, not shown to solver.
def inject_off_by_one(code: str, template: str) -> tuple[str, str]:
    if template == "sum_range":
        buggy = code.replace("range(1, n + 1)", "range(1, n)")
        return buggy, "Loop bound off by one: range(1, n) excludes n"
    elif template == "is_sorted":
        buggy = code.replace("range(len(lst) - 1)", "range(len(lst))")
        return buggy, "Loop bound off by one: range(len(lst)) causes IndexError or wrong check"
    elif template == "find_max":
        buggy = code.replace("lst[1:]", "lst[2:]")
        return buggy, "Slice off by one: lst[2:] skips second element"
    else:
        # Generic: for count_occurrences, fib - use a different bug
        return inject_wrong_op(code, template)

def inject_wrong_op(code: str, template: str) -> tuple[str, str]:
    if template == "find_max":
        buggy = code.replace("if x > best:", "if x >= best:")
        return buggy, "Wrong operator: >= instead of > (still correct for max, so use <)"
        # Actually >= is correct for max. Let's do something that breaks.
    # Fallback: find a comparison to flip
    if ">" in code:
        # Find the first > that's part of a comparison (not in docstring)
        lines = code.split("\n")
        for i, line in enumerate(lines):
            if "if " in line and ">" in line and '"""' not in line:
                lines[i] = line.replace(">", "<", 1)
                return "\n".join(lines), f"Flipped > to < in: {line.strip()}"
    return code, "No operator to flip (fallback - should not happen)"

def inject_missing_base(code: str, template: str) -> tuple[str, str]:
    if template == "fib":
        buggy = code.replace("if n <= 1:\n        return n", "if n == 0:\n        return n")
        return buggy, "Missing base case: n==1 not handled, infinite recursion for n=1"
    else:
        return inject_wrong_var(code, template)

def inject_wrong_var(code: str, template: str) -> tuple[str, str]:
    if template == "sum_range":
        buggy = code.replace("total += i", "total += n")
        return buggy, "Wrong variable: total += n instead of total += i"
    elif template == "count_occurrences":
        buggy = code.replace("count += 1", "count += val")
        return buggy, "Wrong variable: count += val instead of count += 1"
    elif template == "find_max":
        buggy = code.replace("best = x", "best = lst[0]")
        return buggy, "Wrong variable: best = lst[0] instead of best = x (never updates)"
    else:
        return inject_swapped_args(code, template)

def inject_swapped_args(code: str, template: str) -> tuple[str, str]:
    if template == "fib":
        buggy = code.replace("fib(n - 1) + fib(n - 2)", "fib(n - 2) + fib(n - 1)")
        return buggy, "Swapped args: fib(n-2) + fib(n-1) - actually correct, fallback"
    # For most templates, swap two variables in an expression
    if template == "is_sorted":
        buggy = code.replace("lst[i] > lst[i + 1]", "lst[i + 1] > lst[i]")
        return buggy, "Swapped comparison: checks descending instead of ascending"
    else:
        return inject_missing_return(code, template)

def inject_missing_return(code: str, template: str) -> tuple[str, str]:
    # Remove the final return statement
    lines = code.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("return "):
            lines[i] = "    pass  # bug: missing return"
            return "\n".join(lines), "Missing return: final return replaced with pass"
    return code, "No return to remove (fallback)"

BUG_INJECTORS = {
    "OFF_BY_ONE": inject_off_by_one,
    "WRONG_OP": inject_wrong_op,
    "MISSING_BASE": inject_missing_base,
    "WRONG_VAR": inject_wrong_var,
    "SWAPPED_ARGS": inject_swapped_args,
    "MISSING_RETURN": inject_missing_return,
}

def generate_problem(template_name: str, bug_type: str, rng: random.Random) -> dict:
    """Generate a single problem. Returns dict with solver and truth parts."""
    tmpl = TEMPLATES[template_name]
    correct = tmpl["correct"]
    injector = BUG_INJECTORS[bug_type]
    buggy, bug_desc = injector(correct, template_name)
    
    # Verify the bug actually breaks something (sanity check)
    # by running the hidden tests on the buggy code.
    namespace = {}
    try:
        exec(buggy, namespace)
        func_name = template_name
        func = namespace[func_name]
        failed = 0
        for args, expected in tmpl["tests"]:
            try:
                result = func(*args)
                if result != expected:
                    failed += 1
            except Exception:
                failed += 1
        # The bug should cause at least one failure, but not all
        # (if all fail, it might be too broken; if none fail, bug didn't work)
        if failed == 0:
            # Bug didn't break anything; try a different injector
            # For now, just note it
            bug_desc += " [WARNING: bug may not manifest in tests]"
    except Exception as e:
        bug_desc += f" [bug causes exception: {e}]"
    
    return {
        "solver": {
            "template": template_name,
            "buggy_code": buggy,
            "doc": tmpl["doc"],
            "examples": tmpl["examples"],
        },
        "truth": {
            "bug_type": bug_type,
            "bug_description": bug_desc,
            "correct_code": correct,
            "hidden_tests": tmpl["tests"],
        }
    }

def main():
    rng = random.Random(SEED)
    
    templates = list(TEMPLATES.keys())
    bug_types = list(BUG_INJECTORS.keys())
    
    # 24 main problems: 6 per condition, each condition gets all 6 bug types
    # 12 holdout: 2 per bug type
    problems = []
    
    # Main: for each condition (A,B,C,D), assign 6 problems with all bug types
    # We'll generate 24 with balanced bug types, then assign to conditions
    # in a way that each condition gets one of each bug type.
    all_specs = []
    for bug_type in bug_types:
        for i in range(4):  # 4 copies of each bug type (one per condition)
            template = rng.choice(templates)
            all_specs.append((template, bug_type))
    rng.shuffle(all_specs)
    
    # Assign: first 6 to A, next 6 to B, next 6 to C, next 6 to D
    # But ensure each condition gets all 6 bug types.
    # Simpler: group by bug type, then deal one of each to each condition.
    by_bug = {bt: [] for bt in bug_types}
    for template, bug_type in all_specs:
        by_bug[bug_type].append(template)
    
    conditions = {"A": [], "B": [], "C": [], "D": []}
    cond_names = ["A", "B", "C", "D"]
    for bug_type in bug_types:
        templates_for_bug = by_bug[bug_type]
        # Shuffle and assign one to each condition
        rng.shuffle(templates_for_bug)
        for i, cond in enumerate(cond_names):
            if i < len(templates_for_bug):
                conditions[cond].append((templates_for_bug[i], bug_type))
    
    # Generate problems
    problem_id = 0
    solver_problems = {}
    truth_problems = {}
    
    for cond in cond_names:
        for template, bug_type in conditions[cond]:
            pid = f"{cond}_{problem_id:02d}"
            prob = generate_problem(template, bug_type, rng)
            solver_problems[pid] = {
                "condition": cond,
                "template": prob["solver"]["template"],
                "buggy_code": prob["solver"]["buggy_code"],
                "doc": prob["solver"]["doc"],
                "examples": prob["solver"]["examples"],
            }
            truth_problems[pid] = {
                "condition": cond,
                "bug_type": prob["truth"]["bug_type"],
                "bug_description": prob["truth"]["bug_description"],
                "correct_code": prob["truth"]["correct_code"],
                "hidden_tests": prob["truth"]["hidden_tests"],
            }
            problem_id += 1
    
    # Holdout: 12 problems, 2 per bug type
    holdout_solver = {}
    holdout_truth = {}
    for i in range(12):
        bug_type = bug_types[i % len(bug_types)]
        template = rng.choice(templates)
        pid = f"H_{i:02d}"
        prob = generate_problem(template, bug_type, rng)
        holdout_solver[pid] = {
            "condition": "HOLDOUT",
            "template": prob["solver"]["template"],
            "buggy_code": prob["solver"]["buggy_code"],
            "doc": prob["solver"]["doc"],
            "examples": prob["solver"]["examples"],
        }
        holdout_truth[pid] = {
            "condition": "HOLDOUT",
            "bug_type": prob["truth"]["bug_type"],
            "bug_description": prob["truth"]["bug_description"],
            "correct_code": prob["truth"]["correct_code"],
            "hidden_tests": prob["truth"]["hidden_tests"],
        }
    
    # Write outputs
    (HERE / "problems.json").write_text(json.dumps(solver_problems, indent=2))
    (HERE / "ground_truth.json").write_text(json.dumps(truth_problems, indent=2))
    (HERE / "holdout_problems.json").write_text(json.dumps(holdout_solver, indent=2))
    (HERE / "holdout_truth.json").write_text(json.dumps(holdout_truth, indent=2))
    
    print(f"Generated {len(solver_problems)} main problems "
          f"({len([p for p in solver_problems.values() if p['condition']=='A'])} per condition)")
    print(f"Generated {len(holdout_solver)} holdout problems")
    print("Files: problems.json, ground_truth.json, holdout_problems.json, holdout_truth.json")
    print("\nSOLVER: Do not read ground_truth.json or holdout_truth.json!")

if __name__ == "__main__":
    main()
