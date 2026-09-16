# ECON-002 closeout — NO_LARGE_SUCCESSOR

Terminal evidence-freeze record for study `econ002_c72e6357`.
The full study (preregistration, corpus, runner, tests, run artifacts)
lives on branch `study/econ-002`; this note freezes the outcome only.

## Identity

- Study: ECON-002 — minimum successor falsifier
- Authorized code SHA: `8d1d2131f75be12fe02b664b12875b1225998d00`
- Results SHA: `916895b6567a0645f722b78427665e9d18c5f48c`
- Standing: `ECON-002_CLOSED_NO_LARGE_SUCCESSOR`

## Preregistered question

"Can any frozen candidate-generation strategy produce one successor
method that is at least 20% cheaper than the baseline while preserving
12/12 verified success on fresh paired tasks?"

## Receiver rule (frozen)

Same 12 fresh task IDs parent and candidate; one attempt each per
task; 12/12 verified success both arms; zero per-task regressions;
candidate settled total ≤ 80% of parent settled total; unsettled calls
contribute the full reservation (fail-closed).

## Outcome

Preflight passed (1 request, settled $0.000184). 152/152 scientific
calls settled, zero unresolved; scientific spend $1.990608 of the
$20.00 ceiling.

All six candidates rejected. Every candidate preserved 12/12 verified
success with zero regressions:

- D1 delete CHECK: ratio 1.0397
- D2 delete REPRODUCE: ratio 0.9506
- D3 merge REPRODUCE+DIAGNOSE: ratio 0.9412
- D4 wording compression: ratio 0.9720
- S1 cost-aware model proposal: ratio 0.9135 (best observed)
- S2 cost-aware model proposal: ratio 0.9872

Accepted successor: NONE.

## Earned claim

"None of the frozen candidate-generation strategies produced a
successor at least 20% cheaper than the paired baseline while
preserving 12/12 verified success on the frozen fresh-task evaluation."

## Standing

Within the frozen saturated regime, the tested deterministic and
cost-aware model candidate-generation strategies did not produce an
accepted successor with ≥20% lower paired execution cost at preserved
12/12 verified success. The bottleneck moved from an obvious
prompt-specification defect (ECON-001) to a substantive empirical
question about where meaningful efficiency gains actually come from.

No rerun, no rescue, no relaunch under the same study ID. No ECON-003
or successor-search follow-up is authorized by this freeze.

## Capture limitation

The runner reused `S2d`/`S2p` invocation-ID tags for both Stage-2
candidates, overwriting S1's discovery/proposal raw files. Recorded as
a capture limitation; all promotion evidence and all 152 ledger
settlements are preserved; promotion verdicts unaffected.
