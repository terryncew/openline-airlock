# RPI-001 TERMINAL RESULT — run rpi001_616e139a

**Status:** TERMINAL 2026-09-21 (~09:55 PDT). 192/192 scientific calls.
Zero unresolved reservations. Zero dropped operating tasks.

## Identity

- Study: RPI-001 · Run: `rpi001_616e139a` · Branch: `study/rpi-001`
- Corpus eval_sha256: `933cfadd…17bc06a3` (100 tasks) · Schedule sha256:
  `f1780b14…67c391bd` · Task allocation: frozen
- Model: gpt-5.6-sol (exact model/effort/completion qualified pre-contact)
- M0 sha256: `73dac1b8fd4d0bcd…3e20b13ca` (frozen baseline method)

## Lineages (independent: each round on fresh tasks)

- **Phase-1 round 1** (tasks 0000–0014): proposer emitted delta `2fe73863…`;
  receiver gate REJECTED — 12/12 valid, 0 regressions, cost ratio
  1.0096 > 1.0 (candidate cost exceeded parent).
- **Phase-1 round 2** (tasks 0015–0029): delta `6a34ea00…` ACCEPTED —
  12/12, 0 regressions, cost ratio 0.9208. **M1** sha256
  `837d665832e26261762b73e3ef995ef92541ed654fb11d6c137f16c968cef602`.
  M1 compresses the method to 3 steps (INSPECT / FIX / VERIFY).
- **Phase-2 round 1** (tasks 0030–0044, from M1): delta `c16a3008…`
  REJECTED — 12/12, 0 regressions, cost ratio 1.0302 > 1.0 (further
  compression cost MORE, not less). **M2 not accepted; arm C ran M1.**
- Arm methods: A = M0 (`73dac1b8…`), B = M1 (`837d6658…`),
  C = M1 (`837d6658…`).

## Frozen accounting split (quoted from PREREGISTRATION §8)

"Acquire the first accepted improvement once. B and C must receive the
identical frozen improvement artifact and identical realized
first-improvement acquisition/verification cost allocation. C alone
incurs subsequent recursive-search, acquisition, and verification
costs. Apparatus development spend is reported separately and is not
charged as arm performance cost; all scientific search, failed
proposals, acceptance verification, and downstream execution costs are
charged to the relevant arm."

Realized: D1 (phase-1 scientific) = $0.745252 over 56 invocations;
D2 (phase-2 scientific) = $0.357848 over 28 invocations. B bears
D1/2 = $0.372626; C bears D1/2 + D2 = $0.730474. Apparatus
(preflight + model-output qualification) = $0.002640, separate.

## All-in economics per arm (36/36 paired tasks, zero dropped)

| Arm | Method | Acquisition charged | Operating spend | All-in spend | Verified work | All-in work/$ |
|-----|--------|--------------------|-----------------|--------------|---------------|----------------|
| A   | M0     | —                  | $0.491584       | $0.491584    | 36/36         | 73.23          |
| B   | M1     | D1/2 = $0.372626   | $0.472748       | $0.845374    | 36/36         | 42.58          |
| C   | M1     | D1/2+D2 = $0.730474| $0.466868       | $1.197342    | 36/36         | 30.07          |

- Operating-only work/$: A 73.23 · B 76.15 · C 77.11.
- Paired B vs A: geomean ratio 1.038, 95% CI [1.0042, 1.073], n=36 —
  M1's operating efficiency ~3.8% above M0, CI excludes 1.0.
- Paired C vs B: geomean ratio 1.007, 95% CI [0.9705, 1.0449] —
  includes 1.0 (same method; apparatus behaves as expected).
- Regressions: B vs A none; C vs B none.
- Scientific ledger: $2.5343 settled / $0.0000 unresolved / $2.5343
  encumbered of $10.00. Apparatus: $0.00264 of $10.00.
- Total study spend $2.5370; authorized funds remaining ≈ $74.77
  ($77.31 freeze − spend). No top-up was needed.

## Terminal disposition (frozen rule)

- operating_conclusive: true (36 ≥ 30 paired tasks)
- B_produced_more_allin (≥1.05×, no regressions): **false**
  (42.58 vs 73.23)
- C_produced_more_allin (≥1.05×, no regressions): **false**
  (30.07 vs 42.58)

## Narrow claim earned

**B and C did not produce more independently verified useful work per
dollar than A and B respectively, within the frozen horizon and split.**

Supporting observations (not claims of production):
- M1 earned a genuine, receiver-verified ~3.8% operating work/$
  advantage over M0 (paired 95% CI excludes 1.0, zero regressions).
- That advantage did not repay the $0.745 acquisition cost within 36
  downstream tasks — exactly the preregistered sensitivity case:
  operating comparison detects small sustained advantages; all-in
  comparison within this horizon requires very large ones.
- Phase-2's more aggressive compression was rejected on cost
  (1.0302 > 1.0): further compression did not buy further efficiency.
- C-vs-B on the identical method returned ratio ≈ 1 (CI includes 1.0),
  consistent with a calibrated comparison.

## Limits

- Claim is bounded to the frozen corpus, model, envelopes, 36-task
  horizon, and frozen split. No generalization to other tasks,
  models, horizons, or cost structures.
- No rerun, no rescue, no threshold movement post-contact. One
  committed transaction; interruption rules were not triggered.
- Evidence: `runs/rpi001_616e139a/result.json`, `ledger.jsonl`,
  `apparatus_ledger.jsonl`, `raw/` (196 responses), frozen corpus /
  schedule / allocation hashes above.
