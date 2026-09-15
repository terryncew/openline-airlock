# Frozen Q5 spec language prescribing the observed fail-closed behavior

Source: `experiments/rsi-006-q5-durable-substrate-qualification/RSI_006_Q5_SPEC.md`
at Airlock HEAD `c82f0242e6556bbc8d920291f444090b526adeee`
(SHA-256 `7387fa1acd485ff13885df2a267ec1a1a941d958e809b5167451c418c991cc33`).

Quoted verbatim, with line numbers.

## Resume classification per observation (lines 74-84)

> - no prepared record: the work may run (attempt 1);
> - prepared + a matching definitive `spawn_failed` (same attempt): a
>   genuine first attempt remains allowed -- no child was created;
> - started + verified completion: recover/adopt the exact first result
>   via `adopt_orphan_observation` -- zero second execution;
> - started without verified completion: fail closed with
>   `UncertainExecution` -- never rerun;
> - prepared without a definitive `spawn_failed`: fail closed with
>   `UncertainExecution` -- absence of a `started` record is NOT proof
>   that the child never existed (the coordinator may have died between
>   the real spawn and the durable `started` write);
> - already in the transaction journal: skip, never re-execute.

The observed case is the fourth bullet: `cachetools-A-0049` had a
durable `started` record (child pid 34170) and no verified durable
completion. The prescribed behavior is `UncertainExecution`, never
rerun.

## `ScientificTransaction.open()` is resume-only (lines 118-121)

> `ScientificTransaction.open()` is a crash/resume primitive: it appends
> a durable `restart` entry. The coordinator therefore calls it at most
> once per process lifetime (on startup, when resuming an existing
> journal) and never again during ordinary operation -- calling it
> repeatedly under contention would mint false restart provenance even

The observed resume appended exactly one `restart` entry (journal
seq 195) and no second `tx_begin`.

## Claim 8: resume opens exactly once, skips committed, never replays uncertain (lines 391-394)

> 8. in tested cases, a real coordinator crash followed by a fresh-process
>    resume opens the transaction exactly once (exactly one `restart`
>    entry), skips committed observations, and never replays uncertain
>    ones;

Observed: exactly one `restart`, all 192 committed observations
skipped with zero re-execution, the single uncertain observation
(`cachetools-A-0049`) not replayed.

## Claim 15: crash after real child start fails closed with no verdict (lines 464-466)

> 15. in tested cases, a crash after a real child start but before its
>     completion is durable fails closed on resume
>     (`UncertainExecution`): no rerun, no verdict;

Observed: the original process crashed after the real child start of
`cachetools-A-0049` (durable `started` record, ts 1789508822.2992506)
but before its completion was durably recoverable. On resume the
runner raised `UncertainExecution`, performed no rerun, and produced
no verdict. This is the prescribed outcome, not a malfunction.
