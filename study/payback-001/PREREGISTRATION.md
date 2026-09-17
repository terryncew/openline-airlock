# PAYBACK-001 — Preregistration (frozen before contact)

**Study ID:** `payback001`
**Branch:** `study/payback-001`
**Frozen base SHA:** `9ccd19d853083b97f8aed4d30d8ff00c553a1f12` (origin/study/econ-002 HEAD at branch creation)
**Status:** PREREGISTERED — no paid contact authorized. No paid calls until explicit authorization after remote verification.
**ECON-001 / ECON-002:** untouched; standings unchanged; not reopened.

## The earned question

CAN ONE BOUNDED IMPROVEMENT INVESTMENT REPAY ITS OWN ACQUISITION COST OVER A FROZEN FUTURE WORK HORIZON WHILE PRESERVING RECEIVER-VERIFIED QUALITY?

## Material deviation from the provisional design (frozen finding)

The provisional design specified H=700 operating tasks (715 fresh tasks total).
Finalization proved this impossible with the preserved apparatus:

- The preserved ECON task generator's reachable space is ~815 distinct tasks
  (16,000 draws enumerated; count plateaued).
- 333 are already consumed by prior ECON scientific instances
  (econ-001 r1/r2/r3, econ-002).
- 482 fresh tasks exist — fewer than 715.

The generator was NOT expanded to protect the provisional number (that would
be apparatus-stretching: new task machinery with an unvalidated cost regime).
Instead the horizon is refinalized at the largest clean value the apparatus
supports:

**H = 450 operating tasks; 465 fresh tasks total (3 discovery + 12 promotion + 450 operating).**

Re-derived power (D≈$0.37, mean task cost c≈$0.013134, null margin $0.26926):

- Strong positive needs mean per-task saving > (D + 0.26926)/450 ≈ $0.00142,
  i.e. sustained saving ≳ 10.8%.
- Break-even N*(s) = D/(s·c): s=8% → t≈352 (observable within horizon);
  s=5% → t≈565 (beyond horizon: cannot break even).
- All five terminal states remain reachable. The study is a genuine test with
  a higher bar, not a toothless one.

## Frozen design

- One improvement investment only. K=1 accepted successor maximum.
- Control: frozen baseline method (`prompts.BASE_METHOD`, the econ-001 R3
  baseline), unchanged, on the frozen ordered schedule.
- Treatment: starts from the same baseline; may inherit one accepted
  successor from the bounded acquisition.
- Acquisition (treatment pays all of it; rejected spend still counts):
  3 discovery attempts (parent) + 1 proposal + 12×2 promotion attempts.
- Operating: 450 paired tasks; both arms execute exactly once per task;
  frozen per-pair arm order (225 CT / 225 TC, seed 20260916, SHA below) so no
  systematic temporal/provider/cache/run-order effect can favor one arm.
- No recursive generations. No routing infrastructure. No new provider
  integration. No self-modifying acceptance rule.

## Local successor acceptance rule (quality/sanity gate, frozen)

Accept iff ALL hold:

1. parent 12/12 verified success on the 12 promotion tasks;
2. candidate 12/12 verified success;
3. zero per-task regressions (candidate fails nothing the parent passes);
4. candidate paired promotion cost ≤ 1.5 × parent paired promotion cost;
5. the candidate's source never judges itself (model proposes; the frozen
   receiver rule judges).

**Why 1.5×:** it is an operational safety bound, not an economic criterion.
It exists only to keep one explosive successor from making the 450-task
horizon and the $18 budget meaningless. A candidate 1.4× MORE expensive than
the parent can still be accepted — the frozen horizon, not the gate, decides
whether the investment repays. No immediate-savings requirement is imposed.

## Corpus and schedules (frozen)

- 465 tasks, byte-content-disjoint from all prior ECON scientific instances
  (verified: 0 overlap against econ-001 r1/r2/r3 + econ-002 content hashes).
- Seeds declared: corpus 20260921 (derived `gen<k>` streams, first-465-new
  kept — declared procedure), operating order 20260924, arm order 20260916,
  promotion order 20260925.
