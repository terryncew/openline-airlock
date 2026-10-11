# OBSTRUCTION-001 Preregistration v3

**Version:** 3.0
**Frozen:** 2026-10-11
**Supersedes:** 
- v1.0 (2026-10-11, INCONCLUSIVE — generator no-op flaw, 12/36 invalid)
- v2.0 (2026-10-11, APPARATUS PASS but Phase 1 blocked — condition imbalance 9/7/4/4)
**Status:** FROZEN — apparatus validated, no model trials yet.

## Changes from v2 (explicitly documented)

1. **Condition allocation fixed:** v2 produced 9/7/4/4 problems per condition.
   v3 enforces exactly 6 per condition (A, B, C, D) with all 6 bug types
   represented in each condition (1 each). Validated by `validate_v3.py`.

2. **Fresh seed:** v3 uses seed 44 (chosen before generation, not searched).
   v1 seed 42, v2 seed 43 preserved in git history.

3. **Regression tests added:** `test_apparatus_regression.py` reproduces
   both v1 (no-op) and v2 (imbalance) failures. All 4 tests pass on v3.

4. **Source revision recorded:** openline-airlock at d4c81e68d3ca.
   Generator: `generate_v3.py`. Validator: `validate_v3.py`.

**Unchanged from v1/v2:** Research question, hypothesis, four conditions
(A/B/C/D), 3-attempt budget, scoring thresholds (PASS: C ≥ B+2 AND C ≥ D+2),
stop criteria, $0 constraint. The v1 and v2 artifacts are preserved
unchanged.

## Research Question (unchanged)

Does providing an independently verified explanation of the precise
obstacle preventing a failed solution improve AI problem-solving beyond:
(a) structured search with normal feedback,
(b) seeing previous failures,
(c) receiving the same amount of information with irrelevant content?

Separately: can the agent discover accurate obstructions itself?

## Apparatus v3 (validated)

**Seed:** 44
**Fixtures:** 36 total (24 main + 12 holdout), all valid.

**Condition-by-bug-type matrix (main, 24 problems):**

| Condition | OFF_BY_ONE | WRONG_OP | MISSING_BASE | WRONG_VAR | SWAPPED_ARGS | MISSING_RETURN | Total |
|-----------|------------|----------|--------------|-----------|--------------|----------------|-------|
| A         | 1          | 1        | 1            | 1         | 1            | 1              | 6     |
| B         | 1          | 1        | 1            | 1         | 1            | 1              | 6     |
| C         | 1          | 1        | 1            | 1         | 1            | 1              | 6     |
| D         | 1          | 1        | 1            | 1         | 1            | 1              | 6     |

**Holdout:** 12 problems, 2 per bug type, IDs H_00 through H_11, sealed.

**Validation (validate_v3.py):**
- ✅ 24 main (6 per condition)
- ✅ 12 holdout (2 per bug type)
- ✅ 36 unique IDs (A_/B_/C_/D_ main, H_ holdout)
- ✅ 36/36 fixtures: correct passes, buggy fails, defect-caused
- ✅ Regression tests: 4/4 pass

Report: `validation_report_v3.json`

## Conditions (unchanged)

**A — Structured search:** 3 attempts, test pass/fail only.
**B — Failure history:** + previous attempt code.
**C — Verified obstruction:** + verified explanation of precise obstacle.
**D — Control:** + irrelevant/mismatched obstruction (same format, different problem).

## Procedure (unchanged)

**Phase 1:** 24 problems (A_00-A_05, B_06-B_11, C_12-C_17, D_18-D_23),
randomized order, 3 attempts each. Record all attempts, failures, solutions.

**Phase 2:** 12 holdout (H_00-H_11), Condition A format, test transfer.
Sealed until Phase 1 complete.

**Phase 3:** Discovery test (6 failed attempts, solver generates obstructions).

## Metrics (unchanged)

**Primary:** Proportion solved within 3 attempts per condition.
**Secondary:** Mean attempts, holdout vs A transfer.

## PASS / FAIL / INCONCLUSIVE (unchanged)

**PASS:** C solves ≥2 more than B AND ≥2 more than D (of 6 each).
**FAIL:** C-B <2 OR C-D <2 OR B/D outperform C.
**INCONCLUSIVE:** Mixed, cannot complete, or contamination.

**Stop conditions (unchanged):**
- A=B=C=D within 1 after 12 problems → stop.
- Irreproducible → stop.
- Exceeds $0 → stop.

## Integrity

- v1 and v2 preserved unchanged (preregistrations, failures, seeds 42/43).
- v1 A_00/A_01 observations EXCLUDED from efficacy estimates.
- Evaluator in `evaluator/` (v3 ground truths).
- No model trials under v3 yet. Awaiting review.
- No Gateway changes. No paid APIs. No merges. No new repo.

## Deliverables

1. v1, v2, v3 preregistrations (frozen).
2. v3 apparatus: generate_v3.py, validate_v3.py, test_apparatus_regression.py.
3. validation_report_v3.json (36/36 + matrix).
4. [Future] Phase 1 attempts, results, verdict.

---

**Frozen by:** Muse
**Date:** 2026-10-11
**Source revision:** openline-airlock d4c81e68d3ca
**Apparatus verdict:** PASS (all v3 checks green)
**Note:** No AI problem-solving runs under v3. Awaiting Phase 1 authorization.
