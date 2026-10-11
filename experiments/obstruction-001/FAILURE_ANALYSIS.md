# OBSTRUCTION-001: Failure Analysis and Conclusion

**Date:** 2026-10-11
**Status:** STOPPED — Generator failure. INCONCLUSIVE.

## What happened

The experiment was preregistered and frozen (PREREGISTRATION.md).
The problem generator was implemented and run (seed 42, as frozen).

**Critical flaw discovered:** 12 out of 36 generated problems (33%)
contain bugs that do not manifest in the hidden tests. The bug injectors
for WRONG_OP, SWAPPED_ARGS, and OFF_BY_ONE have fallback paths that
produce no-ops when the template doesn't match the expected pattern.

Affected:
- Main set: 8/24 broken (A_01, A_04, B_07, C_13, C_16, D_18, D_19, D_22)
- Holdout set: 4/12 broken

## Partial results (before stop)

Two problems were attempted before the flaw was discovered:
- A_00 (find_max, OFF_BY_ONE): Solved on attempt 1. Valid problem.
- A_01 (fib, WRONG_OP): "Solved" on attempt 1, but the code was already
  correct. Invalid problem.

The invalid problems cannot test the hypothesis because there is no
bug to fix. The solver "succeeds" by submitting the already-correct code.

## Why this matters

The research question asks whether verified obstructions improve
problem-solving. If 33% of problems have no actual obstruction (the code
is already correct), the conditions cannot be meaningfully compared.
- Condition C (verified obstruction) would have nothing to explain.
- The solve rates would be inflated by trivial problems.
- Any difference between conditions could be due to the distribution
  of broken problems, not the obstruction content.

## Conclusion: INCONCLUSIVE

Per the preregistered stop conditions: "the experiment cannot be
completed as designed."

The generator must be fixed to ensure all injected bugs actually break
at least one hidden test. The preregistration would need to be amended
(with explicit order) to either:
1. Fix the injectors and regenerate (new seed, new freeze), or
2. Filter to only valid problems (reduces power, changes the design).

## What was built (reusable)

- `PREREGISTRATION.md`: Frozen protocol (valid).
- `generate.py`: Generator with flaw (needs fix).
- `evaluate.py`: Mechanical test runner (works).
- `problems.json`, `holdout_problems.json`: Solver-visible (33% invalid).
- `evaluator/ground_truth.json`, `evaluator/holdout_truth.json`:
  Experimenter-only (documents the flaw).

## Costs

- Paid APIs: $0 (as required).
- Time: ~2 hours (design, implementation, partial run, analysis).
- No Gateway changes. No merges.

## Recommendation

Fix the bug injectors to guarantee manifestation, then re-freeze with
a new seed. The protocol design is sound; the implementation needs
repair.

---

**Experimenter:** Muse
**Review requested:** Terrynce — how to proceed?
