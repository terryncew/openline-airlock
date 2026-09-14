# AUTORESEARCH-LIVE-003 — confirmed improvement search

LIVE-002 answered the governance question positively but the research question negatively: two real `train.py` proposals were measured by the receiver, both were worse than the fresh baseline, both were rejected, and the accepted state did not move. That result does **not** establish that the generator is inadequate. It establishes only that two attempts did not produce a surviving improvement.

LIVE-003 changes one scientific variable: **search depth**. The same self-declared Prince / Muse Spark 1.3 researcher may receive at most 12 bounded proposal calls against the same pinned Karpathy `autoresearch` substrate. The upstream pin, fixed five-minute objective, fixed seed policy, protected paths, minimum-gain rule, and Airlock receiver boundary remain unchanged.

The new protection is confirmation-before-promotion. A discovery candidate that clears the objective once is only an apparent winner. Airlock leaves the accepted ref unchanged, invokes a fresh receiver measurement for the exact same candidate from the same still-unpromoted base, and permits promotion only if that confirmation also clears the frozen rule. The confirmation receipt—not the discovery receipt—is the only receipt authorized to advance accepted state.

If the first apparent winner fails confirmation, the experiment stops with `APPARENT_WIN_NOT_CONFIRMED`. It does not keep searching for another apparent winner. That rule is deliberately strict: repeated post-selection attempts would create additional chances to promote noise.

## What a positive result earns

`CONFIRMED_LIVE_IMPROVEMENT_PROMOTED` earns one bounded result: a real external research generator produced **A**, A cleared the receiver objective twice under the same fixed-seed protocol, and the exact confirmed candidate was promoted while the researcher remained unable to change the evaluator or promotion rule.

It does **not** earn cumulative optimization, recursive improvement, repeatability, statistical superiority, or hostile-process isolation.

The next experiment is conditional. Only after A exists do we test exact inheritance of A and search for a separately confirmed B. A → inherited A → B would establish cumulative governed optimization. The stronger recursive-improvement claim requires something more: an inherited accepted change must improve the process that generates subsequent improvements, not merely the training code being optimized.

## Budget

The preregistration counts the full experiment rather than calling twelve five-minute evaluations “one hour.” The hard ceilings are 12 researcher calls, 12 discovery evaluations, one confirmation, one fresh baseline, 14 total receiver measurements, 4,200 seconds of training budget, 150 minutes of pod wall time from bootstrap start, and $5.00 estimated paid GPU spend at the recorded hourly rate. Setup and handoff time consume the wall/spend budget too.

Because the pinned upstream uses seed 42, the confirmation is an operational repeat under the same fixed-seed protocol. It is not represented as an independent-seed statistical replication.

## Execution boundary

The live researcher may change only `train.py`. The existing `AUTORESEARCH-GATE-001` receiver overlay remains the authority for measurement and exact promotion. LIVE-003 adds an outer state machine that prevents a discovery ACCEPT from reaching `promote` until the exact candidate earns a second receiver ACCEPT.

The pure protocol state machine is exercised in CI without GPU spend. The live driver additionally snapshots every protected tracked file except `train.py`, requires clean state around receiver calls, counts researcher contacts before they occur, and records receiver measurement attempts before invoking them so failed attempts cannot disappear from the budget.
