# ECON-001 Protocol (frozen)

**Status:** DRAFT — frozen after development (dev-001) completes.
**Study:** economics of method improvement under a fixed-request worker.
**Authorization:** Terrynce White, 2026-09-16. Build-and-run authorized;
no further routine approval round. Escalation only for genuine blockers
outside the authorization.

## 1. Objective

Measure whether the cost of acquiring a method improvement (discovery +
proposal + promotion) is repaid by per-task savings within an observed
horizon, using a fixed-request API worker applied equally to all arms.

## 2. Claim boundary

This study does NOT establish recursive productivity advantage, RSI,
AGI, superintelligence, or continuous self-improvement. It does not
reopen, rescue, or reinterpret COMPOUND-001 (closed), RSI-006 (closed),
or PR #170 (closed unmerged). Failures remain failures.

## 3. Verified configuration

`CONFIG.json` (frozen 2026-09-16, verified against authoritative docs,
not earlier tables): endpoint `POST /v1/responses`, model
`gpt-5.6-sol`, output cap `max_output_tokens` (caps visible + reasoning
tokens together), reasoning effort `medium` (pinned), temperature 0.2
(pinned), `store:false`, non-streaming, no tools, tokenizer
`o200k_base` via `tiktoken.encoding_for_model`, pricing
$4.00/$0.40/$5.00/$20.00 per 1M (input/cached/cache-write/output).

## 4. Request envelopes (all values in CONFIG.json)

- **solving:** input ≤5,000, `max_output_tokens`=3,000, reservation $0.11
- **proposal:** input ≤7,000, `max_output_tokens`=2,000, reservation $0.11
  (extracted delta must itself be ≤1,500 tokens or the proposal is rejected)
- **preflight:** input ≤128, `max_output_tokens`=100, reservation $0.01

Structural input bound (no tokenizer margin): task packets capped at
3,000 tokens at generation (rejected, never truncated); method text
capped at 1,500 tokens rendered complete (all retained instructions +
deltas; `apply_delta` raises rather than truncates); discovery feedback
capped at 1,500 tokens per discovery task (explicit truncation order,
verdict never truncated). Reservation uses fail-closed additive
cache-write reading.

Billable paths per invocation: exactly one request. No SDK (urllib;
no retry layer exists). `max_retries=0` by construction. Timeouts,
transport failures, HTTP errors, and missing usage objects are
**unresolved exposure**: the reservation is retained, never treated as
a free failure. Actual > reservation aborts the study (fail closed).

## 5. Corpus

Seeded generator (`src/econ/corpus.py`), three families
(logic/interface/config), nine templates. Every task ships its bug and
its reference fix. Integrity rule (offline, no paid calls): the
reference must PASS hidden tests and the buggy version must FAIL them;
violations reject the corpus.

Pools (disjoint by construction, separate RNG streams):
- **dev** (48): difficulty validation only. Paid.
- **eval** (162): held out. Never executed before the study run.
- **calib** (3): calibration only.

Freeze hashes: dev `9f6b267a…`, eval `229179c7…`, calib `afca028d…`
(full hashes in `corpus/corpus.json`; regenerated if the generator
changes during development, then re-verified).

