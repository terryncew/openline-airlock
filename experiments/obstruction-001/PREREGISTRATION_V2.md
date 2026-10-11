# OBSTRUCTION-001 Preregistration v2

**Version:** 2.0
**Frozen:** 2026-10-11
**Supersedes:** PREREGISTRATION.md v1.0 (2026-10-11, INCONCLUSIVE due to generator flaw)
**Status:** FROZEN — apparatus validated, no model trials yet.

## Changes from v1 (explicitly documented)

1. **Generator fixed:** v1 injectors had fallback paths producing no-op bugs
   (8/24 main + 4/12 holdout invalid). v2 uses template-specific injectors
   with guaranteed manifestation. Validated 36/36 (see validation_report_v2.json).

2. **Fresh seed:** v1 used seed 42. v2 uses seed 43. The v1 problems
   (seed 42) are preserved in git history but excluded from efficacy
   estimates per the repair authorization.

3. **Defect locations recorded:** v2 generator records the exact line
   number and content of each injected defect (see validation_report_v2.json).

4. **Obstruction quality verified:** Sample obstructions checked for
   accuracy and non-revelation (see OBSTRUCTION_QUALITY.md).

**Unchanged from v1:** Research question, hypothesis, four conditions
(A/B/C/D), 3-attempt budget, 6 problems per condition, 12 holdout,
metrics, PASS/FAIL/INCONCLUSIVE criteria, stop conditions, $0 constraint.

## Research Question (unchanged)

Does providing an independently verified explanation of the precise
obstacle preventing a failed solution improve AI problem-solving beyond:
(a) structured search with normal feedback,
(b) seeing previous failures,
(c) receiving the same amount of information with irrelevant content?

Separately: can the agent discover accurate obstructions itself?

## Domain (unchanged)

Debugging small Python functions with mechanically injected bugs.
$0 cost, objectively checkable, unfamiliar instances.

## Problem Structure (v2)

Each problem: Python function (10-30 lines) with SINGLE injected bug.
5 templates × 4 bug types each = 20 unique combos, 36 total problems.

**Templates (unchanged):** sum_range, find_max, count_occurrences, is_sorted, fib.

**Bug types (unchanged taxonomy, fixed injectors):**
1. OFF_BY_ONE — template-specific (e.g., sum_range: range(1,n) excludes n)
2. WRONG_OP — template-specific (e.g., find_max: < instead of >)
3. MISSING_BASE — fib only: n==0 instead of n<=1
4. WRONG_VAR — template-specific (e.g., sum_range: total+=n instead of total+=i)
5. SWAPPED_ARGS — is_sorted only: return values inverted
6. MISSING_RETURN — template-specific (final return → pass)

**Generation (v2):**
- Seed: 43 (frozen).
- 24 main problems (6 per condition, balanced bug types).
- 12 holdout problems.
- All 36 validated: correct passes, buggy fails, defect-caused, repair restores.
- Files: problems_v2.json (solver), ground_truth_v2.json (evaluator-only).

## Conditions (unchanged)

**A — Structured search (6 problems):** 3 attempts, test pass/fail only.
**B — Failure history (6 problems):** + previous attempt code.
**C — Verified obstruction (6 problems):** + verified explanation of precise obstacle.
**D — Control (6 problems):** + irrelevant/mismatched obstruction.

## Procedure (unchanged)

**Phase 1:** 24 problems, randomized order, 3 attempts each.
**Phase 2:** 12 holdout, Condition A format, test transfer.
**Phase 3:** Discovery test (6 failed attempts, solver generates obstructions).

## Metrics (unchanged)

**Primary:** Proportion solved within 3 attempts per condition.
**Secondary:** Mean attempts, holdout vs A transfer.

## PASS / FAIL / INCONCLUSIVE (unchanged)

**PASS:** C solves ≥2 more than B AND ≥2 more than D (of 6 each).
**FAIL:** C-B <2 OR C-D <2 OR B/D outperform C.
**INCONCLUSIVE:** Mixed results, cannot complete, or contamination.

**Stop conditions (unchanged):**
- A=B=C=D within 1 after 12 problems → stop.
- Irreproducible → stop.
- Cannot run within $0 → stop.

## Integrity (v2)

- Evaluator in `evaluator/` (ground_truth_v2.json, holdout_truth_v2.json).
- Solver in `solver/` sees only problems_v2.json, holdout_problems_v2.json.
- v1 observations (A_00, A_01) EXCLUDED from efficacy estimates.
- No model trials until apparatus passes review (this document).
- No Gateway changes. No paid APIs. No merges.

## Deliverables (v2)

1. PREREGISTRATION.md v1 (preserved, INCONCLUSIVE).
2. PREREGISTRATION_V2.md (this file, frozen).
3. generate_v2.py, validate_v2.py (apparatus).
4. validation_report_v2.json (36/36 evidence).
5. OBSTRUCTION_QUALITY.md (obstruction verification).
6. FAILURE_ANALYSIS.md v1 (preserved).
7. [Future] All attempts, evaluator outputs, obstructions, analysis, verdict.

---

**Frozen by:** Muse (experimenter role)
**Date:** 2026-10-11
**Apparatus verdict:** PASS (36/36 fixtures valid, see validation_report_v2.json)
**Note:** No AI problem-solving runs have occurred under v2. Awaiting review before Phase 1.
