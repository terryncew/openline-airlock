# ECON-001 — Rep-1 Results Report (frozen)

**Run ID:** ECON-001-R3 (study_id `econ001_61cc724b`, directory `runs/study-003/`, branch `run/econ-001-r3`)
**Freeze status:** FROZEN — this file and the receipts/logs listed in the freeze manifest below are sealed.
No relaunch. No repair-and-continue. No replacement repetitions. No horizon extension.
Nothing in this report authorizes, proposes, or schedules a next experiment.

> Nomenclature: "R3" is the run ID (ECON-001-R3), not repetition 3. Repetitions 2 and 3 never executed.
> Nothing below may be read as implying repetition 3 began.

---

## 1. COMPLETED REP-1 OBSERVATION

Rep 1 completed before the infrastructure halt (`status: completed` in `rep1.json`).
128 rep-1 invocations. Rep-1 spend: **$3.113695** (per `rep1.json` `spend_usd`).

### Acquisition (both generations, rep 1)

Both acquisition candidates were **rejected** by the preregistered gate:

- G1: `decision = reject`, reason `no_strict_improvement (vc=3 vp=3 cc=0.111316 cp=0.081608)`
- G2: `decision = reject`, reason `no_strict_improvement (vc=3 vp=3 cc=0.088356 cp=0.071828)`

(`G1_accepted = false`, `G2_accepted = false` in `rep1.json`. The 3 calibration probe tasks
verified 3/3 on both candidate and parent, but candidate cost was not strictly lower.)

Complete acquisition debts (per frozen cost accounting):

- **D1 (first-acquisition debt, G1): $0.277330**
- **D2 (second-acquisition debt, G2): $0.253009**

### Measurement: exact arm costs and verified counts (36 verified per arm)

| Arm | Verified | Pooled cost (USD) | USD per verified |
|-----|----------|-------------------|------------------|
| A   | 36/36    | 0.849092          | 0.0235859        |
| B   | 36/36    | 0.840792          | 0.0233553        |
| C   | 36/36    | 0.893472          | 0.0248187        |

Output preservation held descriptively: B verified 36 ≥ A 36; C verified 36 ≥ B 36.

**Layer separation — descriptive unit-cost difference is not payback.**
Descriptively, B cost $0.008300 less than A over the 36 verified tasks ($0.0233553 vs
$0.0235859 per verified), and C cost $0.052680 more than B. These are descriptive
execution-cost differences only. The acquisition debts D1 and D2 are accounted in the
payback block below, not here.

### Observed acquisition payback (preregistered in-horizon inequality: D + C_hi ≤ C_lo)

**G1 — B vs A: observed_payback_earned = false**
- Exact failed inequality: `0.277330 + 0.840792 <= 0.849092`
- LHS = 1.118122 > RHS = 0.849092. Shortfall: **$0.269030**.
- 36/36 verified on both sides.

**G2 — C vs B: observed_payback_earned = false**
- Exact failed inequality: `0.253009 + 0.893472 <= 0.840792`
- LHS = 1.146481 > RHS = 0.840792. Shortfall: **$0.305689**.
- 36/36 verified on both sides.

**Therefore: rep 1 observed neither first-acquisition payback nor second-acquisition
payback within the frozen 36-task horizon.**

This is a completed-repetition observation. It is NOT a claim that "process improvement
does not pay back." Nothing is inferred about repetitions 2–3, longer horizons, other
task distributions, other models, or replication.

### Cumulative break-even traces (36 verified tasks, task order)

Per-task cumulative net position = cumulative per-task savings − acquisition debt.
Full task-ordered series: `runs/study-003/rep1_breakeven_traces.json` (36 rows,
`cost_A`/`cost_B`/`cost_C` per task plus `G1_cum_net` and `G2_cum_net`).

| Trace | Start | End (task 36) | Min | Max | Crossed zero? |
|-------|-------|---------------|-----|-----|---------------|
| G1: cum(A−B) − D1 | −0.277330 | **−0.269030** | −0.285910 | −0.259850 | No |
| G2: cum(B−C) − D2 | −0.253009 | **−0.305689** | −0.310329 | −0.244109 | No |

Neither trace reaches break-even at any point. Mean per-task saving: G1 +$0.000231
(stdev 0.005083), G2 −$0.001463.

### Projected future payback (preregistered, exploratory only — NOT a finding)

`projected_future_payback` was preregistered in PROTOCOL.md (rep-level per-task savings →
median k*). Reported here as descriptive/exploratory only, not headlined, not a verdict:

- G1: median k* = **1202.88 tasks** to break even at the observed rep-1 per-task saving.
- G2: k* = **∞** (observed per-task saving is negative; no finite break-even).

With one completed repetition these projections have no inferential standing.

---

## 2. STUDY-LEVEL STATUS

**`INCONCLUSIVE_INCOMPLETE_REPETITIONS`**

- Only 1 of the 3 required repetitions completed.
- Reps 2 and 3 never executed.
- No pooled three-repetition verdict.
- No successive-improvement economic advantage established.
- No overall amortization verdict established.

The completed repetition contains valid descriptive evidence (Section 1). The study as a
whole earns no economic verdict.

---

## 3. INFRASTRUCTURE STOP

Run ECON-001-R3 was halted by the frozen fail-fast rule on 2026-09-16 at 14:42:37 PDT,
during rep-2 G2 acquisition, at invocation `rep2_g2_A_r3-eva-inte-0040`.

Stop reason, verbatim:

> "infrastructure failure before dispatch (<urlopen error [Errno 111] Connection refused>); halting study, no further invocations"

