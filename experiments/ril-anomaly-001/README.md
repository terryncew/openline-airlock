# RIL-ANOMALY-001 — Interview the Failure / Earned Lesson Ratchet

The ranking line is closed. RIL-RANK-EXEC-001 showed that a frozen inherited ranking can improve a mechanical receiver-executed search. RIL-RANK-LIVE-002 then showed that the presentation-order treatment had no observed effect on Prince: both fresh sessions reconstructed the same exact four-candidate order on all 16 tasks, producing 1/16 confirmed improvements and 63 receiver evaluations in each arm.

That null does not establish that every live agent erases inherited signal, and it does not test the larger research claim. RIL-ANOMALY-001 asks a different question:

**Can a researcher inherit an unresolved failure, investigate where the current explanation stops working, design a discriminating experiment, and earn new search lessons that produce more independently confirmed improvements than ordinary search under the same bounded resources?**

## Design

Two fresh Muse Spark 1.3 / Prince research trajectories start from the same frozen LIVE-002 failure and the same empty accepted-lesson state. A receiver-private mapping assigns one trajectory to `anomaly_interview` and the other to `ordinary_search`.

Each arm has four research rounds. Both receive the same researcher substrate, allowed tools, per-round resource ceilings, receiver evaluation authority, and promotion rule. The only methodological treatment is the research protocol.

The anomaly arm must identify at least two explanations consistent with the failure, state the observation that would distinguish them, and propose the smallest bounded experiment before proposing a mechanism change. The control arm uses ordinary search and is not required to follow that sequence.

The researcher chooses the experiment. The receiver executes and evaluates it. Proposal quality is never scored by rhetoric or an LLM judge.

## The ratchet

Each arm owns a receiver-maintained `accepted_head`, modeled on the successor-promotion ratchet used in OpenLine swarm improvement.

Every proposal names the exact `accepted_head` it starts from. A receiver outcome is bound to that proposal and to a receiver evidence artifact. Only:

`protocol valid + independently confirmed improvement + no regression`

produces `PROMOTE` and advances the head. `REJECT` and `QUARANTINE` leave the accepted head unchanged. Their observations remain visible as history, but their candidate lessons do not become accepted lessons.

A promoted lesson is therefore evidence-bound memory, not a declaration of general truth. Its scope and invalidation conditions travel with it.

## Resource parity

Per arm: four research rounds, at most 16 receiver evaluations / $1.50 external compute / 20 minutes receiver execution per round. Muse subscription dollars are not allocated because historical per-session marginal cost is not observable. Any RunPod or other external compute used by the receiver must be counted inside the frozen external-compute ceiling.

## Primary metric

Count receiver-confirmed `PROMOTE` decisions within the fixed four-round arm budget.

Passing threshold:

`anomaly_interview promotions - ordinary_search promotions >= 2`

The opposite difference of at least two is an ordinary-search advantage. Anything between is no observed advantage. Protocol or budget failure makes the run inconclusive.

## Claim boundary

A pass would be a single-run process-level result: anomaly-first investigation produced more receiver-confirmed research improvements under this frozen matched-start protocol and ratchet. It would not earn recursive self-improvement, Level 4 autonomy, general scientific judgment, repeatability, production value, economic payback, or hostile-process isolation.

The ratchet is the important inheritance boundary: the researcher may generate explanations and lessons; only receiver evidence decides what survives into the next round.
