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

Durable contact ordering: the ContactGate marker is already durable --
the winning worker wrote it at real process start. After the workers
of a chunk join, the coordinator reconciles that marker into Q4
exactly once, BEFORE any observation evidence from the chunk is
committed or adopted. The durable provenance therefore always reads
authorization-before-observation, regardless of the order in which
worker evidence is applied. If no child started, reconciliation finds
no marker and journals nothing. A gate winner that later failed still
made contact: the event is journaled before the failure is handled.

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

## Stage 1 qualifier mechanism (pre-contact; this change)

The Stage 1 environment-qualifier mechanism is built and fixture-tested
only. No production Stage 1 has run: the execution surface is
complete (`run_rsi_006_q5.py` is present and manifest-bound -- see
"Production lock" below), but completeness is not authorization and
no production environment receipt exists.

### Execution manifest

`execution_manifest.json` (schema
`airlock.rsi-006-q5.execution-manifest.v1`) names the complete code
surface allowed to govern Q5 scientific contact: the Q5 ledger/adapter,
`environment_receipt.py`, `stage1/env_qualify.py`, the Q5 Stage 2 runner
`run_rsi_006_q5.py` (present and manifest-bound as a pre-contact
mechanism; Stage 1 unexecuted), and Q4's `stransaction.py`. It pins
the frozen Q3 receipt (`proofs/rsi-006-q3/environment-receipt.json`,
SHA-256 `d89327dc…7515acaa`) by path and hash. Any change to the
manifest or to any listed file invalidates a frozen receipt.

### Environment receipt

`environment_receipt.py` mints schema
`airlock.rsi-006-q5.env-receipt.v1`. A frozen receipt binds: the
execution-manifest SHA-256 and per-file hashes; the selected
interpreter's exact probed identity (Q3's frozen probe: resolved
executable, version, implementation); the dependency lock (exact
installed versions read from the selected interpreter); every governed
repository's pin, checkout SHA, and tree hash; two green deterministic
baseline vectors per repository plus the SHA-256 of each baseline
evidence file; the Q3 receipt path/SHA-256 and complete Q3
`code_hashes` map; the Q4 `stransaction.py` SHA-256; the Q5 receipt
module's own SHA-256; the storage-witness digest with armed and
qualify boot IDs; and the attempt id. Receipts are created atomically
exactly once; an existing receipt is never re-qualified, only
re-verified.

The receipt also binds the exact qualifier implementation that decided
admissibility: `qualifier.source_commit` (the exact HEAD SHA) and
`qualifier.code_hashes`, the SHA-256 of each qualification-critical
file (`stage1/env_qualify.py`, `environment_receipt.py`,
`execution_manifest.json`). This is a separate binding from the
execution-manifest binding, because the two answer different
questions: the qualifier binding says what decided the environment
was admissible; the execution-manifest binding says what is later
allowed to perform scientific contact. The source commit SHA alone is
not sufficient -- a dirty working tree can execute bytes that are not
in that commit -- so production preflight requires every tracked
qualifier-critical file to be byte-identical to its `HEAD` bytes
(`git show HEAD:path` comparison) and fails closed on any dirty or
untracked qualifier file before dependency install, repository
mutation, baseline execution, witness mutation, or receipt creation.

The initial preflight binds the source state once, but qualification
then performs dependency, repository, and baseline work before the
receipt is frozen. Immediately before `freeze_receipt()` -- after
baselines and after all attempt evidence is durable -- the qualifier
re-runs the exact same pure preflight and requires the result to
equal the initial binding exactly, and requires the Airlock git HEAD
at freeze to equal the HEAD captured at the initial preflight. Any
mid-qualification drift fails closed: no receipt is frozen, the
completed attempt evidence is preserved exactly as produced, and a
new Stage 1 attempt is required once the source state is stable. The
receipt's `airlock_commit` comes from the stable binding that
survived both checks, never from an unpaired final `git rev-parse
HEAD`. A qualification never spans two source states.

Q5 reuses Q3's frozen Stage 1 helpers read-only (interpreter probing,
dependency lock, repository verification, baseline launches). Q5 does
**not** call Q3's schema-freezing `qualify_environment()`. Q3's
`run_baseline_checks()` writes both baseline launches of a repository
to the same evidence filename, so run 2 overwrites run 1; Q5 preserves
Q3's two-run admission semantics but writes distinct files
(`<repo>-baseline-run-1.json`, `<repo>-baseline-run-2.json`), each
separately hashed and receipt-bound. Q3 itself is untouched (frozen).

