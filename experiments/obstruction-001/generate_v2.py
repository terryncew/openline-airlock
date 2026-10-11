#!/usr/bin/env python3
"""OBSTRUCTION-001: Problem generator v2 (apparatus repair).

Fixes the injector flaw from v1. Each bug type is now template-specific
with guaranteed manifestation. No fallback no-ops.

Validation criteria (checked by validate.py):
1. Correct program passes all hidden tests.
2. Buggy program fails at least one hidden test.
3. Buggy program is syntactically valid (no harness error).
4. The defect is the intended one (recorded location matches).

Seed: 43 (fresh, v2). Original v1 seed 42 preserved in git history.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 43  # Fresh seed for v2 (v1 used 42)

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

# Template-specific injectors. Each returns (buggy_code, defect_location, description).
# defect_location is (line_number, line_content) for recording.
# Each injector is GUARANTEED to produce a bug that manifests in tests.

def _find_line(code: str, snippet: str) -> tuple[int, str]:
    """Find 1-indexed line number containing snippet."""
    for i, line in enumerate(code.split("\n"), 1):
        if snippet in line:
            return i, line.strip()
    raise ValueError(f"Snippet not found: {snippet}")

# --- sum_range injectors ---
def sr_off_by_one(code: str):
    buggy = code.replace("range(1, n + 1)", "range(1, n)")
    loc = _find_line(buggy, "range(1, n)")
    return buggy, loc, "OFF_BY_ONE: range(1, n) excludes n, sum is short by n"

def sr_wrong_var(code: str):
    buggy = code.replace("total += i", "total += n")
    loc = _find_line(buggy, "total += n")
    return buggy, loc, "WRONG_VAR: total += n adds n each iteration instead of i"

def sr_missing_return(code: str):
    buggy = code.replace("    return total", "    pass  # bug: missing return")
    loc = _find_line(buggy, "pass  # bug")
    return buggy, loc, "MISSING_RETURN: function returns None instead of total"

def sr_wrong_op(code: str):
    # Change the loop to go backwards incorrectly, or change comparison
    # For sum_range, we can change the range to start at 0 (includes 0, harmless)
    # Better: change to range(1, n+1) -> range(0, n+1) which adds 0 (still correct)
    # Let's do: total = 0 -> total = 1 (off by one in init)
    buggy = code.replace("    total = 0", "    total = 1")
    loc = _find_line(buggy, "total = 1")
    return buggy, loc, "WRONG_OP: total initialized to 1 instead of 0 (off by one)"

# --- find_max injectors ---
def fm_off_by_one(code: str):
    buggy = code.replace("for x in lst[1:]:", "for x in lst[2:]:")
    loc = _find_line(buggy, "lst[2:]")
    return buggy, loc, "OFF_BY_ONE: lst[2:] skips index 1, may miss max"

def fm_wrong_var(code: str):
    buggy = code.replace("            best = x", "            best = lst[0]")
    loc = _find_line(buggy, "best = lst[0]")
    # Only replace the one inside the if, not the initialization
    # The init is "    best = lst[0]", the update is "            best = x"
    # Our replace targets the indented one
    return buggy, loc, "WRONG_VAR: best = lst[0] instead of best = x (never updates)"

def fm_wrong_op(code: str):
    buggy = code.replace("if x > best:", "if x < best:")
    loc = _find_line(buggy, "if x < best:")
    return buggy, loc, "WRONG_OP: < instead of > finds minimum, not maximum"

def fm_missing_return(code: str):
    buggy = code.replace("    return best", "    pass  # bug: missing return")
    loc = _find_line(buggy, "pass  # bug")
    return buggy, loc, "MISSING_RETURN: function returns None instead of best"

# --- count_occurrences injectors ---
def co_wrong_var(code: str):
    buggy = code.replace("            count += 1", "            count += val")
    loc = _find_line(buggy, "count += val")
    return buggy, loc, "WRONG_VAR: count += val instead of count += 1"

def co_wrong_op(code: str):
    buggy = code.replace("if x == val:", "if x != val:")
    loc = _find_line(buggy, "if x != val:")
    return buggy, loc, "WRONG_OP: != instead of == counts non-matches"

def co_missing_return(code: str):
    buggy = code.replace("    return count", "    pass  # bug: missing return")
    loc = _find_line(buggy, "pass  # bug")
    return buggy, loc, "MISSING_RETURN: function returns None instead of count"

def co_off_by_one(code: str):
    # For count, off-by-one could be: for x in lst[:-1] (skips last)
    buggy = code.replace("    for x in lst:", "    for x in lst[:-1]:")
    loc = _find_line(buggy, "lst[:-1]")
    return buggy, loc, "OFF_BY_ONE: lst[:-1] skips last element"

# --- is_sorted injectors ---
def is_off_by_one(code: str):
    buggy = code.replace("range(len(lst) - 1)", "range(len(lst) - 2)")
    loc = _find_line(buggy, "range(len(lst) - 2)")
    return buggy, loc, "OFF_BY_ONE: range(len-2) skips last comparison"

def is_wrong_op(code: str):
    buggy = code.replace("if lst[i] > lst[i + 1]:", "if lst[i] < lst[i + 1]:")
    loc = _find_line(buggy, "if lst[i] < lst[i + 1]:")
    return buggy, loc, "WRONG_OP: < instead of > detects ascending pairs as violations"

def is_swapped_args(code: str):
    # Swap the comparison: check if lst[i+1] > lst[i] (same as wrong_op, but different name)
    # Instead, swap the return values: return False -> return True and vice versa
    buggy = code.replace("            return False", "            return True")
    buggy = buggy.replace("    return True", "    return False", 1)  # Only the last one
    # Actually, let's do it more carefully
    lines = code.split("\n")
    for i, line in enumerate(lines):
        if "return False" in line:
            lines[i] = line.replace("return False", "return True")
        elif line.strip() == "return True":
            # This is the final return; only replace if it's the last return
            # Check if we've already replaced the False
            pass
    # Simpler: swap the two returns
    buggy = code.replace("            return False\n    return True",
                         "            return True\n    return False")
    loc = _find_line(buggy, "return True")
    return buggy, loc, "SWAPPED_ARGS: return values swapped (True/False inverted)"

def is_missing_return(code: str):
    buggy = code.replace("    return True", "    pass  # bug: missing return")
    # Only replace the final one, not inside loop
    # The code has "            return False" (indented 12) and "    return True" (indented 4)
    lines = code.split("\n")
    for i in range(len(lines)-1, -1, -1):
        if lines[i] == "    return True":
            lines[i] = "    pass  # bug: missing return"
            break
    buggy = "\n".join(lines)
    loc = _find_line(buggy, "pass  # bug")
    return buggy, loc, "MISSING_RETURN: sorted lists return None instead of True"

# --- fib injectors ---
def fib_missing_base(code: str):
    buggy = code.replace("    if n <= 1:\n        return n",
                         "    if n == 0:\n        return n")
    loc = _find_line(buggy, "if n == 0:")
    return buggy, loc, "MISSING_BASE: n==1 not handled, infinite recursion"

def fib_wrong_op(code: str):
    buggy = code.replace("    if n <= 1:", "    if n < 1:")
    loc = _find_line(buggy, "if n < 1:")
    return buggy, loc, "WRONG_OP: n<1 instead of n<=1, fib(1) recurses infinitely"

def fib_wrong_var(code: str):
    buggy = code.replace("return fib(n - 1) + fib(n - 2)",
                         "return fib(n - 1) + fib(n - 1)")
    loc = _find_line(buggy, "fib(n - 1) + fib(n - 1)")
    return buggy, loc, "WRONG_VAR: fib(n-1)+fib(n-1) doubles instead of summing"

def fib_off_by_one(code: str):
    # fib off-by-one: return n+1 in base case? Or change recursion
    buggy = code.replace("        return n", "        return n + 1", 1)
    loc = _find_line(buggy, "return n + 1")
    return buggy, loc, "OFF_BY_ONE: base case returns n+1 instead of n"

# Mapping: template -> list of (bug_type, injector_func)
INJECTORS = {
    "sum_range": [
        ("OFF_BY_ONE", sr_off_by_one),
        ("WRONG_VAR", sr_wrong_var),
        ("MISSING_RETURN", sr_missing_return),
        ("WRONG_OP", sr_wrong_op),
    ],
    "find_max": [
        ("OFF_BY_ONE", fm_off_by_one),
        ("WRONG_VAR", fm_wrong_var),
        ("WRONG_OP", fm_wrong_op),
        ("MISSING_RETURN", fm_missing_return),
    ],
    "count_occurrences": [
        ("WRONG_VAR", co_wrong_var),
        ("WRONG_OP", co_wrong_op),
        ("MISSING_RETURN", co_missing_return),
        ("OFF_BY_ONE", co_off_by_one),
    ],
    "is_sorted": [
        ("OFF_BY_ONE", is_off_by_one),
        ("WRONG_OP", is_wrong_op),
        ("SWAPPED_ARGS", is_swapped_args),
        ("MISSING_RETURN", is_missing_return),
    ],
    "fib": [
        ("MISSING_BASE", fib_missing_base),
        ("WRONG_OP", fib_wrong_op),
        ("WRONG_VAR", fib_wrong_var),
        ("OFF_BY_ONE", fib_off_by_one),
    ],
}

def generate_problem(template_name: str, bug_type: str, injector_func,
                     rng: random.Random) -> dict:
    """Generate a single problem with guaranteed-valid bug."""
    tmpl = TEMPLATES[template_name]
    correct = tmpl["correct"]
    
    buggy, (line_no, line_content), bug_desc = injector_func(correct)
    
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
            "defect_location": {"line": line_no, "content": line_content},
            "correct_code": correct,
            "hidden_tests": tmpl["tests"],
        }
    }

def main():
    rng = random.Random(SEED)
    
    # We need 24 main + 12 holdout = 36 problems.
    # Each template has 4 injectors. 5 templates × 4 = 20 unique combos.
    # We need 36, so we'll use each combo at least once, then fill.
    
    # Build list of all (template, bug_type, injector) combos
    all_combos = []
    for template, injectors in INJECTORS.items():
        for bug_type, func in injectors:
            all_combos.append((template, bug_type, func))
    
    # For 36 problems, we'll cycle through combos
    # Main: 24 problems (ensure each bug type appears 4 times)
    # Let's count bug types
    from collections import Counter
    
    # Generate 36 specs: shuffle combos and take 36 (with repetition)
    rng.shuffle(all_combos)
    specs = []
    # First, ensure each of the 6 bug types appears 6 times (36/6=6)
    bug_types = ["OFF_BY_ONE", "WRONG_OP", "MISSING_BASE", "WRONG_VAR",
                 "SWAPPED_ARGS", "MISSING_RETURN"]
    # MISSING_BASE only in fib, SWAPPED_ARGS only in is_sorted
    # Let's just generate and check distribution
    
    # Simpler: generate 36 by cycling through shuffled combos
    extended = (all_combos * 2)[:36]  # 40 combos, take 36
    rng.shuffle(extended)
    specs = extended[:36]
    
    # Split: first 24 main, last 12 holdout
    main_specs = specs[:24]
    holdout_specs = specs[24:]
    
    # Assign conditions to main: 6 per condition, balanced bug types
    # Group main_specs by bug type
    by_bug = {}
    for template, bug_type, func in main_specs:
        by_bug.setdefault(bug_type, []).append((template, bug_type, func))
    
    conditions = {"A": [], "B": [], "C": [], "D": []}
    cond_names = ["A", "B", "C", "D"]
    # Deal round-robin from each bug type
    for bug_type in sorted(by_bug.keys()):
        items = by_bug[bug_type]
        rng.shuffle(items)
        for i, item in enumerate(items):
            cond = cond_names[i % 4]
            conditions[cond].append(item)
    
    # Generate
    solver_problems = {}
    truth_problems = {}
    pid_counter = 0
    
    for cond in cond_names:
        for template, bug_type, func in conditions[cond]:
            pid = f"{cond}_{pid_counter:02d}"
            prob = generate_problem(template, bug_type, func, rng)
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
                "defect_location": prob["truth"]["defect_location"],
                "correct_code": prob["truth"]["correct_code"],
                "hidden_tests": prob["truth"]["hidden_tests"],
            }
            pid_counter += 1
    
    # Holdout
    holdout_solver = {}
    holdout_truth = {}
    for i, (template, bug_type, func) in enumerate(holdout_specs):
        pid = f"H_{i:02d}"
        prob = generate_problem(template, bug_type, func, rng)
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
            "defect_location": prob["truth"]["defect_location"],
            "correct_code": prob["truth"]["correct_code"],
            "hidden_tests": prob["truth"]["hidden_tests"],
        }
    
    # Write to v2 files (preserve v1)
    (HERE / "problems_v2.json").write_text(json.dumps(solver_problems, indent=2))
    (HERE / "ground_truth_v2.json").write_text(json.dumps(truth_problems, indent=2))
    (HERE / "holdout_problems_v2.json").write_text(json.dumps(holdout_solver, indent=2))
    (HERE / "holdout_truth_v2.json").write_text(json.dumps(holdout_truth, indent=2))
    
    print(f"Generated {len(solver_problems)} main + {len(holdout_solver)} holdout (v2, seed {SEED})")
    print("Files: problems_v2.json, ground_truth_v2.json, holdout_problems_v2.json, holdout_truth_v2.json")

if __name__ == "__main__":
    main()