Task packet ≤3,000 tokens, enforced at build. Single target file
(`target.py`); worker outputs the complete corrected file in one
```python fenced block; anything else is extraction failure.

## 6. Worker and evaluation

`src/econ/worker.py`: reservation before contact; pre-contact refusal
on envelope breach or insufficient budget (no request sent); settlement
from the response usage object; receipts per invocation.

`src/econ/evaluate.py`: temp dir, subprocess, wall-clock timeout, no
network. Accident containment only — no hostile-worker containment is
claimed. Verdict 0/1 on hidden tests.

## 7. Acquisition

Per acquisition: 3 discovery attempts (parent method) → 1 proposal call
→ render + 1,500-token cap check → 3 promotion attempts parent +
3 promotion attempts candidate (disjoint tasks). Acceptance requires
**strict improvement**: candidate strictly better on verified output or
cost, worse on neither. Equal-equal rejects.

- G1 (common method, all arms inherit): 10 invocations
- G2 (arm C only): 10 invocations

## 8. Schedule (36-measurement-task design)

Per repetition (128 invocations): G1 acquisition + 12 tasks × 3 arms
(G1), G2 acquisition (C) + 12 × 3 (G2), 12 × 3 (G3, no acquisition).
Measurement task IDs matched across A/B/C within a rep; reps use
disjoint ID ranges. Three reps = 384 + 4 calibration = **388
invocations**, ceiling **$42.58** under the $50 study budget.

Equal-cost hurdles (descriptive context, not verdict criteria):
B/A repays iff V_B/V_A > 23/18; pooled C/B iff V_C/V_B > 28/23.

## 9. Calibration (4 paid calls, inside the $50)

1 preflight (telemetry; asserts provider usage present and local token
count tracks provider count within 2%, else abort) + 3 family tasks
(baseline method). Sets operational timeout, observes c_max, records
strategy threshold T=$8.00. Changes nothing about tasks, generator,
method, or verdict rules.

## 10. Economic calculations (separate; not interchangeable)

1. **Descriptive unit-cost advantage:** pooled $/verified per arm over
   completed reps, with output preservation stated. Says nothing about debt.
2. **Observed acquisition payback:** COST-FORM inequality D1 + C_B ≤ C_A
   with V_B ≥ V_A (pooled), plus per-rep breakdown. Earned iff pooled
   holds AND ≥2 completed reps hold per-rep. Success-rate ratios alone
   never establish this.
3. **Projected future payback:** rep-level per-task savings → median k*
   with CI extending to +∞ whenever any completed rep shows
   non-positive savings. A projection, never an observed verdict.

Aborted reps and unresolved exposure are reported alongside
completed-run economics, never folded into them.

## 11. Budgets and spend control

- Development: ≤$5, separate ledger (`runs/dev-001/`), dev tasks only.
- Study: ≤$50 including calibration, separate ledger (`runs/study-001/`).
- No top-ups, no auto-reload changes. Billing endpoints are not
  readable with the API key (403); enforcement is local via the ledger.
- Missing-usage calls retain reservations as unresolved exposure.

## 12. Development record

### dev-001 (2026-09-16) — temperature incident
48 dev tasks, 45 unresolved (HTTP 400: `gpt-5.6-sol` rejects non-default
temperature), 3 refused pre-contact. Fix: temperature omitted. Ledger
preserved as incident record. Actual spend $0.00.

### dev-002 (2026-09-16) — fixed worker, single-bug tasks
42/42 completed calls passed (100%), 6 unresolved (local authd socket
"Connection refused", transport failures). Settled $0.20, $0.66 retained
unresolved. 0 extraction failures. Provider framing overhead: constant
+10 input tokens (n=42, zero variance) — added to local pre-contact count.
Finding: 100% baseline exceeds the 80% band -> generator hardened.

### dev-003 (2026-09-16) — two-bug tasks: 48/48 (100%, $0.61 settled)
Cost/task $0.008-$0.027. Still above band -> generator hardened again.

### dev-004 (2026-09-16) — v3: three-bug + longer modules + subtle bugs
48/48 (100%, $0.93 settled). All families 100%. Cost/task $0.0121-$0.0478
(mean $0.0195). 0 unresolved, 0 refused, 0 extraction failures, 0 drift.
Subtle bug classes (aliasing, shared holder state, shallow snapshot,
tax-on-pre-discount) all caught by the model.

### Band decision
Rule: baseline outside 20-80% -> adjust the generator before freezing.
Adjusted twice (v1->v2->v3); baseline stayed at 100%. A further adjustment
is a linear arms race: the task shape (verify each line against a precise
docstring) is fundamentally easy for a frontier debugger. The measurement
is not degenerate — cost per verified task varies 4x and the acquisition
accepts cost reductions at equal output (vc == vp and cc < cp), so
discrimination operates on the cost side and output preservation (V_B >=
V_A) is a one-sided condition. Study proceeds on the v3 corpus.
Total dev spend: $0.00 + $0.20 + $0.61 + $0.93 = $1.74 of the $5 budget.

## 13. Freeze record

- CONFIG.json frozen 2026-09-16 (verified config)
- Corpus frozen: v3 hashes dev `fb8894c6…`, eval `0c0010b8…`,
  calib `555684ce…` (full in `corpus/corpus.json`)
- Code frozen: commit 51b4e0d (study/econ-001 branch)
- Closed records preserved: COMPOUND-001 freeze (f7b1822), RSI-006,
  PR #170 branch (131a4440) — untouched.