### Storage witness (two-boot protocol)

`--arm-storage` writes the storage witness
(`airlock.rsi-006-q5.storage-witness.v1`) recording the arming boot ID,
a nonce, the arming time, the durable-root path, and the filesystem
identity (`st_dev`). Witness writes are atomic, and the operator may
re-arm before qualification/freeze when a new storage witness is
required; the witness is not create-once. `--qualify-env` refuses
unless: the witness exists, parses, and matches the schema; the
current boot ID differs from the arming boot ID (the root has proven
it survives a boot transition); the witness's durable root equals the
selected root; and the live filesystem identity equals the armed one
(the root was not moved or copied to new storage). Volatile roots
(`/tmp`, `/var/tmp`, `/dev/shm`) are rejected at arming time. The
create-once environment receipt permanently binds the final
successful witness bytes (digest plus armed boot ID, arming time,
durable root, and filesystem identity): after receipt freeze,
changing or re-arming the witness makes verification fail, and
re-verification additionally requires the CURRENT live filesystem
identity of the durable root to equal the bound identity, so copying
or remounting the qualified root onto different storage at the same
pathname fails closed before scientific contact. `st_dev` is not
claimed to be cryptographic or globally stable storage identity; the
claim is only that Q5 detects the tested change in filesystem
identity between arming, qualification, and verification.

Exact threat boundary: the storage witness demonstrates that bytes
written beneath the selected durable root were later observed intact
under a different Linux boot ID, with filesystem/root identity
cross-checks. It detects the tested persistence and migration
failures. It is not cryptographic attestation against an actor with
write access to the durable root. The receipt permanently records the
claimed armed/qualify boot IDs, the arming time, and the witness
digest, so an auditor sees exactly what was asserted. This boundary is
covered by fixture tests (`test_witness_fs_changed_rejected`,
`test_witness_tampered_rejected`, `test_witness_same_boot_rejected`).

### Attempt preservation and locking

Each qualification run takes a nonblocking `flock` on the durable root
(a second simultaneous qualifier is excluded before any mutation) and
works in an append-only attempt directory (`attempts/000001`,
`000002`, ...). A failed attempt's evidence is never overwritten: the
next attempt gets a new directory, and a repair must leave the failed
attempt byte-identical. The selected interpreter invocation path must
live beneath the durable root (e.g. `<root>/venv/bin/python`). The
check is lexical on purpose: it proves the selected *invocation path*
is beneath the root -- it does not prove the symlink *target* is. A
normal venv's `bin/python` typically points at a system interpreter
outside the root, and resolving the link would reject every ordinary
venv. What the receipt binds instead is the *resolved* interpreter
identity (resolved executable, version, implementation -- probed from
the selected interpreter itself, never trusted from the running
process), and the verifier fails closed if that identity changes.
Lexical containment keeps the invocation path inside the durable
unit; the identity binding is what detects a swapped or moved
interpreter. Stage 2 work directories must live beneath the qualified
durable root.

Fixture interpreters expose the parent environment's installed
packages to the fixture venv through a `.pth` file purely as fixture
convenience (so pytest is importable without a network install); this
is not interpreter-isolation evidence. A dedicated negative test
qualifies against a genuinely isolated venv (no `.pth` exposure,
installs disabled) and fails at dependency admission with no baseline
executed and no receipt frozen.

### Production lock

The execution surface is complete: `run_rsi_006_q5.py` is present and
bound by the production execution manifest. Completeness is not
authorization. Production Stage 1 remains unexecuted: no production
environment receipt exists anywhere in the repository, no storage
witness has been armed, and no CI workflow invokes `--arm-storage` or
`--qualify-env` (asserted statically by `stage1/self_check.py` --
executing those modes against a complete manifest would do real
environment work, so the self-check never runs them).

