# OBSTRUCTION-001 Preregistration

**Frozen:** 2026-10-11 (before any problems generated or attempts made)
**Status:** FROZEN — no changes after this point without explicit order.

## Research Question

Does providing an independently verified explanation of the precise
obstacle preventing a failed solution improve AI problem-solving beyond:
(a) structured search with normal feedback,
(b) seeing previous failures,
(c) receiving the same amount of information with irrelevant content?

Separately: can the agent discover accurate obstructions itself (distinct
from benefiting when supplied)?

## Domain

Debugging small Python functions with mechanically injected bugs.

**Rationale:**
- Objectively checkable: hidden tests pass/fail deterministically.
- Unfamiliar instances: bugs injected programmatically with seeded RNG;
  solver sees only the buggy code, not the bug type.
- Verifiable obstructions: experimenter knows ground-truth bug type and
  can confirm the explanation matches the actual obstacle.
- $0 cost: Python + solver reasoning, no paid APIs.

## Problem Structure

Each problem consists of:
- A Python function (10-30 lines) with a SINGLE injected bug.
- A docstring describing intended behavior.
- 2-3 example inputs/outputs (not the hidden tests).
- Hidden tests (5-8 cases) that the solution must pass.

**Bug taxonomy (fixed, 6 types):**
1. OFF_BY_ONE: loop bound off by one (e.g., `range(n)` vs `range(n+1)`)
2. WRONG_OP: wrong comparison operator (e.g., `<` vs `<=`)
3. MISSING_BASE: missing base case in recursion
4. WRONG_VAR: incorrect variable in expression (e.g., `x` vs `y`)
5. SWAPPED_ARGS: two arguments swapped in a call
6. MISSING_RETURN: missing return statement (falls through to None)

**Templates (fixed, 5 types):**
1. `sum_range(n)`: sum of integers from 1 to n
2. `find_max(lst)`: maximum element in a list
3. `count_occurrences(lst, val)`: count occurrences of val in lst
4. `is_sorted(lst)`: check if list is sorted ascending
5. `fib(n)`: nth Fibonacci number (recursive)

**Generation:**
- Seeded RNG (seed frozen in protocol).
- For each problem: pick template (uniform), pick bug type (uniform),
  pick parameters (e.g., specific variable names, constants).
- Inject the bug into the template.
- Generate hidden tests from the CORRECT implementation.
- The solver never sees the bug type, template ID, or generation seed.

## Conditions

Within-solver (Muse), between-problems (different problem sets per
condition, matched for difficulty by bug-type distribution).

Each problem allows **3 attempts**. Same total budget per condition.

**Condition A — Structured search (6 problems):**
- Attempt 1: Receive buggy code + docstring + examples. Propose fix.
- After each failed attempt: Receive "Tests [list] failed." No other info.
- Attempt 2, 3: Same.

**Condition B — Failure history (6 problems):**
- Same as A, plus: after each failed attempt, receive the previous
  attempt's code alongside the test failures.
- "Tests [list] failed. Your previous attempt was: [code]."

**Condition C — Verified obstruction (6 problems):**
- Same as B, plus: after each failed attempt, receive a verified
  explanation of the precise obstacle.
- Format: "Your fix [brief description]. It fails because [precise
  obstacle]. The bug is [location/type], and your change doesn't
  address it because [reason]."
- The obstruction is written by the experimenter using:
  - Ground-truth bug type (from generation log)
  - The solver's attempted fix
  - The observed test failures
- Verified: the explanation must correctly identify the bug location
  and explain why the attempted fix doesn't resolve it, as confirmed
  by running the tests.

**Condition D — Control (6 problems):**
- Same as B, plus: receive an "explanation" that is a real verified
  obstruction from a DIFFERENT problem (different bug type).
- Controls for information amount while testing content relevance.
- Format identical to C, but content is mismatched.

**Problem sets:**
- 24 problems total for main experiment (6 per condition).
- Bug types balanced: each condition gets one of each of the 6 bug types.
- Templates rotated to avoid template-condition confounds.
- 12 holdout problems (separate set, 2 per bug type) for transfer test.

