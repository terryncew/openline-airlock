# ECON-001-R3 — run freeze manifest

Distinct run ID: **ECON-001-R3** (directory `runs/study-003/`).
Launches study-001/launch-1 (aborted) and study-001/launch-2 (interrupted)
remain unchanged on branch `study/econ-001` and are EXCLUDED from
confirmatory results. ECON-001-R2 (runs/study-002/, branch
`run/econ-001-r2`) was declared infrastructure-incomplete on 2026-09-16
(see `RECONCILIATION.md`, `RUN_STATUS.md`) and is EXCLUDED from
confirmatory results. This run is the single confirmatory execution.

## Authorization (step 4 of the 2026-09-16 repair order)

- Study allocation: **$50.00**. Prior encumbrance, launches 1/2:
  $1.1197 (settled $1.0097 + retained $0.11).
- ECON-001-R2 reconciled: settled $1.4642 + retained ambiguous $0.11 =
  $1.5742. The 301 proven-not-dispatched reservations ($33.11) were
  released per the reconciliation and no longer encumber.
- Total encumbered before this run: $1.1197 + $1.5742 = **$2.6939**.
- Remaining: $50.00 − $2.6939 = **$47.3061**. Run budget set to
  **$47.30** (truncated, conservative).
- Conservative maximum exposure of this run (all 388 reservations
  retained): **$42.58** ≤ $47.30. Margin: **$4.72**.
- No funding shortfall; the allocation is not expanded. Development
  exposure ($5.61 retained) is tracked separately and unaffected.

## Frozen elements

- **Code**: branch `run/econ-001-r3`, this freeze commit. Behavior code
  identical to `25103c8` (the fail-fast repair, proven offline 19/19 +
  25/25 + 15/15, zero spend); this commit adds only the R3 corpus, the
  corpus-generation script, and this manifest — no behavior change.
- **Protocol**: `PROTOCOL.md` as in `25103c8`, including section 14
  (restart, stop, and amendment behavior) and the new **infrastructure
  halt** rule: a demonstrably pre-dispatch failure — credential-service
  error before dispatch, or a refused/unreachable/DNS-failed connect —
  records the failed call as unresolved and halts the study with status
  `halted_infrastructure`; no further invocations. Timeouts, HTTP error
  statuses, and malformed output keep the frozen
  record-unresolved-and-continue behavior. No amendments after this
  freeze.
- **Stop control**: `runs/study-003/STOP` is checked at the top of
  `invoke()`, before reservation and before provider contact — proven
  offline to block every subsequent paid invocation.
- **Model/prices**: `gpt-5.6-sol`, `POST https://api.openai.com/v1/responses`,
  reasoning effort `medium`, `max_output_tokens` envelopes
  (solving 7,000/2,000; proposal 5,000/3,000; preflight 128/100).
  Pricing re-verified 2026-09-16 against developers.openai.com:
  $4.00 input / $0.40 cached / $5.00 cache-write / $20.00 output per 1M;
  promotional pricing through 2026-11-21. tiktoken 0.14.0 `o200k_base`.
  Envelopes: solving $0.11, proposal $0.11, preflight $0.01.
- **Complete method cap**: 1,500 tokens on the complete rendered inherited
  method, including all retained instructions and deltas
  (`prompts.METHOD_TOKEN_CAP`; enforced in `apply_delta` — over-cap
  renders reject as `rendered_method_over_cap`, never truncate).
- **Task schedule**: 3 repetitions x 54 eval tasks (36 measurement as
  12 task-groups x 3 arms A/B/C, IDs matched across arms within a rep;
  18 acquisition: G1 common 10 invocations, G2 arm-C 10 invocations) +
  4 calibration calls = **388 invocations**, ceiling **$42.58**.
  Reps use disjoint ID ranges (sorted task order, fixed rep slices).
- **Outcome rules**: acquisition acceptance requires STRICT improvement —
  candidate strictly better on verified output or cost, worse on neither;
  equal-equal rejects. Ordinary malformed model output is a charged
  rejection (`delta_malformed` / `delta_extraction_failed`), never a crash.
  Equal-cost hurdles are descriptive context, not verdict criteria:
  B/A repays iff V_B/V_A > 23/18; pooled C/B iff V_C/V_B > 28/23.
- **Evaluation instances**: `corpus/corpus_r3.json`, generated from the
  FROZEN generator (`src/econ/corpus.py`, unchanged) with master seed
  **20260917** — arbitrary, date-based, declared before generation; no
  outcome-based selection, no tuning against prior outcomes.
  Same family mix and difficulty: 162 eval (54 logic / 54 interface /
  54 config), 3 calib (1 per family), 3 bugs/task, same bug classes.
  Task IDs prefixed `r3-` (distinct from all prior IDs).
  Previously-exposed exclusion: content-hashes of every task in
  `corpus/corpus.json` (all pools, launches 1/2) and
  `corpus/corpus_r2.json` (all pools, R2) — 327 prior contents; 64 eval
  + 2 calib draws colliding with the exclusion set were regenerated
  with deterministic sub-seeds (`20260917:regen:<pool>:<i>:<k>`) until
  disjoint, with within-run dedup. Final corpus is disjoint from every
  previously generated instance.
  Verified before freeze: 165/165 reference-passes/buggy-fails on hidden
  tests (local), all 165 packets build within the 3,000-token cap.
  Pool hashes: eval `5b091dd2dd3ddf6f78ce5cd6cb72ca406fd4f612bbf463c151711032578c54e6`,
  calib `d670d0f74377d561bec64610ff2e19d1bd83d33464b3434d480bee4f8ac14899`.
  File SHA-256: `64b448a2be420ea8d89d0816b68bdb255f8a80cf4462cea89d183284aafa0899`.
  Generation script: `runs/study-003/gen_corpus_r3.py` (zero network,
  zero spend).

## Launch

- Command: `ECON_RUN_NAME=study-003 ECON_CORPUS=corpus/corpus_r3.json
  ECON_BUDGET=47.30 python scripts/study_run.py` from
  `study/econ-001/`. Single launch ("run once"); no automatic retries,
  no relaunches. Operator stop via the STOP file remains available.
- Launch record (`study.json`, ledger, console) lands in
  `runs/study-003/`.