Production qualification (no fixture injection) still fails closed
with `ManifestLockedError` before any dependency install, repository
clone/update, baseline, or receipt work whenever the execution
surface is incomplete: the manifest requires every listed file,
including the runner, and the common preflight raises before either
production mode (`--arm-storage`, `--qualify-env`) can write any
state -- no witness file, no attempt directory, no dependency
operation, and no repo/pool mutation occur. The production CLI
accepts no manifest replacement, no repository-set replacement, no
frozen-pin weakening, and no boot-ID override. Fixture manifests,
fixture pins, and synthetic boot IDs enter only through internal
function parameters, never through CLI flags. The manifest note
records the boundary explicitly: the surface is complete, and
scientific contact requires a separately authorized invocation
against a verified receipt -- which has not been given.

### Claim boundary (Stage 1 mechanism; pre-contact)

Q5 may additionally claim only:

11. in tested cases, the production qualifier refuses with
    `ManifestLockedError` before any environment mutation when the
    execution surface is incomplete (a required manifest file,
    including the runner, missing), through the common preflight;
12. in tested cases, a missing/malformed/same-boot/moved-storage
    witness is rejected before any environment mutation;
13. in tested cases, an interpreter invocation path outside the
    durable root is rejected before any environment mutation, and the
    frozen receipt records the resolved interpreter identity used;
14. in tested cases, a failed qualification attempt preserves its
    evidence byte-identical while a later attempt succeeds and
    freezes;
15. in tested cases, a frozen receipt re-verifies against the live
    environment and detects interpreter drift, dependency drift,
    repository drift, manifest drift, witness drift, and Stage 2
    work-directory escape;
16. the Stage 1 self-check (`stage1/self_check.py`) passes: Q3
    byte-identical to its frozen receipt, Q4 unchanged from merged
    PR #161, Q5 ledger unchanged from the merged HEAD with the Q5
    adapter (changed by design in the pre-contact runner mechanism)
    bound by the production manifest, production manifest carrying
    the required execution surface with the runner present and
    listed, no production Stage 1 run (no receipt, no CI invocation
    of arming or qualification), and Stage 1 code importing no
    scientific substrate;
17. the dedicated `rsi-006-q5-stage1-gate` CI workflow runs the
    self-check and the 51 fixture contract tests on Stage 1
    mechanism changes only, and spec changes trigger that gate;
18. in tested cases, a modified qualification-critical file with
    unchanged declared source identity is refused before any
    environment mutation (both the fixture byte-comparison path and
    the production `git show HEAD:path` path), and the frozen receipt
    binds the exact qualifier bytes that decided admissibility;
19. in tested cases, both production entry points (`--arm-storage`
    and `--qualify-env`) refuse with zero mutation when the execution
    surface is incomplete, through the common preflight; with the
    surface complete, production Stage 1 remains unexecuted -- no
    receipt exists and no CI workflow invokes either entry point;
20. in tested cases, a genuinely isolated venv (no `.pth`, installs
    disabled) fails at dependency admission with no baseline executed
    and no receipt frozen;
21. in tested cases, source drift after the initial preflight (a
    manifest-governed file mutated mid-qualification, or the Airlock
    HEAD moving with governed bytes unchanged) fails closed at the
    final pre-freeze preflight: no receipt is frozen, the completed
    attempt evidence is preserved exactly as produced, and a new
    attempt is required once the source state is stable;
22. in tested cases, receipt re-verification parses and cross-checks
    the bound storage witness and rejects a changed CURRENT live
    filesystem identity for the durable root, so a copy or remount of
    the qualified root onto different storage at the same pathname
    fails closed before scientific contact.

Q5 does **not** claim: a production Stage 1 run, substrate
qualification, scientific success, validation against real
repositories or real mutants, authorization for Stage 1, tamper-proof
witnessing against a malicious storage owner (see the threat boundary
above), or any change to Q3's terminal outcome.

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
7. in tested cases, the Q4 contact entry is journaled before every
   observation/adoption entry from the same batch (durable
   authorization-before-observation), even when the gate winner is
   not first in coordinator apply order;
8. in tested cases, a real coordinator crash followed by a fresh-process
   resume opens the transaction exactly once (exactly one `restart`
   entry), skips committed observations, and never replays uncertain
   ones;
9. in tested cases, restart skips committed observations and never
   replays uncertain ones;
10. Q3 scientific constants and Q3/Q4 files remain unchanged per
   `self_check.py`.

### Runner mechanism (pre-contact; this change)

