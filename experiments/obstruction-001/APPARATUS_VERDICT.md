# OBSTRUCTION-001 Apparatus Verdict

**Date:** 2026-10-11
**Verdict:** APPARATUS PASS

## Evidence

### 1. Fixture Validation: 36/36 PASS

`validate_v2.py` independently checked every fixture:
- ✅ Correct program passes all hidden tests (36/36)
- ✅ Buggy program is syntactically valid (36/36)
- ✅ Buggy program fails at least one hidden test (36/36)
- ✅ Defect location recorded and present in buggy code (36/36)

Report: `validation_report_v2.json` (36 fixtures with defect locations, test results)

### 2. Injector Repair

**v1 flaw:** 12/36 fixtures had no-op bugs (fallback paths in WRONG_OP, SWAPPED_ARGS, OFF_BY_ONE injectors).

**v2 fix:** Template-specific injectors with guaranteed manifestation.
- Each (template, bug_type) pair has a dedicated injector function.
- No fallback paths. No no-ops.
- Example: `sr_off_by_one` for sum_range always produces `range(1, n)` which always fails the `n` test case.

### 3. Obstruction Quality

`OBSTRUCTION_QUALITY.md` demonstrates:
- ✅ Obstructions accurately identify the obstacle (grounded in bug type + defect location).
- ✅ Obstructions explain *why* the attempted fix fails (not just *that* it fails).
- ✅ Obstructions do NOT reveal complete solutions (no code snippets, no line numbers).

Example: For OFF_BY_ONE in find_max, the obstruction explains "the loop never examines index 1" without saying "change lst[2:] to lst[1:]".

### 4. Versioned Preregistration

`PREREGISTRATION_V2.md` (frozen):
- Fresh seed: 43 (v1 seed 42 preserved in history).
- Preserves v1 hypothesis, 4 conditions, 3-attempt budget, 6+6+6+6+12 problems.
- Preserves PASS/FAIL/INCONCLUSIVE criteria and stop conditions.
- Explicitly documents v1→v2 changes (generator fix, seed change).
- Excludes v1 A_00/A_01 observations from efficacy estimates.
- No model trials have occurred under v2.

### 5. Preserved Artifacts (unchanged)

- `PREREGISTRATION.md` v1 (frozen, INCONCLUSIVE)
- `FAILURE_ANALYSIS.md` v1 (documents generator flaw)
- `problems.json`, `ground_truth.json` v1 (seed 42, 8/24 invalid)
- `solver/attempt_A_00_1.py`, `solver/attempt_A_01_1.py` (v1 attempts)

## What was NOT done (per authorization)

- ❌ No new AI problem-solving runs (awaiting review)
- ❌ No changes to v1 preregistration, runs, or INCONCLUSIVE result
- ❌ No paid APIs ($0)
- ❌ No Gateway changes
- ❌ No merges
- ❌ No new repository (used existing openline-airlock)

## Ready for Review

The apparatus is validated and frozen. Awaiting authorization to begin Phase 1 (24 problems, 4 conditions) under PREREGISTRATION_V2.md.

**Files for review:**
- `PREREGISTRATION_V2.md` (frozen protocol)
- `validation_report_v2.json` (36/36 evidence)
- `OBSTRUCTION_QUALITY.md` (obstruction verification)
- `generate_v2.py`, `validate_v2.py` (apparatus code)
