# ECON-002 — Minimum Successor Falsifier — PREREGISTRATION

**Study identity:** ECON-002 / `econ002_c72e6357` (distinct from ECON-001; no
ECON-001 artifact is modified, relaunched, or extended by this study.)

**Status:** FROZEN. No paid contact has occurred under this study ID.
No paid calls until the operator explicitly authorizes the frozen study.

**Repo:** branch `study/econ-002`, base commit `43f8436` (branch
`run/econ-001-r3`); `origin/main` = `f7b1822`. Frozen in commit
(see §12).

## 1. Experiment question

"Can any frozen candidate-generation strategy produce one successor method
that is at least 20% cheaper than the baseline while preserving 12/12
verified success on fresh paired tasks?"

## 2. Baseline

`prompts.BASE_METHOD` from frozen econ-001 code (SHA-256
`73dac1b8fd4d0bcdabc34faddb3063a3033c3b5ebb5e037059de8663e20b13ca`),
223 tokens.

## 3. Stage 1 — deterministic compression candidates (frozen order)

Tested sequentially in this exact order. Never reordered on results.
Each candidate is rendered offline with frozen `apply_delta`; the runner
re-verifies the rendered SHA-256 immediately before promotion, and the
candidate is immutable after another candidate's result is observed.

Directive numbering (explicitly verified): `apply_delta` numbers the
preamble line ("You fix one small Python module. Follow this procedure
exactly.") as block 1; visible numbered step k is block k+1. Directives
below are written in this numbering. Steps are renumbered 1..n after
application.

### D1 — delete visible CHECK
Delta: `REMOVE_STEP 6` → 192 tokens, SHA-256
`61f45a8fa4814d07f9cb933500fe4743014abd8f0fca81ef528a711fc75466c2`.

Rationale (bounded): "CHECK is a plausible removable source of additional
computation. Whether removing it preserves verified success and materially
reduces cost is exactly what the receiver test determines."

### D2 — delete visible REPRODUCE
Delta: `REMOVE_STEP 3` → 188 tokens, SHA-256
`723efcecfcd4064172edce2b0fd8572dcea3b094ecb4064889d45d64bf0eb984`.
Disclosed imperfection: CHECK's
"edge case from step 2" reference now dangles at renumbered DIAGNOSE;
the receiver judges the rendered method as-is.

### D3 — merge visible REPRODUCE + DIAGNOSE
Delta (exact, already reviewed):
```
REPLACE_STEP 3: REPRODUCE AND DIAGNOSE. Write down the smallest input that exposes the defect, then name the single root cause: one wrong expression, one missing case, one wrong boundary. If you cannot name it, say so and make the most conservative change consistent with the statement.
REMOVE_STEP 4
```
→ 200 tokens, SHA-256
`ff6209fb728dd6d615ab1b2cd0dbd2c02e9e0396a756b428acb44747deab3d98`.

### D4 — wording compression
Delta: the exact six already-reviewed REPLACE_STEP directives (see
CANDIDATES.json `candidates.D4.delta_text`). Not rewritten, tuned, or
improved during preregistration. → 180 tokens, SHA-256
`8a42dc1014231daf61267cdcbc593ca3072852145fe07b147d2cdfa077300737`.

Full rendered bytes for D1–D4: CANDIDATES.json (`rendered_method`,
`rendered_sha256`, `rendered_tokens`).

## 4. Receiver rule (identical for every candidate, both stages)

- Same 12 fresh task IDs for parent and candidate (paired design).
- Exactly one parent attempt and one candidate attempt per task.
- Candidate must achieve 12/12 verified success.
- Parent must achieve 12/12 verified success.
- Zero per-task candidate success regressions.
- Candidate settled total cost ≤ 80% of parent settled total cost
  (IEEE-754 double comparison, no epsilon).
- Unsettled calls contribute their full reservation to the total
  (fail-closed: an unresolved call cannot help a candidate pass).
- Candidate source never judges its own result; receiver-side local
  hidden tests remain authoritative.

Stop immediately at first accepted candidate. If all four deterministic
candidates are rejected, Stage 2 is earned.

## 5. Stage 2 — corrected-objective proposer (earned only)

At most two model-proposed candidates. Objective, verbatim:

"Produce one method change whose goal is lower measured execution cost
while preserving equal-or-better verified success. You may delete, merge,
shorten, simplify, or remove method steps. Added procedure is a regression
unless it improves verified output enough to justify its cost."

The proposer additionally receives: baseline success observations,
baseline measured cost observations, the actual receiver acceptance
criterion (§4), the verified directive-numbering note, and the delta
format. It must NOT receive promotion outcomes from earlier candidates.
Each Stage-2 candidate is judged by the exact same paired-12 / 20%
receiver rule. Stop at first acceptance or after two rejected proposals.

## 6. Fresh tasks

- Corpus: `study/econ-002/corpus/corpus.json`, SHA-256
  `df932a0987f99a8e4f04e304a357a16504092c1e636a27f62cc15a81bdaf9754`.
- Declared seeds: 20260918, 20260919, 20260920 (deterministic
  `build_corpus` from frozen econ-001 code).
- Content-disjointness: every frozen eval task's `target_code` is
  byte-distinct from all eval instances in all three econ-001 corpora
  (242 unique old instances; 0 overlap) — no task instance previously
  exposed in ECON-001 scientific runs can appear.
- Integrity: 78/78 frozen tasks verified reference-passes / buggy-fails
  before the freeze.
- Allocation: `study/econ-002/TASK_ALLOCATION.json` — exactly the 78
  worst-case tasks, each used exactly once (Stage 1: 4×12 promotion;
  Stage 2: 2×(3 discovery + 12 promotion)). Frozen before contact.
- No task swapping after results are observed. No difficulty tuning
  after corpus generation.
- Saturated regime kept: the corpus_r3 generator produced 36/36
  baseline success; with success saturated, compression is the only
  available axis, which is exactly the axis under test. Introducing
  harder tasks would answer a different question and stays a separate
  experiment.

## 7. Empirical-null calibration (exact wording)

"The paired-12 / 20% rule produced 1 acceptance in 30,000 empirical null
resamples drawn from preserved identical-method observations."

This is empirical calibration from the preserved corpus_r3
identical-method data (2026-09-16), not a population probability or
general statistical guarantee. Transfer of the calibration to the fresh
corpus_r4 regime is an assumption, not a proof. The 20% margin, not the
resample count, is what carries the rule's selectivity: the worst
observed null saving at n=12 was 21.57%.

## 8. Budget (separate from ECON-001 and development accounting)

- Maximum physical budget: **$20.00** (new study budget line).
- Reservation ceiling per paid call: $0.11 (frozen CONFIG.json
  envelopes: solving and proposal).
- Worst-case call inventory (frozen code, mechanically verified):
  Stage 1: 4 × 24 = 96; Stage 2: 2 × 28 = 56; **total maximum 152
  paid scientific calls**; plus exactly 1 non-scientific preflight call
  (§13) = **153 total maximum paid calls**.
- Worst-case reservation: 152 × $0.11 = $16.72 scientific; preflight
  1 × $0.11 = $0.11; combined **$16.83 ≤ $20.00**.
- Verified by `scripts/succ_run.py` offline mode against frozen
  CONFIG.json before the freeze. If the enforced worst-case bound
  exceeded $20, the study would STOP before contact; it does not.

## 9. Execution / failure rules (frozen before contact)

- Malformed candidate output = charged rejection, no replacement.
- Any runner crash = preserve run and stop, no repair-and-continue.
- Pre-dispatch infrastructure failure = stop, zero new invocations
  (`InfrastructureHalt` propagates; fail-fast).
- Dispatched but unsettled call = reservation retained until reconciled.
- No candidate replacement. No task replacement. No threshold movement.
- No post-contact prompt changes.
- No code repair and relaunch under the same study ID.
- No second chance for a rejected candidate.
- STOP file checked before every paid invocation
  (`worker.invoke` pre-reservation gate).
- If infrastructure fails after contact, the partial study is preserved
  as incomplete. It is not rescued.
- Paid execution requires the explicit `--authorize-paid-contact` flag;
  the default mode performs offline validation only and constructs no
  provider.

## 10. Maximum claims

Positive (if authorized and run, at most):

"Strategy X produced a method the receiver accepted as at least 20%
cheaper than the paired baseline while preserving 12/12 verified success
on the frozen fresh-task evaluation."

Negative (frozen; failure establishes only this):

"None of the frozen candidate-generation strategies produced a successor
at least 20% cheaper than the paired baseline while preserving 12/12
verified success on the frozen fresh-task evaluation."

The 20% margin means failure does NOT establish that no cheaper
successor exists. This negative claim is not broadened to: no cheaper
successor exists; compression does not work; recursive improvement
fails; the baseline is globally cost-minimal. No recursive-improvement
claim. No compounding claim. No cross-model claim. No cross-distribution
claim. No statement that smaller improvements do not exist.

## 11. Implementation bound (amended by A2; descriptive facts updated)

Original bound language (from the work order, frozen at A0): "Target
approximately <=100 new runtime/controller LOC." This was an
approximate implementation target intended to keep the runner small and
prevent a new subsystem — not a hard scientific stop condition. The
word "approximately" is in the frozen language.

Amended facts:
- Reuses frozen econ-001 primitives only: `attempt()`, `evaluate()`
  (via `attempt`), ledger, worker, `apply_delta()`, corpus builder,
  envelope loader, discovery feedback format.
- New code: `scripts/succ_run.py` — 133 statements. The increase over
  the original ~100-statement target comes from the separately-accounted
  provider preflight added in Amendment A1. The runner remains one
  small script reusing frozen ECON primitives, with no new subsystem,
  no new provider integration, and no new gate architecture.
- Offline test results (2026-09-16, zero provider contact): 15/15
  ECON-002 tests pass — the 10 original gate/rendering/freeze tests
  plus 5 preflight tests (success path, timeout, missing usage, frozen
  spec, stop-file blocks contact).
- Existing econ-001 offline suites remain green and untouched:
  19/19, 15/15, 25/25 (no file in `study/econ-001/` was modified).

## 12. Freeze record

- Preregistration: this file.
- Corpus: `corpus/corpus.json` (SHA-256 §6).
- Candidates: `CANDIDATES.json` (rendered bytes + SHA-256 + tokens).
- Allocation: `TASK_ALLOCATION.json`.
- Runner: `scripts/succ_run.py`; tests: `tests/test_succ_offline.py`.
- Proof of no paid scientific contact: `runs/econ002_c72e6357/`
  does not exist; no ledger, no raw responses, no reservations under
  this study ID. The runner's default mode cannot construct a provider.

## 13. Amendment A1 — remote verifiability + provider preflight (pre-contact)

Added before any paid contact. Nothing in the scientific design in
§§1–12 changed. §8 budget/call figures and §11 descriptive
implementation/test counts are superseded by Amendment A1/A2.

**Remote verifiability.** The frozen study must be pushed to GitHub
before paid contact. Paid contact is not authorized from a local-only
freeze. Remote: branch `study/econ-002`, head
`f4f5276a9ea3f76621ac2cb8472d2d517e8093ba`, tree verified byte-for-byte
against the local freeze for all ECON-002 artifacts.

**Non-scientific provider preflight.** Before first scientific contact,
the runner issues exactly one provider request whose only purpose is to
verify the current paid execution path. It checks: exactly one request
is issued (counted; no retry, fallback, fanout, or second request);
provider usage metadata is present; actual usage prices under the frozen
pricing table (`worker.settle_cost`); the $0.11 reservation covers the
observed call (also enforced inside `invoke` via OverrunAbort);
pre-dispatch failure (`InfrastructureHalt`) remains distinguishable
from dispatched-but-unsettled exposure (`unresolved`, reservation
retained). This preflight is NOT a scientific task: it uses no
ECON-002 promotion/discovery task, does not touch the method, and is
never used to infer model quality, tune thresholds/prompts/corpus/
candidate order/task allocation, or establish long-run infrastructure
reliability.

Frozen preflight specification:
- instructions: `Reply with exactly this word and nothing else: ok`
- input: `ping`
- caps: max_input_tokens 512, max_output_tokens 16
- reservation: $0.11 (envelope `preflight`)
- timeout: 60 s; one-call-only semantics enforced by construction
- failure handling: timeout → `unresolved` (dispatched, reservation
  retained) → STOP; HTTP non-200 / missing usage → `unresolved` → STOP;
  transport failure before dispatch or credential-service failure →
  `InfrastructureHalt` → STOP; operator STOP file → zero requests → STOP
- accounting: separate ledger `runs/<study>/preflight_ledger.jsonl`
  (envelope `preflight`); outcome recorded in `study.json` under
  `preflight`, never in the scientific results; the scientific ledger is
  created only after the preflight passes

If the preflight fails, the study stops before scientific contact and
`study.json` records the preflight failure with an empty results array.

**Revised physical budget (mechanical, from frozen code).**
- Maximum scientific calls: 152 × $0.11 = $16.72
- Preflight calls: 1 × $0.11 = $0.11
- Total maximum paid calls: 153
- Worst-case total retained reservation: **$16.83 ≤ $20.00 physical ceiling**
