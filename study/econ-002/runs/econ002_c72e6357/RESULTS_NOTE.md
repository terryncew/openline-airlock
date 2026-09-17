# ECON-002 — Results freeze note (2026-09-16)

Run executed 2026-09-16 ~15:27–15:44 PDT under study ID
`econ002_c72e6357`, code frozen at remote commit
`8d1d2131f75be12fe02b664b12875b1225998d00` (branch `study/econ-002`),
with the operator's explicit `--authorize-paid-contact` authorization.

## Outcome

Preflight: PASS — exactly 1 request, usage present, settled $0.000184
under the frozen pricing table, within the $0.11 reservation.

All six frozen candidates REJECTED by the paired-12 / 20% receiver rule:

| candidate | vp | vc | parent $ | candidate $ | ratio | regressions | decision |
|---|---|---|---|---|---|---|---|
| D1 (delete CHECK) | 12 | 12 | 0.1543 | 0.1604 | 1.0397 | 0 | reject |
| D2 (delete REPRODUCE) | 12 | 12 | 0.1648 | 0.1567 | 0.9506 | 0 | reject |
| D3 (merge) | 12 | 12 | 0.1703 | 0.1603 | 0.9412 | 0 | reject |
| D4 (wording) | 12 | 12 | 0.1574 | 0.1530 | 0.9720 | 0 | reject |
| S1 (model proposal 1) | 12 | 12 | 0.1601 | 0.1462 | 0.9135 | 0 | reject |
| S2 (model proposal 2) | 12 | 12 | 0.1529 | 0.1529 | 0.9872 | 0 | reject |

Accepted: none.

Earned negative claim (frozen wording): "None of the frozen
candidate-generation strategies produced a successor at least 20%
cheaper than the paired baseline while preserving 12/12 verified
success on the frozen fresh-task evaluation."

Observed, within the claim boundary: every candidate preserved 12/12
verified success; the best observed saving was S1 at 8.6%, D1 (delete
CHECK) was 4.0% MORE expensive than the parent. No inference beyond the
frozen claim is made.

## Money

Scientific ledger: settled $1.990608, unresolved retained $0.00,
152/152 calls settled. Preflight ledger: settled $0.000184.
Combined $1.990792 of the $20.00 physical ceiling.

## Capture limitation (recorded, not repaired)

The runner reused the literal tag "S2d"/"S2p" for both Stage-2
candidates' discovery and proposal invocation IDs. S2's discovery and
proposal raw files therefore overwrote S1's (`S2d_00..02.json`,
`S2p.json`). The S1 discovery/proposal raw response bytes are lost.
What is preserved: all 152 ledger settle entries (full money
accounting), all 144 promotion raw files including request bodies
(which carry the candidate method text), and S2's discovery/proposal
raw files. The gate verdicts depend only on the promotion attempts,
which are fully preserved. Per the standing evidence rule, the gap is
recorded as a capture limitation; the missing bytes are not
reconstructed. The runner defect is NOT repaired under this study ID.
