# RSI-006-Q4 — Durable Scientific Transaction (pre-contact successor to Q3)

**Status: PRE-CONTACT.** No scientific contact is authorized under this
ID. No Stage 1 against the four real repositories, no real mutants, no
mutant-observation subprocesses. This change adds only a durable
scientific-transaction layer and deterministic crash-injection contract
tests. The real substrate is not executed here.

## Lineage

RSI-006-Q3 froze `EXECUTION FAILURE AFTER CONTACT` (proof-only PR #160):
the single authorized Stage 2 invocation consumed scientific contact,
sealed discovery on all four repositories (590 observations), and was
then killed by a VM reboot during confirmation. The work directory lived
under ephemeral `/tmp`; the contact marker, observations, seals, and
nonce evidence died with the host. Q3's protocol had no continuation
semantics for this case: the run could neither resume nor produce a
verdict, and the no-rerun/no-rescue rule correctly made that terminal
under the Q3 ID.

Inspection of the frozen Q3 evidence earned one narrow defect, and only
one: **crash continuity after scientific contact.** Q3 bound the
irreversible authorization to a single process and a volatile work
directory, with no durable continuation semantics. A recoverable
infrastructure event (host loss) destroyed the ability to reach or
preserve a verdict. Everything else in Q3 behaved as designed: receipt
verification, the feasibility guard, frozen baselines, the contact
gate's exactly-once marker, and the frozen phase order all printed
correctly before the reboot.

RSI-006-Q4 is the minimal successor that adds exactly one thing: a
durable, receiver-owned scientific-transaction layer with
crash-injection contract tests. It does not re-litigate Q3's verdict
(Q3 stays frozen), does not rescue Q3's run, and does not change any
scientific constant.

## Frozen Q3 scientific constants (unchanged, bound by self-check)

Every constant below is owned by the Q3 spec and Q3 modules. Q4 never
redefines them. `self_check.py` extracts them from the Q3 sources by AST
(without importing the substrate) and asserts equality with this table;
it also verifies the Q3 code files still hash to the frozen environment
receipt (`proofs/rsi-006-q3/environment-receipt.json`).

- Discovery seeds: `RSI-006-Q-discovery-A` / `RSI-006-Q-discovery-B`.
- Confirmation: fresh 256-bit OS-entropy nonce created only after the
  discovery seal exists. (The crash-injection fixtures use a
  deterministic test nonce derived from the transaction ID so that
  control and resumed runs are comparable; the transaction layer is
  nonce-agnostic and the real Q4 protocol preserves Q3's
  fresh-entropy semantics. This deviation is fixture-only and is
  stated in the claim boundary.)
- Budgets (discovery_A, discovery_B, determinism, confirmation):
  more-itertools (72, 72, 10, 20), cachetools (102, 102, 20, 60),
  boltons (70, 70, 20, 60), pluggy (51, 51, 20, 60).
- Thresholds: Q-DET agreement 1.0 exact; Q-SIG kill rate [0.05, 0.95];
  Q-STAB per-operator |dA−dB| ≤ 0.25 and Spearman ≥ 0.7 with ≥3 operators
  at ≥10 observations per half; Q-FRESH per-operator ≤ 0.30 and overall
  ≤ 0.15; collection-error rate < 0.10; Q-INTACT tree hash unchanged.
- Operator set: CMP_SWAP, ARITH_SWAP, BOOL_FLIP, NUM_DELTA, LOGIC_SWAP,
  NOT_DROP.
- Repository pins: more-itertools
  `b2f3aff7633057d234ec9186c18a53f4df306d08`, cachetools
  `4500e3d04288738d25acbb4973eb3c3e1bf41db9`, boltons
  `961dcff3f42e73b245aef65e377fe82763b257bb`, pluggy
  `0a4974175aa2d873f401345b151297af2e74c851` — untouched, read-only.
- Scoring semantics, canonical record shape, and the discovery-seal
  relationship: unchanged from Q3.
- Baseline semantics: vectors frozen in the Stage 1 receipt; Stage 2
  loads them, never re-executes them.
- Receipt verification and the contact boundary (exactly-once
  authorization consumption at the first actual mutant-observation
  process start): unchanged. The transaction layer records the contact
  event durably but does not move the boundary.

## The transaction layer (`stransaction.py`)

Substrate-agnostic: it journals opaque canonical observation bytes keyed
by mutant ID and knows nothing about mutants, repositories, or pytest.

- **Receiver-owned transaction ID**, derived deterministically from the
  environment receipt SHA-256 and the Q4 code hashes, created at
  `begin()` before any contact. Identical on every resume.
- **No ephemeral state**: `begin`/`open` refuse any work directory
  resolving under `/tmp`, `/var/tmp`, or `/dev/shm`. Fail closed.
- **Atomic, fsynced journal and artifacts**: temp file + fsync +
  atomic rename + directory fsync. Journal entries form a SHA-256 hash
  chain; the entry is the commit point. A crash leaves either the
  complete entry or nothing; stale temp files are ignored and cleaned
  on open.
- **Single contact event**: `note_contact` is exactly-once; after a
  restart it returns the original event instead of creating a second
  one. The event survives because it lives in the journal.
- **Discovery records and seals durable before advancing**: a seal
  commits only when every member observation is already committed.
- **Nonce committed before confirmation**: `commit_nonce` is
  exactly-once; any confirmation dispatch before the nonce entry is a
  driver-ordering violation the journal would expose. Resume reuses the
  committed nonce; never a new one.
- **Observations committed by ID and digest**; re-committing an ID is
  rejected (`DuplicateWork`). Completed observations are never rerun.
- **Resume verifies everything**: journal chain, receipt and code-hash
  bindings, and every committed artifact's digest. Then it appends a
  `restart` entry (so launch metadata records the restart) and the
  driver replays the plan, skipping committed work. No new nonce, seed,
  threshold, budget, pin, operator, or scoring value on resume.
- **Corrupted or incomplete checkpoint state fails closed**: no resume,
  no verdict.
- **Verdict/report commits atomically**: report written atomically
  first, journal entry binding its digest second. A report file with no
  entry is not committed; the driver recomputes deterministically.

### Orphan outcomes: the execution/commit gap

Two crash windows leave a completed outcome outside the journal: the
process dies after the observation physically executes but before
`commit_observation` runs (execution gap), or it dies inside
`commit_observation` after the outcome artifact is renamed but before
the journal entry binding its digest is appended (commit gap). A naive
resume would re-execute the observation -- for non-recomputable work
that is a second execution, not a retry.

The layer answers with `adopt_orphan_observation`: the exact first
completed outcome is recovered from independently durable,
transaction-bound evidence, and only if every check passes, in order:
evidence completeness; transaction ID; observation ID and phase;
receipt and code-hash bindings (no drift across the crash); and the
outcome artifact digest against the independently recorded digest.
Anything less -- missing fields, binding drift, digest mismatch, a
torn execution receipt, or an ambiguous execution count -- raises
`OrphanUnverifiable` and the resume fails closed: the outcome cannot
be proven, so it must not be silently re-derived.

Adoption is journaled as `observation_adopted`, distinct from a fresh
`observation` entry so provenance stays auditable. An adopted
observation counts as committed for resume/pending and digest purposes,
and its artifact is re-verified on every later resume like any other
committed observation. Adoption is itself crash-safe: a crash between
the artifact write and the journal append leaves the same orphan the
next resume can adopt.

## Crash-injection contract tests

Deterministic fixtures (no real repositories, no real mutants, no
scientific contact). A fake driver replays Q3's causal order
(contact → discovery → seal → nonce → confirmation → determinism
reruns → metrics → verdict) with outcomes as a pure function of
(seed, mutant ID). Termination is injected as a real `os._exit(1)` in a
subprocess at exact instrumentation points; a fresh process then
resumes from the same work directory.

Termination points: after contact; after discovery seal; after nonce
commit; mid-confirmation; before final verdict commit; mid-verdict
commit (orphan report file, no journal entry). Plus a double-crash
case (after contact, then mid-confirmation).

Two further termination points exercise the observation-completion
gap with an independently durable execution receipt outside the
journal: execution gap (outcome durably recorded, death before
`commit_observation`) and commit gap (death inside `commit_observation`
after the artifact rename, before the journal append). Each recorded
outcome carries fresh per-execution randomness, so a re-execution is
detectable by outcome bytes, not just by counting.

For every recoverable case: resumed canonical results digest and
verdict must equal the uninterrupted control exactly. Launch metadata
may differ and must record the restart (restart count ≥ 1 in
post-crash launches, 0 in control).

Negative tests: tampered journal entry → fail closed; tampered
observation artifact → fail closed; receipt binding drift on resume →
fail closed; duplicate observation commit → rejected; duplicate nonce
commit → rejected; double contact → single event, second call returns
the original; work dir under /tmp → refused; begin over an existing
journal → refused.

## Claim boundary (exact)

Q4 claims ONLY:

1. The transaction layer implements the durability contract above, as
   demonstrated by the fixture/contract tests listed here.
2. All Q3 scientific constants are unchanged, as demonstrated by
   `self_check.py`.
3. No Q3 file was modified by this change.

Q4 does NOT claim:

- substrate qualification (nothing was qualified);
- that the transaction layer is proven against real mutant workloads,
  real repositories, or real host failures (fixtures only);
- that any scientific contact occurred (none did);
- that the fixture's deterministic test nonce says anything about
  Q3's fresh-entropy confirmation semantics (it is a testability
  stand-in; the layer is nonce-agnostic).

## Anti-rescue (restated for Q4)

This layer is not a rescue of Q3's run. Q3 stays frozen exactly as
merged. The transaction layer is a protocol successor: it changes what
a future qualification run can survive, not what Q3 earned. No Q4
scientific contact occurs without a separate, explicit authorization,
and any future Stage 1/Stage 2 under a successor ID inherits this
layer's continuation semantics from before contact, never as a repair
after it.