- corpus SHA-256: `f7879ba68c664600469588caf637e6a048c581f04fd44271a4848f8863e10a69`
- arm-order SHA-256: `97558f018d6138db1ac383ec048ba998acae8f08b0dd243934a0cb1c4724a560`
  (balance exactly 225 CT / 225 TC).
- Allocation: indices 0–2 discovery, 3–14 promotion, 15–464 operating pool;
  operating order is the frozen permutation in OPERATING_ORDER.json.
- Composition note: 464 logic-family + 1 config-family (the generator's
  remaining fresh space is logic-dominated). No task swapping, no replacement
  tasks, no difficulty retuning after contact, no horizon extension.

## Empirical-null calibration (frozen; replaces the ad-hoc 2·sd·√H bar)

Source: preserved identical-method replicated observations ONLY —
ECON-001 rep1, 36 task×method cells × 3 true replicate attempts.
Same method plays both "control" and "treatment".

Procedure (frozen, `scripts/null_calibration.py`): per synthetic task, draw a
cell uniformly, draw an ordered pair of distinct attempts uniformly,
Δ = control − treatment; sum 450 Δs → one synthetic null terminal advantage
(D=0). N=20,000 synthetic horizons, seed 20260916.

Results (USD terminal advantage under no true method effect):

| variant | median | p90 | p95 | p99 | max |
|---|---|---|---|---|---|
| V1 primary (permute within cell) | 0.00006 | 0.14930 | 0.19256 | **0.26926** | 0.46752 |
| V1b reseed | 0.00039 | 0.15054 | 0.19186 | 0.27434 | 0.44334 |
| V2 with-replacement | -0.00042 | 0.12116 | 0.15636 | 0.22056 | 0.37212 |
| V3 parametric per-cell Gaussian | -0.00157 | 0.14934 | 0.18998 | 0.27091 | 0.50666 |
| V4 pooled (cell structure destroyed) | 0.00040 | 0.15725 | 0.20370 | 0.28671 | 0.50027 |
| V5 half the cells (18) | -0.00044 | 0.14274 | 0.18212 | 0.26376 | 0.45292 |
| V6 independent R2 replicate cells (12) | -0.00020 | 0.12646 | 0.16350 | 0.23100 | 0.42750 |

**Frozen terminal margin: NULL_MARGIN_99 = $0.26926** (V1 p99).

Composition caveat (frozen): the null is calibrated on 36 config-family
cells; the operating horizon is logic-family (apparatus limit above).
Phase-2 found config the wider-tailed family, so this margin is conservative
for a logic horizon — it is harder, not easier, to earn a strong positive.
The p99 is stable (±4%) across the primary-family resampling choices; the
independent R2 sample (V6) is lower, consistent with a conservative margin.

Frozen wording: "Under preserved identical-method empirical-null resampling,
X of 20,000 simulated 450-task horizons exceeded the frozen terminal margin."
This is NOT a true population false-positive probability.

## Terminal states and accounting (frozen)

- D = all treatment acquisition settled cost + all retained unresolved
  acquisition reservations (+ any other preregistered acquisition-side cost
  classified as treatment investment). The non-scientific preflight (if run)
  is excluded: separate accounting, exactly as ECON-002.
- Operating task i: Δ_i = control_cost_i − treatment_cost_i.
- A(t) = Σ_{i≤t} Δ_i − D; A(0) = −D.
- Break-even time: first t with A(t) > 0.
- Unresolved-but-continued operating tasks contribute Δ_i = 0; their
  reservations are retained exposure, never silent gains.

Primary positive requires ALL of:

1. acquisition produced one accepted successor;
2. no receiver-quality regression under the frozen quality rule
   (treatment fails a task the control passes → strong positive VOID);
3. A(450) > 0;
4. A(450) > NULL_MARGIN_99 ($0.26926);
5. all required accounting evidence preserved (ledger, TASKS.jsonl,
   RUN_STATUS.json, candidate method + SHA).

Terminal verdicts:

- A(450) ≤ 0 → **NO_PAYBACK** (negative): the investment did not repay
  within the frozen horizon.
- 0 < A(450) ≤ $0.26926 → **NOMINAL_NOT_BEYOND_NULL**: nominal in-horizon
  payback, but not beyond preserved identical-method variation; strong
  positive not earned.
