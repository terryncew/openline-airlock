# OBSTRUCTION-001: Independent Review Finding (v3)

**Date:** 2026-10-11
**Reviewer:** Independent (via Terrynce)
**Target:** Commit fe6d3a2 (v3 apparatus, APPARATUS PASS)
**Status:** PHASE 1 BLOCKED / NO MODEL TRIALS

## Defects Found

### 1. Duplicate buggy programs across conditions (CRITICAL)

**Finding:** Only 12 of the 24 main buggy programs are distinct.

**Evidence:**
```
Main: 24 problems, 12 distinct buggy programs
Duplicates: 12 (50%)
```

**Root cause:** The v3 generator uses deterministic injectors. With 5 templates
× 4 injectors per template = 20 unique (template, bug_type) combinations,
generating 24 problems guarantees duplicates. The same combination always
produces identical buggy code.

**Impact:** Cross-condition contamination. If Condition A and Condition C
both contain the identical buggy program, the solver's performance on the
second encounter is confounded by memory of the first. The conditions cannot
be meaningfully compared.

**Preregistration violation:** v3 specifies "unfamiliar instances" and
"different problem sets per condition, matched for difficulty." Duplicate
programs violate the unfamiliarity requirement.

### 2. Holdout contamination (CRITICAL)

**Finding:** 9 of 12 holdout programs exactly duplicate a main program.

**Evidence:**
```
Holdout: 12 problems, 9 duplicate a main program (75%)
```

**Root cause:** Same as above — deterministic injectors with insufficient
unique combinations for 36 total problems.

**Impact:** Invalidates the transfer comparison. The holdout is supposed to
test whether obstruction-derived insight transfers to *new* problems. If
9/12 holdouts are identical to main problems, it's a memory test, not a
transfer test.

**Preregistration violation:** v3 specifies "separate holdout set" for
"performance on held-out problems." Duplicates violate separation.

### 3. Evaluator defaults to v1 ground truth (HIGH)

**Finding:** `evaluate.py` defaults to `evaluator/ground_truth.json` (v1,
seed 42) instead of v3.

**Evidence:**
```python
# evaluate.py line 22:
def evaluate(..., truth_file: str = "evaluator/ground_truth.json") -> dict:

# evaluate.py line 96:
truth_file = "evaluator/ground_truth.json"  # v1, not v3
```

**Impact:** If the evaluator is run without explicit truth_file argument,
it scores against v1 problems (different seed, different bugs). Results
would be meaningless.

**Note:** The v3 validator (`validate_v3.py`) correctly uses v3 files.
Only the standalone `evaluate.py` has this defect.

## Why v3 validation missed these

The v3 validator (`validate_v3.py`) checked:
- ✅ 36/36 fixtures valid (correct passes, buggy fails)
- ✅ 6 per condition, all 6 bug types each
- ✅ 12 holdout, 2 per bug type
- ✅ Unique fixture IDs

It did NOT check:
- ❌ Distinctness of buggy programs across conditions
- ❌ Holdout vs main program overlap
- ❌ Evaluator default file version

The "unique fixture IDs" check verified IDs like A_00, A_01 are distinct,
but did not verify the *content* (buggy_code) is distinct.

## Verdict

**PHASE 1 BLOCKED.** The v3 apparatus cannot support the preregistered
experiment:
- Cross-condition duplicates invalidate the A/B/C/D comparison.
- Holdout duplicates invalidate the transfer test.
- The evaluator defect risks scoring against wrong ground truth.

## Preserved (unchanged)

- v1: PREREGISTRATION.md, seed 42, INCONCLUSIVE (generator no-op flaw)
- v2: PREREGISTRATION_V2.md, seed 43, APPARATUS PASS (but Phase 1 blocked for imbalance)
- v3: PREREGISTRATION_V3.md, seed 44, APPARATUS PASS (but Phase 1 blocked for duplicates)
- All at commit fe6d3a2, branch experiment/obstruction-001-v3

## Recommendation

**STOP OBSTRUCTION-001.** Do not generate v4 without a new owner decision.

The fundamental issue is insufficient unique (template, bug) combinations
for 36 problems. Options for a redesign (if authorized):
1. More templates (need ≥36 unique combos for 36 problems)
2. Parameterized injectors (same bug type, different manifestations)
3. Smaller experiment (fewer problems, accept reduced power)

But per the owner's order: **NO v4, NO more experiments without a new decision.**

---

**Documented by:** Muse
**Date:** 2026-10-11
**Status:** OBSTRUCTION-001 STOPPED. Phase 1 BLOCKED / NO MODEL TRIALS.