## Procedure

**Phase 1 — Main experiment (24 problems):**
1. Generate all 24 problems (seeded). Experimenter does not reveal
   bug types to solver.
2. Solver attempts problems in randomized order (across conditions,
   to avoid order effects). For each problem:
   - Receive condition-appropriate prompt.
   - Make up to 3 attempts.
   - After each attempt, evaluator runs hidden tests (mechanical).
   - Receive condition-appropriate feedback.
3. Record: solved (bool), attempts used, final code.

**Phase 2 — Transfer test (12 holdout problems):**
1. After Phase 1, solver attempts 12 holdout problems.
2. All holdout problems use Condition A format (structured search only,
   no obstructions).
3. Compare solver's holdout performance to Condition A baseline.
4. If holdout > A, suggests transfer of obstruction-derived insight.
   If holdout ≈ A, obstructions were problem-specific hints.

**Phase 3 — Discovery test (separate):**
1. Select 6 failed attempts from Phase 1 (across conditions).
2. Solver (as "discoverer") receives: buggy code + failed attempt +
   test failures. Task: "Explain the precise obstacle preventing this
   solution."
3. Experimenter (with ground truth) scores each explanation:
   - Correctly identifies bug location? (yes/no)
   - Correctly explains why the attempt failed? (yes/no)
   - No hallucinations? (yes/no)
4. This tests discovery ability, separate from benefit when supplied.

## Metrics

**Primary:**
- Proportion solved within 3 attempts, per condition (A, B, C, D).

**Secondary:**
- Mean attempts to solution (among solved).
- Transfer: holdout solve rate vs Condition A solve rate.

**Evaluator:**
- Mechanical: hidden tests pass/fail. No human judgment.
- Scoring rules frozen here. Protected tests stored separately from
  solver's working directory.

## PASS / FAIL / INCONCLUSIVE (preregistered)

**PASS:** Condition C solves ≥ 2 more problems than B AND ≥ 2 more than D
(out of 6 each). This demonstrates that verified obstruction content
improves solving beyond failure history alone and beyond irrelevant
information.

**FAIL:** Difference between C and B is < 2 problems, OR difference
between C and D is < 2 problems, OR B/D outperform C. The obstruction
content does not provide meaningful benefit.

**INCONCLUSIVE:** 
- Results are mixed (e.g., C > B but C ≈ D, suggesting information
  amount matters but not content).
- Experiment cannot be completed as designed.
- Solver recognizes the problems (contamination).

**Stop conditions (halt experiment, report INCONCLUSIVE):**
- Equivalent conditions perform equally well after 12 problems
  (interim check): if A=B=C=D within 1 problem, stop.
- Results cannot be reproduced (solver's answers vary wildly on
  re-attempt).
- Cannot run within $0 (should not occur; no APIs used).

## Controls and Integrity

- Evaluator (test runner), scoring rules, and protected tests are in
  `experiments/obstruction-001/evaluator/` — outside the solver's
  working directory during attempts.
- Solver works in `experiments/obstruction-001/solver/` with only the
  problem statement and condition-appropriate feedback.
- Generation seed: 42 (frozen). Problems generated AFTER this
  preregistration is frozen.
- No changes to Gateway. No paid APIs. No claims about OpenAI internals.
- No automatic merging. Stop for review after results.

## Deliverables

1. This preregistration (frozen).
2. Generation code + seed + problem sets (reproducible).
3. All solver attempts (code + timestamps).
4. All evaluator outputs (test results).
5. All obstructions supplied (Conditions C and D).
6. Cost accounting ($0, plus time).
7. Failure analysis: which bug types were hardest, where obstructions
   helped/hurt, qualitative observations.
8. Explicit PASS / FAIL / INCONCLUSIVE conclusion.

---

**Frozen by:** Muse (experimenter role)
**Date:** 2026-10-11
**Signature:** Protocol frozen before problem generation. No changes
without explicit order from Terrynce.
