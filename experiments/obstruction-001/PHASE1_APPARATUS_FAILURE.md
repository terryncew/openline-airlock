# OBSTRUCTION-001 Phase 1: Apparatus Failure Report

**Date:** 2026-10-11
**Status:** STOPPED — Condition balance failure.

## What happened

Phase 1 was authorized to run 4 conditions with 6 problems each (24 total),
per PREREGISTRATION_V2.md.

**Actual distribution from generator (seed 43):**
- Condition A: 9 problems
- Condition B: 7 problems
- Condition C: 4 problems
- Condition D: 4 problems

**Bug type coverage:**
- A: MISSING_BASE(1), MISSING_RETURN(2), OFF_BY_ONE(2), WRONG_OP(2), WRONG_VAR(2) — missing SWAPPED_ARGS
- B: MISSING_BASE(1), MISSING_RETURN(2), OFF_BY_ONE(1), WRONG_OP(1), WRONG_VAR(2) — missing SWAPPED_ARGS
- C: MISSING_RETURN(1), OFF_BY_ONE(1), WRONG_OP(1), WRONG_VAR(1) — missing MISSING_BASE, SWAPPED_ARGS
- D: MISSING_RETURN(1), OFF_BY_ONE(1), WRONG_OP(1), WRONG_VAR(1) — missing MISSING_BASE, SWAPPED_ARGS

## Why this matters

The preregistration specifies:
- "6 problems per condition, balanced bug types"
- PASS criteria: "C solves ≥2 more than B AND ≥2 more than D (of 6 each)"

With C=4 and D=4, the PASS criteria cannot be applied as written.
The comparison would be underpowered and unbalanced.

The v2 validator checked fixture validity (36/36 pass) but did NOT
check condition balance. This is an apparatus design flaw.

## What was NOT done

- No problems were attempted under Phase 1.
- No conditions were run.
- The v2 apparatus (fixtures) remains valid for 36/36.
- The v2 preregistration remains frozen.

## Options

1. **Fix generator balancing** (requires v3 preregistration, new seed):
   Ensure 6 per condition with balanced bug types. Re-validate 36/36.
   
2. **Amend preregistration** (requires explicit order):
   Change to "4-9 problems per condition" and adjust PASS criteria
   proportionally (e.g., C rate > B rate by ≥33%). This weakens the design.

3. **Stop** (current):
   Report the failure, do not run Phase 1.

## Recommendation

Option 1: Fix the generator to enforce 6-per-condition balance, then
re-freeze as v3. The fixture validity logic is sound; only the
allocation needs repair.

---

**Reported by:** Muse
**Awaiting:** Terrynce's decision on how to proceed.
