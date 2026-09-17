# PAYBACK-003 — INCOMPLETE (terminal freeze note)

Study `payback003`, branch `study/payback-003`.
Execution SHA (exact): `e2657c0d8d915ab385f3d257fb4a0ea5f9423ca6`.
Terminal evidence commit on `study/payback-003`: `73f011a09828eebae7e6330f5594c99d3064cfa3`
(run dir committed unmodified, as produced by the authorized run).
Preregistered PAYBACK-002 closeout PR #173 merged as
`aac08aed03f052da04c66e0e1f5b6872dfdf649a` (2026-09-17T00:38:00Z);
PAYBACK-002 remains permanently INCOMPLETE and untouched.

## Terminal verdict

**INCOMPLETE** — the 450-task operating horizon could not complete.
The frozen accounting module (`payback_acct.compute`, unchanged since the
pre-contact freeze) reads this directly from the preserved evidence:
`H_completed = 141 < 450`, no `RUN_STATUS.json`, missing tasks 141–449.
This is an operator application of the frozen rule to frozen evidence,
not a runner-produced verdict. No rescue, no relaunch, no PAYBACK-004.

## What happened

- Preflight: CLEAN PASS — `pb3-pre-00`, settled $0.000408, usage 12/18
  tokens (same clean signature as pb2's preflight). The authorized
  invocation then proceeded into scientific contact per the
  if-and-only-if condition.
- Scientific contact began **2026-09-16 17:43:57 PDT** with the first
  acquisition provider dispatch `pb3-d-00`. No-rescue bound from that
  moment; it held.
- Acquisition (all on the fresh pb3 corpus, disjoint from prior ECON
  scientific instances and from pb2-contacted tasks):
  - Discovery: 3 tasks (`pb3-d-00..02`), fresh `pb3-logi-*` tasks.
  - Proposal: fresh provider call `pb3-p`; the returned delta replaced
    method step 5 with "CHECK: walk the visible tests against the fixed
    file by hand; cover the edge case from step 2 explicitly."
  - Promotion: 12/12 vs 12/12, 0 regressions, cost ratio 0.9801
    (threshold 1.5) → successor ACCEPTED.
  - Accepted successor SHA-256:
    `6f28b65a89b283460ad04e4b6c13defa08c5906c280dc381fef7e2d507b2d6d4`
    (sha256 of `candidate_method.txt`, verified). Byte-identical to the
    PAYBACK-002 successor delta: legitimate — pb3 earned it independently
    through its own discovery/proposal/promotion on the fresh corpus
    (acquisition debt differs: $0.353276 vs $0.372212). The proposal
    procedure is deterministic given the same parent method and prompt;
    the provider returned the same text. Nothing from pb2 was imported.
  - Acquisition debt D = **$0.353276** (all settled, $0 retained).
- Operating: 141/450 tasks completed, 311 calls settled, **0 regressions**,
  0 void tasks. Curve: A(0) = −$0.353316, A(141) = −$0.348196,
  max A(t) = −$0.325516 at t=43. **No break-even** in the partial curve.
  A(450): not applicable (horizon incomplete).

## The terminal event

At ~2026-09-16 18:28:30 PDT (task 141, ~44.6 minutes after contact):

1. `pb3-o-C-0141`: transport failure — "Remote end closed connection
   without response" → recorded unresolved, $0.11 reservation retained.
2. `pb3-o-T-0141`: transport failure — `<urlopen error [Errno 111]
   Connection refused>` → recorded unresolved, $0.11 reservation retained.
   The preserved ECON worker classifies ECONNREFUSED as demonstrably
   pre-dispatch (`_is_infra_failure`) and raises `InfrastructureHalt`
   per its documented contract ("Callers must let it propagate:
   run_study ends the study immediately with no further provider
   contact").
3. The runner's `_attempt` catches only `(OSError,
   http.client.HTTPException)`; `InfrastructureHalt` is a plain
   `Exception` subclass, so it propagated uncaught through
   `operating → paid → main` and the runner died (exit 1; full
   traceback preserved in `console.err`). No `RUN_STATUS.json` was
   written.

The transport circuit breaker (repair #3, N=3 consecutive) did not trip:
the first failure was counted (streak=1), but the second failure never
reached the breaker as a countable event — the worker raised
`InfrastructureHalt` from inside `invoke()` instead of returning a
transport-failure result. Same terminal state, different mechanism.
(The pb2 runner died with the identical signature: remote-closed then
ECONNREFUSED, no RUN_STATUS.json — retrospective reading: pb2's death
was this same worker-level InfrastructureHalt path, not the breaker.)

## Supervisor record

The supervisor (repair #2) captured the runner's death durably:
`console.out`/`console.err` from process start, initial
`SUPERVISION.json` (runner PID, start time, command), heartbeats to
18:28:24 PDT. The supervisor itself did not survive to write its
terminal classification record — `SUPERVISION.json` remains in its
initial (unfinalized) state and no `INFRA_TERMINAL.json` exists.
The supervisor's own death cause is not evidenced. Recorded here as an
apparatus limitation, not repaired (post-contact repair is forbidden).

## Money

- Settled: **$4.592836** of the $18.00 ceiling, across 311 calls.
- Retained unresolved: **$0.22** (2 × $0.11: `pb3-o-C-0141`,
  `pb3-o-T-0141`). Both are transport failures before dispatch with
  zero usage; reservations are retained unless later evidence
  mechanically proves non-dispatch/non-charge.
- Preflight $0.000408 is outside the scientific ledger (gate cost).

## Limitations

- The 141-task partial curve is visible evidence, not a verdict: it does
  not establish that payback would or would not have occurred by task
  450, and it must not be used to interpret or modify any future study.
- Two runner-level mechanisms for infrastructure termination now exist
  in the frozen apparatus (worker `InfrastructureHalt` vs. transport
  circuit breaker); their interaction was observed, not designed. This
  is frozen as evidence, not repaired.
- The supervisor's missing terminal record is an unrepaired apparatus
  gap; the runner's own `console.err` traceback is the primary evidence
  of the terminal event.
- No claim is made about provider behavior beyond the recorded calls.

## Confirmation

Zero post-contact rescue: after 2026-09-16 17:43:57 PDT there was no
repair, no relaunch, no task replacement, no seed swap, no candidate
substitution, no threshold movement, no horizon extension, no
accounting-formula change, no transport-policy change. The run was
frozen as it died; the evidence was committed byte-identical.
PAYBACK-002 was not touched, and no PAYBACK-004 was created.

Related: PAYBACK-001 `INCOMPLETE_APPARATUS_DEFECT` (unchanged),
PAYBACK-002 `INCOMPLETE` (unchanged), ECON-002 closed
`ECON-002_CLOSED_NO_LARGE_SUCCESSOR` (unchanged).
