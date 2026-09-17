# PAYBACK-002 — Results / freeze note

**Authorized SHA:** `1e5c5a1fd698b0f9eb94d3adfcb25ea53e766173`
**Study ID:** `payback002`
**Branch:** `study/payback-002`
**Run directory:** `study/payback-002/runs/payback002/`
**Note written:** 2026-09-16, after the run reached its end state. This note is
an operator record written from preserved evidence only. Nothing in the run
directory was modified, repaired, or reconstructed.

---

## Preflight result: CLEAN PASS

- Exactly one provider post (`pb2-pre-00`).
- `status == "ok"`; usage present (12 input / 18 output tokens).
- Settled actual cost: $0.000408; ledger reservation settled, no unresolved entry.
- Raw provider response persisted at `raw/pb2-pre-00.json`.
- Gate detail: `pass — settled $0.000408, usage=12/18 tokens`.
- Real provider contact verified: dispatch via `worker.RealProvider()`
  (one-shot `/v1/responses`); provider request/response bytes exist in `raw/`.

## Acquisition

- 3 discovery calls (`pb2-d-00`…`pb2-d-02`) + 1 proposal (`pb2-p`), all settled.
- **Acquisition debt D = $0.372212** (settled) + $0.00 (retained) = **$0.372212**.
  Preflight ($0.000408) excluded from D per the frozen rule.
- Proposal delta (verbatim, 178 chars):
  ```delta
  Replace step 5 with:
  5. CHECK. Run the visible tests against the fixed file when executable; otherwise walk them by hand. Cover the edge case from step 2 explicitly.
  ```
- Promotion: parent 12/12, candidate 12/12, 0 regressions, parent cost
  $0.1625, candidate cost $0.1654, **cost ratio 1.0175 ≤ 1.5×** → **ACCEPTED**.
- Accepted successor SHA-256:
  `6f28b65a89b283460ad04e4b6c13defa08c5906c280dc381fef7e2d507b2d6d4`
  (`candidate_method.txt`).

## Operating phase (incomplete)

- **Operating tasks completed: 171 of 450.** Operating calls settled: 341.
- Frozen corpus, frozen operating order, frozen CT/TC schedule, one attempt
  per arm per task — no swaps, no regeneration, no repeats (verified from
  `TASKS.jsonl`: 171 rows, indices 0–170, arm order per schedule).
- Receiver-quality regressions in completed tasks: **0**.
- Partial cumulative curve: A(0) = −$0.371712; A(171) = −$0.381312.
  **No break-even observed** in the completed portion. A(450): not applicable
  (horizon incomplete).
- Frozen null margin: $0.26926 (not reached; no verdict earned on the
  payback question).

## What ended the run

After task 170, two consecutive transport failures were recorded and retained
($0.11 each, per the frozen unresolved rule):

1. `pb2-o-C-0170` — `transport_no_usage: Remote end closed connection without
   response` (task 170 row written with control cost None; delta 0).
2. `pb2-o-T-0171` — `transport_no_usage: <urlopen error [Errno 111]
   Connection refused` (task 171 never completed; no `pb2-o-C-0171` attempt).

The runner process then died: zero Python processes remained, the ledger
stopped growing (verified over 60 s), and **no `RUN_STATUS.json` and no
runner terminal outcome were produced**. The background execution session
record was also lost (`unknown session`), so the runner's stdout/stderr
is unrecoverable from the runtime.

Per the frozen no-rescue rule, no repair and no relaunch occurred under study
ID `payback002` — including for this infrastructure-class failure. The run
directory is preserved exactly as the dead process left it.

## Money (recomputed from preserved ledger evidence only)

- Total settled: **$4.861228** across 370 calls (1 preflight + 28 acquisition
  + 341 operating), of the $18.00 ceiling.
- Retained unresolved exposure: **$0.22** (2 × $0.11 operating reservations).
- No acquisition reservations remain unresolved.

## Terminal verdict: INCOMPLETE

The horizon could not complete (171/450 tasks) because the runner process
died mid-operating-phase after two transport failures. Per the frozen rule
("horizon cannot complete because of stop/budget/infrastructure →
INCOMPLETE"), the scientific standing is **INCOMPLETE** — no verdict earned
on the payback question. This is never rescued and never extended.

## Capture / apparatus limitations

1. **No runner terminal state exists.** `RUN_STATUS.json` was never written;
   `verdict.json` was never written. The INCOMPLETE verdict above is the
   operator's application of the frozen incompleteness rule to preserved
   evidence, not a runner-produced verdict.
2. **Latent accounting defect (not repaired, per no-rescue):**
   `scripts/payback_acct.py:compute` reads `e["retained"]` for unresolved
   ledger entries, but the preserved `econ` ledger writes the key
   `"reservation"`. On any real ledger containing unresolved entries,
   `compute()` raises `KeyError`. It never fired before because no prior
   study ran `compute()` against a real ledger with unresolved entries.
   The final accounting above was therefore recomputed with a separate
   read-only pass applying the frozen formulas directly to the preserved
   ledger; the study code was not modified.
3. The runner's stdout/stderr for the paid run is unrecoverable (lost
   background session). All provider evidence that matters (ledger,
   `TASKS.jsonl`, `raw/`) is preserved on disk and committed here.
4. Task 170's control arm is unresolved (retained $0.11); its delta was
   recorded as 0 per the frozen rule. Task 171 has no row.

## Confirmations

- Zero code repair, zero relaunch, zero threshold movement, zero task
  substitution, zero horizon extension under `payback002`.
- PAYBACK-001 untouched; its standing remains INCOMPLETE_APPARATUS_DEFECT.
- Exactly one paid run was executed under this authorization.
