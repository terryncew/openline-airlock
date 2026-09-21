# RPI-001 PREREGISTRATION — frozen before contact

**Study:** RPI-001 (recursive-productivity-improvement 001)
**Run ID:** `rpi001_616e139a`
**Branch:** `study/rpi-001` (from `study/econ-002` @ `9ccd19d`)
**Frozen:** 2026-09-21. No edits after first paid contact except the
one-committed-transaction resume path.

## 1. Question

Do successive inherited method improvements produce more independently
verified useful work per dollar?

## 2. Arms and lineages

- **A:** baseline method M0, unchanged. M0 = frozen `econ.prompts.BASE_METHOD`
  (sha256 `73dac1b8fd4d0bcdabc34faddb3063a3033c3b5ebb5e037059de8663e20b13ca`).
- **B:** M0 + the first accepted improvement M1, then frozen. M1 is acquired
  once (phase 1, below) and the identical frozen artifact is forked to B and C.
- **C:** the identical frozen M1, plus further improvement search (phase 2).
  If phase 2 accepts, C runs M2; otherwise C runs M1.

Lineages are independent after the fork: B never receives phase-2
proposals; C never re-runs phase-1 acquisition.

## 3. Corpus (fresh, matched)

100 tasks (`rpi-eva-0000` … `rpi-eva-0099`), generated with the FROZEN
econ-001 corpus builder. Declared seeds: 20261000–20261016 (45 tasks each;
seeds 20260921–23 were exhausted first: 110/135 duplicates of prior
corpora — the generator's task space is small).

- `eval_sha256`: `933cfadd086e1a561daee659f9460d647f42f700002b5b8d0c55dd0417bc06a3`
- Integrity gate (local, pre-freeze): all 100 reference codes PASS hidden
  tests, all 100 buggy targets FAIL them. 0 integrity failures.
- Disjointness gate: every `target_code` byte-distinct from all 333 eval
  instances in the four prior frozen corpora (econ-001 corpus, corpus_r2,
  corpus_r3, econ-002 corpus). 595 generated duplicates excluded.
- Families cycle logic/interface/config, as in the frozen builder.

## 4. Allocation (frozen, no reuse across phases or rounds)

| Phase | Discovery | Promotion |
|---|---|---|
| Phase 1 round 1 | rpi-eva-0000–0002 | rpi-eva-0003–0014 (12) |
| Phase 1 round 2 | rpi-eva-0015–0017 | rpi-eva-0018–0029 (12) |
| Phase 2 round 1 | rpi-eva-0030–0032 | rpi-eva-0033–0044 (12) |
| Operating (36) | rpi-eva-0045–0080 | one attempt per arm per task |
| Spares (19) | rpi-eva-0081–0099 | unused |

## 5. Operating schedule (frozen)

Per-task arm order is a seeded Fisher–Yates permutation of [A,B,C]
(`random.Random(f"rpi-schedule:{task_id}")`).
`schedule_sha256`: `f1780b140a4ceb439afeeade64e376f2ca51d0964f295f0902e78fb367c391bd`.
Re-verified by the runner before any scientific contact.

## 6. Proposal (the proposer receives the economic objective)

Each acquisition round: 3 discovery attempts (parent method; advisory
feedback only) → 1 proposal call → delta extraction → `apply_delta`
rendering → 12 paired promotion attempts (parent vs candidate).

The proposer explicitly receives the economic objective: *"Produce a
method change whose goal is more independently verified useful work per
dollar: equal-or-better verified success at lower measured execution
cost."* It also sees the frozen acceptance criterion below. Receiver
acceptance rules and held-out tests stay outside its control: it never
sees the promotion tasks, and only the frozen receiver rule decides.

Delta format: exactly one ```delta fenced block; directives
REPLACE_STEP/ADD_STEP/REMOVE_STEP against the [k]-block-numbered current
method (block [1] = preamble). Malformed delta, missing block, cap
exceeded (1500 tokens), or empty model output → charged rejection,
never repaired, never retried.

## 7. Frozen receiver rule (phase 1 and phase 2)

ACCEPT iff, on the 12 paired promotion tasks:
1. parent passes 12/12 AND candidate passes 12/12 (extracted code, local
   hidden-test evaluation);
2. zero regressions (no task the parent passes is failed by the candidate);
3. candidate total settled promotion cost ≤ parent total settled
   promotion cost (ratio ≤ 1.0).

Any non-ok promotion attempt (unresolved, overrun, refused) VOIDS the
round (charged rejection). Phase 1 runs up to K1=2 rounds, stopping at
the first acceptance. Phase 2 runs K2=1 round from M1 (or M0 if phase 1
failed to accept).

## 8. Frozen accounting split

Quoted from the owner revision (2026-09-21): *"Acquire the first accepted
improvement once. B and C must receive the identical frozen improvement
artifact and identical realized first-improvement
acquisition/verification cost allocation. C alone incurs subsequent
recursive-search, acquisition, and verification costs. Apparatus
development spend is reported separately and is not charged as arm
performance cost; all scientific search, failed proposals, acceptance
verification, and downstream execution costs are charged to the relevant
arm."*

- D1 = all phase-1 scientific spend (settled + retained unresolved).
  Arm B bears D1/2; arm C bears D1/2.
- D2 = all phase-2 scientific spend (settled + retained unresolved).
  Arm C bears D2 alone.
- Arm A: operating spend only. Arm B: D1/2 + operating.
  Arm C: D1/2 + D2 + operating.
- Apparatus spend (preflight, qualification calls) uses a separate
  ledger and is never charged as arm performance.

## 9. Envelopes, model, budgets, call inventory

- Model: `gpt-5.6-sol` (frozen in worker.py), reasoning effort medium,
  temperature omitted (provider rejects non-default).
- Envelopes: solving / proposal / preflight, each $0.05 reservation,
  one-shot POST, no retries. Overrun above reservation → OverrunAbort,
  fail-closed.
- Scientific budget: $10.00 (ledger-gated). Apparatus budget: $10.00
  (separate ledger).
- Max scientific calls: (2×28) + (1×28) + (36×3) = 192.
  Worst-case reservation: 192 × $0.05 = $9.60 ≤ $10.00.

## 10. Interruption / resume (frozen)

- Ledger replays on startup. Open reserves are retired as unresolved
  exposure and NEVER resent.
- Interruption during a promotion round voids that round (charged
  rejection); phase 1 proceeds to the next round if any.
- Interruption during phase 2 voids phase 2 (C inherits M1).
- An operating task with any non-ok arm attempt is dropped from the
  paired comparison (all arms); spend retained per §8. If fewer than 30
  paired tasks remain, the operating comparison is INCONCLUSIVE.
- Operator stop file halts before the next paid invocation (checked
  pre-reservation).

## 11. Terminal decision rules (frozen)

- Operating comparison is conclusive iff ≥30 paired tasks (of 36).
- Zero-regression guard: an arm that fails any task arm A passes cannot
  "produce more" (it produced less verified work).
- Primary (all-in work/$ per §8): B "produced more" iff
  (all-in work/$)_B / (all-in work/$)_A ≥ 1.05 with no regressions;
  likewise C vs B. Otherwise: "did not produce more within the frozen
  horizon and split."
- Preregistered decomposition: operating work/$ per arm (excludes
  acquisition) with paired per-task cost-ratio 95% CI.

## 12. Sensitivity (stated before contact)

- Operating comparison: paired over 36 matched tasks; can reveal
  sustained operating cost advantages around ≥8% at preserved success.
- All-in comparison: under the frozen split, only very large operating
  effects (order ~55% sustained saving, given realized D1) could repay
  acquisition within the 36-task horizon. Smaller or slower-payback
  improvements yield "did not produce more within the frozen horizon,"
  not "improvements cannot pay."

## 13. Claim ceiling

At most: the exact terminal disposition, the frozen hashes, the
realized all-in economics per arm (spend + unresolved exposure, split
shown), and the narrow earned claim ("produced more" / "did not produce
more within the frozen horizon and split" / "inconclusive"). No
generalization beyond the frozen corpus, model, and horizon.

## 14. One-committed-transaction rule

No rerun, no rescue, no replacement proposal, no threshold movement, no
fresh transaction after contact. Only the existing same-transaction
resume path (§10) is allowed. A failed base case stays failed.
