# ECON-001-R2 — run freeze manifest

Distinct run ID: **ECON-001-R2** (directory `runs/study-002/`).
Launches study-001/launch-1 (aborted) and study-001/launch-2 (interrupted)
remain unchanged on branch `study/econ-001` and are EXCLUDED from
confirmatory results. This run is the single confirmatory execution.

## Frozen elements

- **Code**: branch `run/econ-001-r2`, content commit `c877a33beed85fb703a0731ff5bca4d8b8caee6f`
  (= repaired commit `b8c9fac` + env-override launcher for run identity,
  no behavior change). Offline checks on the repaired commit: 19/19 +
  25/25, zero spend. STOP control: `runs/study-002/STOP` is checked at the
  top of `invoke()`, before reservation and before provider contact —
  proven offline to block every subsequent paid invocation.
- **Protocol**: `PROTOCOL.md` as in `b8c9fac`, including section 14
  (exact restart, stop, and amendment behavior) and the 36-measurement-task
  design. No amendments after this freeze.
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
- **Evaluation instances**: `corpus/corpus_r2.json`, generated from the
  FROZEN generator (`src/econ/corpus.py`, unchanged) with master seed
  **20260916** — arbitrary, date-based, declared before generation; no
  outcome-based selection, no tuning against prior outcomes.
  Same family mix and difficulty: 162 eval (54 logic / 54 interface /
  54 config), 3 calib (1 per family), 3 bugs/task, same bug classes.
  Task IDs prefixed `r2-` (distinct from all prior IDs).
  Previously-exposed exclusion: 22 eval + 3 calib task contents were shown
  to the model in launches 1/2; 16 newly drawn tasks colliding with those
  contents were regenerated with deterministic sub-seeds
  (`20260916:regen:<pool>:<i>:<k>`) until disjoint. Final corpus is
  disjoint from every previously exposed instance.
  Verified before freeze: 165/165 reference-passes/buggy-fails on hidden
  tests (local), all 165 packets build within the 3,000-token cap.
  Pool hashes: eval `dfda5bcd54056e494ac4f6c1abcfc4026c35454fe6f0fa32cbf8055ab4916aa2`,
  calib `962b78f0892c89c3c6907575223f915f03af3217a61479ffb4116aa8529f65693`.
  File SHA-256: `124c13c8d4371932df78aa3db021f47a0ef5630095e945d98e36fa7d08a64902`.

## Budget

- Study allocation $50 INCLUDES the prior $1.119656 encumbered
  (study-001: settled $1.009656 + unresolved $0.11). This run's ledger
  ceiling: **$48.88**. Worst-case new-run exposure (all 388 reservations
  retained): $42.58. Portfolio worst case: $43.70 <= $50.
- The $5.61 unresolved development exposure is tracked SEPARATELY
  (study/econ-001 `runs/DEV_RECORD.md`); billing records were
  inaccessible (API 403), remote execution/billing unresolved — no claim
  of nonexistence, no claim of permanent unknowability.
- Calibration (4 calls, required by the frozen protocol) counts toward
  the $48.88. Provider credit headroom: $104.98 - $2.7589 settled.

## Execution rules

- Run ONCE. If an unexpected crash occurs: preserve the run as-is;
  no repair, no relaunch, no amendment.
- STOP file may be created at any time to halt before the next paid call.
- Raw provider responses persist to `runs/study-002/raw/` before parsing;
  exposure is reported as settled + unresolved-retained + in-flight-open.