- The failure was demonstrably pre-dispatch: POSIX ECONNREFUSED at `connect()` after the
  authd surrogate was obtained — zero bytes transmitted. It is recorded as
  `unresolved / transport_no_usage` ($0.11 retained) and **is not counted as a
  scientific task result**.
- The fail-fast mechanism then issued **zero further invocations** (verified: no settle
  or reserve after the halt record; `reserved_open = 0.00`).
- One earlier rep-2 acquisition invocation, `rep2_g2_C_r3-eva-inte-0037`, ended
  `transport_no_usage: Remote end closed connection without response` — ambiguous,
  retained as unresolved ($0.11), not counted as science.
- Rep 1 (completed before the halt) is unaffected by the stop.

Record staleness note: `report.json`'s `unresolved_exposure` section shows
`count: 0` — that file was written at rep-1 completion, before the halt. The canonical
accounting is `study.json` + `ledger.jsonl` (Section 4). No scientific field depends on
the stale section; it is recorded here so the discrepancy is not mistaken for a revision.

---

## 4. EXACT ACCOUNTING (all ECON launches)

Study allocation: $50.00. Development accounting kept separate per the frozen protocol.

| Launch | Settled (USD) | Unresolved retained (USD) | Open reserves (USD) | Encumbered (USD) |
|--------|--------------|---------------------------|---------------------|------------------|
| Launch 1 (aborted, runner crash) | 0.148296 | 0.00 | 0.00 | 0.148296 |
| Launch 2 (interrupted post-amendment) | 0.861360 | 0.11¹ | 0.00 | 0.971360 |
| ECON-001-R2 (infrastructure-incomplete; $33.11 released per frozen reconciliation `2c77730`, no longer encumbered) | 1.464214 | 0.11² | 0.00 | 1.574214 |
| ECON-001-R3 (this run) | 4.533790 | 0.22³ | 0.00 | 4.753790 |
| Study infra verification (`dev_verify_00`) | 0.003240 | 0.00 | 0.00 | 0.003240 |
| **Study total** | **7.010900** | **0.44** | **0.00** | **7.450900** |

¹ Launch 2: `rep1_g1_C_eva-conf-0011` — operator-terminated in flight; provider outcome unknown; not resent.
² R2: `rep1_g2_C_r2-eva-conf-0038` — remote end closed connection; retained per protocol.
³ R3: `rep2_g2_C_r3-eva-inte-0037` (remote closed, ambiguous) + `rep2_g2_A_r3-eva-inte-0040`
   (connection refused, demonstrably pre-dispatch, excluded from science).

**Study allocation remaining: $50.00 − $7.450900 = $42.549100.**

Development (separate track): settled $1.749216 (dev-001…dev-004), unresolved retained
$5.61 ($4.95 pre-dispatch refused + $0.66 transport unknowns), encumbered $7.359216 —
against the $5 development allocation (exceeded; standing record, not part of the study).

---

## 5. RUN IDENTITY AND STOP POINT

- Run ID: **ECON-001-R3** — `study_id econ001_61cc724b`, `runs/study-003/`, branch `run/econ-001-r3`.
- First reservation: 2026-09-16 13:44:02 PDT (`calib_preflight`).
- Stop point: 2026-09-16 14:42:37 PDT, rep-2 G2 acquisition, invocation
  `rep2_g2_A_r3-eva-inte-0040` (connection refused, pre-dispatch).
- Code: frozen at commit `f07981d` (behavior identical to proven repair commit `25103c8`).
- Model/prices frozen per RUN_MANIFEST.md: `gpt-5.6-sol`, reasoning effort `medium`,
  $4.00/$0.40/$5.00/$20.00 per 1M input/cached/cache-write/output.
- Corpus: `corpus/corpus_r3.json`, SHA-256
  `64b448a2be420ea8d89d0816b68bdb255f8a80cf4462cea89d183284aafa0899`, master seed 20260917.

---

## 6. FREEZE MANIFEST

Frozen 2026-09-16 (PDT). SHA-256 over the exact bytes below. The original ledgers are
append-only; nothing was altered to produce this report.

| Path | SHA-256 |
|------|---------|
| `runs/study-003/RESULTS_REP1_REPORT.md` | (this file — frozen by the freeze commit hash below) |
| `runs/study-003/ledger.jsonl` | `e02bf9a9c5e08f7129bee4ab2e54931b8e0a4060d8e17c50ed54031cde4a1ac6` |
| `runs/study-003/study.json` | `51184fe43303f7199e1fad1533e5f08bb6badaecb19e0243da165c46d250218f` |
| `runs/study-003/report.json` | `7c50426b8364f1c1017c79e032829445fdacfdf09da470988848315a3e2d5483` |
| `runs/study-003/rep1.json` | `801935d3ed46499ddc2010e212df48e87e9fdac2b8caf527937f918640479323` |
| `runs/study-003/rep1_breakeven_traces.json` | `fd0730b054bf3aa4bebef214b8d7416e2ef166e7773d0b9a08e85a890e3b9fba` |
| `runs/study-003/calibration.json` | `ff1bdc84831475637919c4bf55015158c6b574c715f9ced097300c49e06d9153` |
| `runs/study-003/console.log` | `5e8c57dafa405a262e60c9c982e7e7c39c2c8267af73a33a779b6dc2956c64f1` |
| `runs/study-003/RUN_MANIFEST.md` | `a401ea3a3aa9eac0c7be5484ba89c06ce59080ba3a392482f944a800e3a30786` |
| `runs/study-003/raw/` (190 files, combined hash of sorted per-file SHA-256) | `28c2028a48d4b72f3e57cd1ad7d2af6432b4bdcc09dd1cea8de4e502d689f1a4` |

Freeze commit: `run/econ-001-r3` — recorded below at freeze time.
