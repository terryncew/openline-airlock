#!/usr/bin/env python3
"""OBSTRUCTION-001: Problem generator v3 (apparatus repair).

Fixes v2 condition-imbalance failure. Enforces strict allocation:
- Exactly 6 problems per condition (A, B, C, D) = 24 scored.
- Each condition gets ALL 6 bug types (one each) — comparable representation.
- 12 holdout (2 per bug type).
- Total 36, all validated.

Seed: 44 (chosen before generation, not searched).
v1 seed 42, v2 seed 43 preserved in git history.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 44  # v3 seed, chosen 2026-10-11 before generation

# Import v2 templates and injectors (unchanged logic)
import sys
sys.path.insert(0, str(HERE))
from generate_v2 import TEMPLATES, INJECTORS

# Bug types in fixed order
BUG_TYPES = ["OFF_BY_ONE", "WRONG_OP", "MISSING_BASE", "WRONG_VAR",
             "SWAPPED_ARGS", "MISSING_RETURN"]

def generate_problem(template_name: str, bug_type: str, injector_func) -> dict:
    """Generate a single problem. Same as v2."""
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

def pick_template_for_bug(bug_type: str, rng: random.Random,
                          used_templates: set) -> tuple[str, callable]:
    """Pick a template that supports this bug type, preferring unused."""
    candidates = []
    for template, injectors in INJECTORS.items():
        for bt, func in injectors:
            if bt == bug_type:
                candidates.append((template, func))
    # Prefer templates not yet used (for diversity)
    unused = [(t, f) for t, f in candidates if t not in used_templates]
    pool = unused if unused else candidates
    return rng.choice(pool)

def main():
    rng = random.Random(SEED)
    
    solver_problems = {}
    truth_problems = {}
    holdout_solver = {}
    holdout_truth = {}
    
    pid_counter = 0
    
    # Main: 4 conditions × 6 bug types = 24 problems
    # Each condition gets one of each bug type
    for cond in ["A", "B", "C", "D"]:
        used_templates = set()
        # Shuffle bug type order per condition (to vary template assignment)
        bug_order = BUG_TYPES.copy()
        rng.shuffle(bug_order)
        for bug_type in bug_order:
            template, func = pick_template_for_bug(bug_type, rng, used_templates)
            used_templates.add(template)
            pid = f"{cond}_{pid_counter:02d}"
            prob = generate_problem(template, bug_type, func)
            solver_problems[pid] = {
                "condition": cond,
                "template": template,
                "buggy_code": prob["solver"]["buggy_code"],
                "doc": prob["solver"]["doc"],
                "examples": prob["solver"]["examples"],
            }
            truth_problems[pid] = {
                "condition": cond,
                "bug_type": bug_type,
                "bug_description": prob["truth"]["bug_description"],
                "defect_location": prob["truth"]["defect_location"],
                "correct_code": prob["truth"]["correct_code"],
                "hidden_tests": prob["truth"]["hidden_tests"],
            }
            pid_counter += 1
    
    # Holdout: 12 problems, 2 per bug type
    for i in range(12):
        bug_type = BUG_TYPES[i % len(BUG_TYPES)]
        # Pick template (allow reuse, but vary)
        template, func = pick_template_for_bug(bug_type, rng, set())
        pid = f"H_{i:02d}"
        prob = generate_problem(template, bug_type, func)
        holdout_solver[pid] = {
            "condition": "HOLDOUT",
            "template": template,
            "buggy_code": prob["solver"]["buggy_code"],
            "doc": prob["solver"]["doc"],
            "examples": prob["solver"]["examples"],
        }
        holdout_truth[pid] = {
            "condition": "HOLDOUT",
            "bug_type": bug_type,
            "bug_description": prob["truth"]["bug_description"],
            "defect_location": prob["truth"]["defect_location"],
            "correct_code": prob["truth"]["correct_code"],
            "hidden_tests": prob["truth"]["hidden_tests"],
        }
    
    # Write v3 files
    (HERE / "problems_v3.json").write_text(json.dumps(solver_problems, indent=2))
    (HERE / "ground_truth_v3.json").write_text(json.dumps(truth_problems, indent=2))
    (HERE / "holdout_problems_v3.json").write_text(json.dumps(holdout_solver, indent=2))
    (HERE / "holdout_truth_v3.json").write_text(json.dumps(holdout_truth, indent=2))
    
    # Print allocation matrix
    from collections import Counter, defaultdict
    matrix = defaultdict(Counter)
    for pid, t in truth_problems.items():
        matrix[t["condition"]][t["bug_type"]] += 1
    print("Condition-by-bug-type matrix (main, 24 problems):")
    print(f"{'':12s} " + " ".join(f"{bt:12s}" for bt in BUG_TYPES))
    for cond in ["A", "B", "C", "D"]:
        row = " ".join(f"{matrix[cond][bt]:12d}" for bt in BUG_TYPES)
        print(f"{cond:12s} {row}")
    
    print(f"\nGenerated 24 main + 12 holdout (v3, seed {SEED})")

if __name__ == "__main__":
    main()
