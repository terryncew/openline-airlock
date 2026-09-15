# RSI-006-Q5: durable substrate qualification (pre-contact)

## Lineage

RSI-006-Q3 froze `EXECUTION FAILURE AFTER CONTACT`: the single
authorized Stage 2 invocation was killed by a VM reboot during
confirmation, and the volatile `/tmp` work directory destroyed the
ability to reach or preserve a verdict. Q3 stays frozen; no rerun,
rescue, repair, reconstruction, or reinterpretation is allowed.

RSI-006-Q4 (merged as PR #161) added the missing mechanism layer: a
durable, receiver-owned scientific-transaction journal in which
completed observations are either recovered from independently durable,
transaction-bound evidence or continuation fails closed, and continuity
is bound to the same authorization instance, not merely the same
environment.

RSI-006-Q5 is the pre-contact successor that integrates the two: Q3's
frozen scientific machinery wrapped in Q4's durable transaction layer,
with a receiver-owned durable execution ledger around the real
observation path. Q5 builds only the adapter, self-checks, and local
fixture/integration tests. No Stage 1, no real repositories, no real
mutants, no scientific contact.

## Frozen Q3 scientific constants (unchanged, bound by self_check.py)

- Seeds: `RSI-006-Q-discovery-A`, `RSI-006-Q-discovery-B`
- Budgets (A, B, determinism, confirmation): more-itertools
  (72, 72, 10, 20); cachetools (102, 102, 20, 60); boltons
  (70, 70, 20, 60); pluggy (51, 51, 20, 60)
- Operators: CMP_SWAP, ARITH_SWAP, BOOL_FLIP, NUM_DELTA, LOGIC_SWAP,
  NOT_DROP
- Pins: more-itertools `b2f3aff7633057d234ec9186c18a53f4df306d08`;
  cachetools `4500e3d04288738d25acbb4973eb3c3e1bf41db9`; boltons
  `961dcff3f42e73b245aef65e377fe82763b257bb`; pluggy
  `0a4974175aa2d873f401345b151297af2e74c851`
- Thresholds: Q-DET 1.0; Q-SIG [0.05, 0.95]; Q-STAB per-operator ≤0.25,
  Spearman ≥0.7, ≥3 operators with ≥10 observations per half; Q-FRESH
  per-operator ≤0.30, overall ≤0.15; collection-error rate <0.10;
  Q-INTACT unchanged. Known BOOL_FLIP integer 0/1 behavior unchanged.
- Q3 implementation files remain byte-identical to
  `proofs/rsi-006-q3/environment-receipt.json`; Q4's
  `stransaction.py` remains byte-identical to the PR #161 merge.
  Q5 modifies neither, nor `proofs/`.

## The receiver-owned durable execution ledger

New in Q5 (`execution_ledger.py`), sitting around the real observation
path and owned by the receiver -- never by the worker subprocess. The
pre-spawn `start` record of the first draft conflated reserved work
with work that actually crossed the process-start boundary; Q3
correctly treats a `Popen` failure as zero scientific contact, so Q5
preserves that distinction. The execution state is:

`prepared → started | spawn_failed`

1. **Before the spawn is attempted**, atomically persist a `prepared`
   record bound to txid, observation ID, phase, attempt number,
   environment receipt SHA-256, and code hashes. Reservation only: it
   proves nothing about whether a child process was ever created.
2. **Only from Q3's post-`Popen` callback**, after the child process
   actually exists, atomically persist a `started` record binding the
   child PID and exec_nonce -- this specific physical execution.
3. **If `Popen` raises and no child was created**, atomically persist a
   `spawn_failed` record: proof of zero execution and zero contact.
4. **After the subprocess completes** and the canonical outcome bytes
   are durably persisted, atomically persist completion evidence
   binding the outcome digest.
5. **Only then** commit/adopt into `ScientificTransaction`.

Resume classification per observation:

- no prepared record: the work may run (attempt 1);
- prepared + a matching definitive `spawn_failed` (same attempt): a
  genuine first attempt remains allowed -- no child was created;
- started + verified completion: recover/adopt the exact first result
  via `adopt_orphan_observation` -- zero second execution;
- started without verified completion: fail closed with
  `UncertainExecution` -- never rerun;
- prepared without a definitive `spawn_failed`: fail closed with
  `UncertainExecution` -- absence of a `started` record is NOT proof
  that the child never existed (the coordinator may have died between
  the real spawn and the durable `started` write);
- already in the transaction journal: skip, never re-execute.

All ledger writes are atomic (tmp + fsync + rename + directory fsync):
a crash leaves a record fully present or fully absent, never torn.

## Contact preservation and the single-writer coordinator

Q3's `ContactGate` is imported read-only and used verbatim at the same
boundary -- immediately after the observation subprocess has actually
started. Its `O_CREAT|O_EXCL` arbitration still decides the single
winner under genuine concurrency; the adapter additionally journals
the contact event into the transaction. If a crash lands between the
gate win and the journal append, `reconcile_contact` re-journals the
winner's marker on the next start: exactly one authorization/contact
transition, never two.

The coordinator model matches Q3: one coordinator process dispatches
concurrent child observations and owns the live `ScientificTransaction`
for its whole lifetime. Worker threads may race at actual
process-start/contact (the gate); they return execution/contact
evidence to the coordinator and never mutate the Q4 journal. The
coordinator serializes all journal mutations through its single live
instance.

`ScientificTransaction.open()` is a crash/resume primitive: it appends
a durable `restart` entry. The coordinator therefore calls it at most
once per process lifetime (on startup, when resuming an existing
journal) and never again during ordinary operation -- calling it
repeatedly under contention would mint false restart provenance even
though the journal is intact. A coordinator-exclusion `flock` is held
for the coordinator's whole lifetime. Acquisition is non-blocking: a
second coordinator process started while one is alive fails closed
with `CoordinatorExclusionError` before it can open or mutate the
journal, write any ledger record, or touch contact state (a blocking
wait would hang instead of failing closed, and the waiter would
eventually mint a restart entry for a non-crash). The OS releases the
lock on real process death. After an actual coordinator crash, the
successor process opens exactly once: the journal gains exactly one
`restart` entry for the one genuine resume.

## Stage 1 receipt (future, not this change)

A future authorized Q5 Stage 1 must mint a **new** environment receipt
(schema `airlock.rsi-006-q5.env-receipt.v1`) binding: the Q5
integration code hashes, the merged Q4 transaction code hash, the
frozen Q3 substrate code hashes, the interpreter/dependency lock, the
repository pins/trees, and the baseline vectors. The Q3 receipt must
**not** be reused as Q5's scientific receipt: it names a different
codebase. The adapter takes the receipt SHA-256 as a parameter; the
fixture tests use a fixture receipt, which is test-only.

## Claim boundary (pre-contact)

Q5 may claim only:

1. the adapter, ledger, self-checks, and fixture/integration tests
   exist and pass;
2. in tested cases, a deterministic `Popen` failure records a durable
   `spawn_failed` with zero Q3 contact and zero Q4 contact, and a
   later valid first launch is allowed;
3. in tested cases, a crash after `prepared` but before the durable
   `started` record fails closed with zero second execution -- absence
   of `started` is not proof the child never existed;
4. in tested cases, a crash after `started` but before completion
   evidence fails closed with zero second execution;
5. in tested cases, a crash after completed durable evidence but before
   transaction commit adopts the exact first result with zero second
   execution;
6. in tested cases, simultaneous child starts under one coordinator
   produce exactly one contact winner, exactly one Q4 contact event,
   a valid journal, and zero `restart` entries;
7. in tested cases, a real coordinator crash followed by a fresh-process
   resume opens the transaction exactly once (exactly one `restart`
   entry), skips committed observations, and never replays uncertain
   ones;
8. in tested cases, restart skips committed observations and never
   replays uncertain ones;
9. Q3 scientific constants and Q3/Q4 files remain unchanged per
   `self_check.py`.

Q5 does **not** claim: substrate qualification, scientific success,
validation against real repositories or real mutants, authorization
for Stage 1, or any change to Q3's terminal outcome.