- A(450) > $0.26926 with quality preserved → **STRONG_POSITIVE**.
- Treatment fails a task control passes → strong positive VOID.
- No accepted successor → operating skipped; terminal result records
  acquisition debt only → **NO_PAYBACK** under the frozen question.
- Horizon incomplete for infrastructure/budget reasons → **INCOMPLETE**;
  never positive, never negative, never rescued.

## Budget and call inventory (frozen)

Maximum paid-call inventory, mechanically recomputed from frozen code
(`--offline` asserts these):

| class | calls | reservation each |
|---|---|---|
| preflight (non-scientific, separate accounting) | 1 | $0.11 |
| acquisition discovery | 3 | $0.11 |
| proposal | 1 | $0.11 |
| promotion (12 tasks × 2 arms) | 24 | $0.11 |
| operating (450 tasks × 2 arms) | 900 | $0.11 |
| **scientific total** | **928** | |
| **grand total** | **929** | |

- Physical budget ceiling: **$18.00**, ledger-enforced.
  Covers the acquisition cap ($3.50) + 900 tasks at the frozen mean task cost
  ($0.013134 → $11.82) = $15.32 < $18. Expected settled ≈ $12.2
  (acquisition ~$0.37 + operating ~$11.82): 48% headroom. Well under the
  ~$25 Route-A estimate — no stop triggered.
- Worst-case retained exposure: ≤ $18.00 (the ledger refuses reservations
  beyond the ceiling; breach aborts to INCOMPLETE, never raises the ceiling).
- Stop behavior: reservation refusal (InsufficientBudget) → halt →
  INCOMPLETE. Operator STOP file checked before every paid invocation;
  stop → no call issued → halt → INCOMPLETE. Unresolved call (missing usage)
  → reservation retained, study continues, task contributes Δ=0.

## Failure / no-rescue rules (frozen before contact)

- Malformed proposal = charged rejection (spend stays in D).
- Rejected acquisition spend remains debt. No candidate replacement.
- No second acquisition round. No task replacement. No arm-order change.
- No threshold movement. No horizon extension for any reason.
- No post-contact prompt changes. No code repair/relaunch under the same
  study ID.
- Infrastructure failure after contact: preserve the partial run, stop,
  record INCOMPLETE.
- Missing evidence is recorded, never reconstructed.
- Operator STOP checked before every paid invocation.

## Promotable claim boundaries (frozen)

Maximum positive claim (mechanically equivalent):

"The treatment spent $D acquiring one receiver-approved method change, began
the operating horizon $D behind the baseline, crossed observed break-even
after N frozen work units, and finished the 450-task horizon $Y ahead —
beyond the preserved identical-method empirical-null margin — while
preserving receiver-verified quality."

Maximum negative claim:

"The treatment spent $D on bounded improvement and did not repay that
investment within the frozen 450-task horizon while preserving the
preregistered receiver-quality conditions."

Do NOT claim: general recursive self-improvement; indefinite compounding;
autonomous general intelligence; cross-workload generalization; projected
payback as observed payback; future profitability beyond H.

## Implementation (frozen)

- 730 code lines across 6 files (≤800 target): thin runner
  (`scripts/payback_run.py`), thin accounting (`scripts/payback_acct.py`),
  corpus/arm-order glue (`scripts/gen_pb1_corpus.py`), null calibration
  (`scripts/null_calibration.py`), frozen constants (`frozen.py`), offline
  tests (`tests/test_offline.py`, 18/18 passing).
- Reuses preserved ECON primitives: attempt, evaluate, worker, ledger,
  prompts/apply_delta, extract, corpus, envelopes. Zero modifications to
  preserved ECON files.
- No router. No recursive loop. No new provider integration.
- `payback_run.py --offline` verifies every freezable artifact with zero
  provider contact. Paid mode requires `--authorize-paid-contact` and is NOT
  authorized.

## Proof of zero paid PAYBACK-001 contact

- No `payback_run.py --authorize-paid-contact` invocation has occurred.
- No `study/payback-001/runs/` directory exists.
- All work to date: offline corpus generation, offline null calibration,
  offline tests. Zero provider requests issued under any `pb1-` invocation ID.
