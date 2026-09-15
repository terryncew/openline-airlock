# RSI-006-Q3 — Substrate Qualification Spec

**Status: FROZEN** (pending review; Stage 2 `--qualify` not authorized).
This file is the authority for RSI-006-Q3. Thresholds, budgets, seeds,
and the two-stage boundary below were set before any RSI-006-Q3 mutant
was generated or observed. If the substrate fails qualification, it is
not tuned under this ID.

## Lineage

RSI-006-Q froze `NOT_QUALIFIED_RSI_006_SUBSTRATE` (proof-only PR #156).
RSI-006-Q2 froze `INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE`
(proof-only PR #158): its single-shot runner burned the one-run
authorization on an environment defect — the execution host had no
`pytest`, so every baseline returned `collection_error` with empty
outcomes before any mutant was generated or observed. The frozen Q2
verdict is preserved as historical evidence and is not reinterpreted
here.

Review found the defect that killed Q2 was in the qualification design,
not the substrate: **the protocol had no separation between recoverable
environment engineering and irreversible scientific contact.** One
function performed pool setup, SHA verification, the feasibility guard,
baselines, discovery, sealing, confirmation, and reruns; baseline
subprocess stdout/stderr was discarded; and the one-run authorization was
consumed by an environment failure that produced zero scientific
information.

RSI-006-Q3 is the minimal successor that adds exactly two things:

1. **A two-stage boundary** between repeatable environment qualification
   (Stage 1) and irreversible scientific contact (Stage 2), joined only
   by a frozen environment receipt.
2. **Full launch observability**: every suite launch preserves its exact
   argv, interpreter, cwd, environment identity, exit status, stdout,
   stderr, JUnit report (when produced), and start/end timestamps.
   `collection_error` is a disposition only; it is never sufficient
   evidence by itself.

Everything else is unchanged: the same four pinned repositories, the
same operator set, the same discovery seeds, the same thresholds, the
same budgets, the same fresh-nonce semantics, the same scoring
semantics, the same canonical record shape and seal relationship. No
researcher arms, no hypotheses, no LLM imports, zero API spend —
asserted by contract test, as in Q1/Q2.

## Stage 1 — environment qualification (repeatable until green)

Entry: `python env_qualify.py --qualify-env --work-dir DIR`.

Stage 1 owns terminal execution of the environment. It may:

- select and verify the interpreter (exact path, version, implementation)
- install missing test dependencies and freeze exact versions
- clone repositories and verify pinned SHAs
- run untouched baselines (green + deterministic across two runs)
- repair setup/environment issues
- repeat failed environment checks after repair

It must NOT:

- generate mutants
- execute mutant outcomes
- issue a confirmation nonce
- touch discovery/confirmation seeds in an outcome-bearing way
- expose researcher-arm performance
- consume the one-run scientific authorization

Structural guarantee: `env_qualify.py` never imports `perturb`
(asserted statically by AST and dynamically: `perturb` is absent from
`sys.modules` after Stage 1). The observation harness loads the mutation
substrate lazily, only inside the mutant path, which Stage 1 never calls.

When Stage 1 is green it freezes an **environment receipt**
(`environment-receipt.json`):

- exact interpreter identity (resolved path, version, implementation)
- dependency lock (exact installed versions of required packages)
- repository pins, checked-out SHAs, and tree hashes
- the frozen baseline outcome vectors
- baseline commands and launch-evidence bindings (SHA-256 of each
  preserved launch record)
- hashes of all Q3 code/spec files
- host facts needed to reproduce the execution surface

After the freeze, the environment contents used for the scientific run
are immutable: Stage 2 re-verifies every binding and refuses on drift.

## Stage 2 — scientific contact (irreversible)

Entry: `python run_rsi_006_q3.py --qualify --env-receipt PATH --work-dir DIR`.

Verdicts: `QUALIFIED_RSI_006_Q3_SUBSTRATE`,
`NOT_QUALIFIED_RSI_006_Q3_SUBSTRATE`,
`INCONCLUSIVE_RSI_006_Q3_PRECONDITION_FAILURE`.

Stage 2 performs, in order: receipt verification → repository SHA
verification → feasibility guard (static) → discovery from the frozen
seeds (observe, persist canonical records + launch sidecars, seal) →
fresh OS-entropy nonce → confirmation → determinism reruns →
metrics → verdict → report. Baseline vectors are loaded from the
receipt; baselines are not re-executed in Stage 2.

### The authorization-consumption boundary (mechanical)

The one-run authorization is consumed **only when the first
mutant-observation process is actually started**. The mechanism:

- Stage 2 constructs one receiver-owned `ContactGate` over
  `scientific-contact.json` before discovery begins. The gate's sole
  mutating entry point is `note_process_started`.
- `observe.run_suite_once` invokes that hook with the child pid
  immediately after `subprocess.Popen` returns on the mutant path --
  i.e. only once the OS has actually spawned the mutant-observation
  process. A spawn failure (`OSError`) never reaches the hook.
- The baseline path (`observe_baseline`) never receives the hook, so
  Stage 1-style launches cannot consume authorization.
- The gate's transition is atomic (an in-process lock plus an atomic
  `O_CREAT|O_EXCL` create of the marker file): the first actual start
  creates the marker
  `{schema, event, mutant_id, receipt_sha256, child_pid, ts}`; every
  later start is a no-op that reads back the winner's marker instead of
  rewriting or duplicating the event.

Consequences, all mechanical rather than conventional:

- receipt verification, the feasibility guard, mutation generation,
  executor creation, and failed submissions all precede any mutant
  `Popen`: none of them can consume authorization;
- exactly one marker can ever exist; later starts neither rewrite nor
  duplicate it;
- the contact marker names the real mutant and the real subprocess pid,
  cross-checkable against the persisted launch evidence (`child_pid`).

From the first marker:

- no environment repair
- no dependency change
- no interpreter change
- no rerun
- no rescue
- no threshold change
- no seed change
- no repository substitution
- no operator change

- no environment repair
- no dependency change
- no interpreter change
- no rerun
- no rescue
- no threshold change
- no seed change
- no repository substitution
- no operator change

The first scientific outcome stands. If Stage 2 starts and then fails —
for any reason — the first outcome is frozen exactly and no second
scientific invocation occurs under Q3.

Stage 2 refuses to start (non-zero exit, zero subprocesses, zero contact
marker) when: the receipt is missing, unparseable, schema-mismatched, or
any binding (interpreter, dependency lock, Q3 code hashes, repository
checkouts/trees) has drifted.

## Launch observability

Every suite launch — baseline or mutant, Stage 1 or Stage 2 — preserves:

- exact command argv
- interpreter path (as invoked)
- cwd
- environment identity (SHA-256 over the full child environment) plus
  the exact overrides the harness sets
- exit status (null on timeout)
- stdout and stderr (full bytes)
- JUnit report presence and SHA-256 (when produced)
- start/end timestamps and duration
- classification/disposition: one of `ok`, `timeout`,
  `collection_error_no_junitxml`, `collection_error_unparseable_junitxml`

Launch evidence travels as a sidecar to the canonical observation
record; the canonical record shape and the discovery seal relationship
are unchanged from Q2.

## Frozen constants (unchanged from Q2)

Discovery seeds: `RSI-006-Q-discovery-A` / `RSI-006-Q-discovery-B`.
Confirmation uses a fresh 256-bit OS-entropy nonce created only after
the discovery seal exists (resampling stability, not unseen-site
transfer — as settled for Q2).

Budget tuples (discovery_A, discovery_B, determinism, confirmation):
more-itertools (72, 72, 10, 20), cachetools (102, 102, 20, 60),
boltons (70, 70, 20, 60), pluggy (51, 51, 20, 60).

Thresholds: Q-DET agreement 1.0 exact; Q-SIG kill rate [0.05, 0.95];
Q-STAB per-operator |dA−dB| ≤ 0.25 and Spearman ≥ 0.7 with ≥3 operators
at ≥10 observations per half; Q-FRESH per-operator ≤ 0.30 and overall
≤ 0.15; collection-error rate < 0.10; Q-INTACT tree hash unchanged.

Repository pool: more-itertools `b2f3aff7`, cachetools `4500e3d0`,
boltons `961dcff3`, pluggy `0a497417` — untouched, read-only.

## Known generator issue (carried over from Q2, still out of scope)

`perturb.py` is byte-identical to the RSI-006-Q2 generator
(`e4e35ca7…14da6302`). `_is_bool_candidate` matches integer literals
`0`/`1` by `==`; BOOL_FLIP on `0` yields `True`, on `1` yields `False`
— int-to-bool conversions alongside genuine boolean flips. Unchanged
and deterministic; fixing it would change the mutant population and
remains out of scope.

## Anti-rescue

No rerun, repair, threshold movement, diagnosis-driven tuning,
reinterpretation, repository substitution, operator changes, or seed
changes under RSI-006-Q3 after scientific contact begins. Stage 1
repair-and-repeat is routine engineering, not a scientific outcome, and
is permitted only before the receipt is frozen for the authorized run.