`run_rsi_006_q5.py` is the Q5 Stage 2 scientific runner: it executes
the Q3 mutation-discovery protocol against verified pool checkouts
under a Q4 scientific transaction, journaling one observation per
mutant with the ContactGate contact exactly once, sealing discovery
mutant sets per Q3's deterministic ordering, committing a single
confirmation nonce, running det-reruns, and binding the terminal
verdict report to the Q4 verdict entry by digest. Q5's adapter
completion-builder seam carries the Q3 canonical record: the runner
hands completed-process evidence to Q3's frozen completion builder,
so committed observation records are Q3-canonical by construction --
the timeout/kill/collection-error semantics Q3 proved are preserved,
not reimplemented. The runner executes fresh work in lifecycle
order: verify receipt, static feasibility guard, pre-contact report
on guard failure (no transaction, no nonce, no contact), then --
under the whole-lifetime nonblocking coordinator lock -- reverify
the receipt, exactly one transaction `begin()`/`open()`, immediate
`reconcile_contact()` on resume, then mutant generation and phase
execution. The runner is present, manifest-bound, fixture-tested --
and unexecuted against anything real.

Spawn failure is a Q3 parity case, not a generic retry. Frozen Q3
treats a `Popen` `OSError` as a completed canonical observation --
`outcomes={}`, `collection_error=True`, `timeout=False` (therefore a
kill), launch disposition `launch_spawn_failed`, no child, no contact
hook -- so the runner's scientific path does the same: when the
runner's `spawn_failure_builder` is active, a `Popen` `OSError`
becomes the exact Q3 `launch_spawn_failed` canonical record, with no
`started` record and no ContactGate call. The `spawn_failed` proof,
the canonical outcome bytes, and the completion are persisted
durably and the observation is committed through Q4 normally; the
observation names no physical execution, so its report `exec_nonce`
is null. On resume, `spawn_failed` + verified completion is
recoverable/adoptable (zero second `Popen`); `spawn_failed` without
verified completion fails closed (`UncertainExecution`) -- the spawn
failure is already Q3's scored observation and is never retried. The
generic adapter path (no scientific builders) is unchanged:
`spawn_failed` stays recorded and retryable.

Q5 may additionally claim only:

11. in tested cases, the runner's Q3 completion path produces
    canonical observation records byte-identical to frozen Q3
    (survivor, killed mutant, missing/extra tests, timeout,
    collection error, unparseable JUnit, raw corrupt JUnit retained
    in the launch sidecar);
12. in tested cases, a builder exception propagates without a
    fallback envelope, and a timeout with no completion builder
    raises `UncertainExecution` (no rerun);
13. in tested cases, an uninterrupted fixture full run reaches a
    terminal verdict with exactly one contact, journaled before all
    observation commits, deterministic discovery seals, a single
    journaled confirmation nonce, 100% det-rerun agreement, no
    duplicate execution nonces, and a Q4 verdict entry bound to the
    report digest;
14. in tested cases, crashes at each recoverable point (after first
    contact, after discovery, after discovery seal, after the
    confirmation nonce, mid-confirmation, after det-rerun, in the
    verdict gap) resume to the same terminal scientific evaluation
    as the uninterrupted run -- same seals, same nonce, same
    canonical discovery records, exactly one contact, committed
    observations skipped, recoverable completed observations adopted
    with zero second physical execution;
15. in tested cases, a crash after a real child start but before its
    completion is durable fails closed on resume
    (`UncertainExecution`): no rerun, no verdict;
16. in tested cases, a static-guard failure writes only a pre-contact
    report: no transaction, no execution nonce, no contact;
17. in tested cases, a forced `Popen` `OSError` through the runner's
    scientific path produces the exact Q3 `launch_spawn_failed`
    canonical record (byte-identical canonical bytes, zero contact,
    zero child execution), commits normally, reports a null
    `exec_nonce`, and -- after a crash between its durable completion
    and the Q4 commit -- is adopted on resume with zero second
    `Popen`; a `spawn_failed` without verified completion fails
    closed instead of retrying.

Q5 does **not** claim: a production Stage 1 run, substrate
qualification, scientific success, validation against real
repositories or real mutants, authorization for Stage 1 or for any
production runner invocation, tamper-proof witnessing against a
malicious storage owner (see the threat boundary above), or any
change to Q3's terminal outcome.

Q5 does **not** claim: substrate qualification, scientific success,
validation against real repositories or real mutants, authorization
for Stage 1, or any change to Q3's terminal outcome.
