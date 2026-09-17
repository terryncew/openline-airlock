# PAYBACK-002 — Terminal Evidence Freeze Note

**Standing: `INCOMPLETE` (frozen). This is NOT a negative payback result.**

Written: 2026-09-16 (UTC), from preserved evidence only.
Purpose: frozen, additive, proof-only record of the PAYBACK-002 terminal
state. Nothing in this note modifies any experimental artifact. No evidence
was reconstructed. The outcome is not softened.

PAYBACK-001 remains untouched: `INCOMPLETE_APPARATUS_DEFECT`.
PAYBACK-002 remains untouched: `INCOMPLETE`.

## Identity

- Study ID: `payback002`
- Branch: `study/payback-002`
- Preregistration (frozen before contact):
  `1e5c5a1fd698b0f9eb94d3adfcb25ea53e766173`
- Base: `acdc0b4ccb637aaa2782996018c370628b6b44a0`
  (PAYBACK-001 failure-evidence commit, preserved)
- Terminal evidence commit (run directory as the dead process left it):
  `b295e12ad3cbf3ffc89d128c5f7fa2285fcffbc4`
- Run directory: `study/payback-002/runs/payback002/`
  (tree `df902c71e0ae7cba9af2906237a5e65c7672705e` at the evidence commit)

## What the preserved evidence shows

- **Real provider contact.** Dispatch via `worker.RealProvider()`; provider
  request/response bytes preserved in `raw/`. The PAYBACK-001 apparatus
  defect (abstract `worker.Provider()`) did not recur.
- **Clean preflight.** Exactly one post (`pb2-pre-00`), status ok, usage
  12/18 tokens, settled $0.000408, reservation settled, raw persisted.
  Preflight cost excluded from acquisition debt D per the frozen rule.
- **Acquisition complete.** 3 discovery calls + 1 proposal, all settled.
  **D = $0.372212** settled / $0.00 retained.
- **Successor ACCEPTED.** Proposal delta replaced method step 5 (run visible
  tests or walk by hand; cover the edge case). Promotion 12/12 vs 12/12,
  0 regressions, cost ratio **1.0175** (≤ 1.5× cap). Accepted successor
  SHA-256: `6f28b65a89b283460ad04e4b6c13defa08c5906c280dc381fef7e2d507b2d6d4`.
- **Operating: 171/450 tasks.** 341 operating calls settled, 0 regressions.
  Partial cumulative curve: **A(0) = −$0.371712; A(171) = −$0.381312.**
  No break-even observed in the completed portion. **No A(450)** — the
  horizon did not complete.
- **Money.** $4.861228 settled of the $18.00 ceiling across 370 calls
  (1 preflight + 28 acquisition + 341 operating). **$0.22 retained
  unresolved** (2 × $0.11 operating reservations). Not released: retained
  unless later evidence mechanically proves non-dispatch/non-charge; any
  later reconciliation is additive and outside the frozen run bytes.

## What ended the run

Two consecutive transport failures, then runner death:

1. `pb2-o-C-0170` — `transport_no_usage: Remote end closed connection
   without response` (task 170 control unresolved, retained $0.11; delta 0).
2. `pb2-o-T-0171` — `transport_no_usage: <urlopen error [Errno 111]
   Connection refused` (task 171 never completed; no `pb2-o-C-0171`).

The runner process died: no `RUN_STATUS.json`, no runner terminal outcome,
background session record lost, stdout/stderr unrecoverable. The run
directory is byte-identical to what the dead process left, except for the
operator's `RESULTS_NOTE.md`.

## Capture / apparatus limitations (preserved, not repaired)

1. **No runner terminal state exists.** The INCOMPLETE verdict is the
   operator's application of the frozen incompleteness rule
   ("horizon cannot complete because of stop/budget/infrastructure →
   INCOMPLETE") to preserved evidence — `RESULTS_NOTE.md` is identified as
   an operator record, not a runner-produced verdict.
2. **Latent accounting defect (not repaired, per no-rescue):**
   `scripts/payback_acct.py:compute` reads `e["retained"]` for unresolved
   ledger entries, but the real ledger writes `"reservation"` → `KeyError`
   on any real ledger with unresolved entries. Final accounting was
   recomputed read-only from preserved evidence with the frozen formulas.
3. Runner stdout/stderr for the paid run is unrecoverable.

## Confirmations

- Terminal verdict: **INCOMPLETE** — no verdict earned on the payback
  question. Never rescued, never relaunched, never extended.
- Zero rescue / relaunch / threshold movement / task substitution / horizon
  extension under `payback002`. The accepted successor was not turned into
  a retroactive completion. The 171-task partial curve was not used to move
  thresholds.
- Exactly one paid run was executed under the authorization; it is consumed.
- Any further attempt at the payback question requires a new study identity
  and fresh authorization.

## Integrity

See `INTEGRITY_MANIFEST.md` for the pinned SHAs (preregistration commit,
terminal evidence commit, run-directory tree, accepted successor bytes).
