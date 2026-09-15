# RSI-006-Q2 result freeze

Experiment: RSI-006-Q2 substrate qualification (non-scientific stage).
Question: can the external discovery substrate — generic, receiver-owned
perturbations of untouched real repositories — yield stable, reproducible,
signal-bearing observations, without looking at arm performance?

## Verdict

`INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE`

The single corrected `--qualify` invocation started, passed the
deterministic feasibility guard on all four repositories, cloned all four
repositories at their exact frozen pins, and then failed every baseline
with a collection error before any mutant was generated or observed.
0 observations in 16.5 s, zero API spend, no researcher arms involved,
runner exit code 0. No confirmation nonce was issued, no discovery
archive was sealed, no records were written.

## The two evidence items (both frozen here)

1. **PRE-RUN launcher failure** (`launcher-failure-exit127.log`):
   the first launch attempt invoked `python`, which does not exist on the
   execution host. Shell exit 127 in ~9 ms; the Python interpreter never
   started and `run_rsi_006_q2.py` never executed. Classified by explicit
   authorization as `PRE-RUN_LAUNCHER_FAILURE` — launcher provenance,
   not a qualification verdict and not a scientific outcome.
2. **Authorized Q2 qualification** (`primary-stdout.log`,
   `rsi-006-q2-report.json`): the single corrected `python3` invocation
   and its exact first outcome, preserved unaltered.

The launcher failure preceded the experimental apparatus and did not
generate or influence any substrate observation: `/tmp/rsi-006-q2` was
never created, zero baselines executed, zero mutants executed, zero
substrate contact, zero observations, zero confirmation nonce, zero
model/API/researcher activity.

## Pre-flight (all passed before the corrected invocation)

- `git rev-parse HEAD` = `795aa35ca806bfe659a1c9870f92a85e5d1f87f9`
  (the merged Q2 stage).
- Tracked working tree clean (only pre-existing untracked historical
  proof files, preserved).
- Frozen package hashes recomputed from source bytes, all matching the
  authorization: spec `6e2ed29a…e947c79`, perturb.py `e4e35ca7…14da6302`,
  observe.py `b4556add…7a7182c` (byte-identical to the frozen Q1
  harness), runner `28b0d0e4…2735f71dd9`.
- Non-executing `--self-check` clean under `python3`.
- `/tmp/rsi-006-q2` confirmed absent before launch.

## What the run did, exactly (from the report)

- Feasibility guard PASS on all four repos (static AST site
  enumeration, no test execution): more-itertools, cachetools, boltons
  qualifying on ARITH_SWAP/BOOL_FLIP/NUM_DELTA; pluggy on
  BOOL_FLIP/NUM_DELTA/LOGIC_SWAP.
- All four repos cloned at their exact frozen pins (more-itertools
  `b2f3aff7`, cachetools `4500e3d0`, boltons `961dcff3`, pluggy
  `0a497417`); tree hashes identical before and after (Q-INTACT held;
  nothing was modified).
- Each baseline subprocess returned
  `{'outcomes': {}, 'collection_error': True, 'timeout': False}`,
  recorded in the report as `precondition_failures`.

## Observed environment fact (not a diagnosis)

`/usr/bin/python3 -m pytest` on this host prints
`No module named pytest`. The frozen `observe.py` runs baselines as
`[python, -m, pytest, … --junitxml=…]` with stdout/stderr suppressed,
and marks a run as `collection_error` when no JUnit XML is produced.
That is the full extent of what was observed about the failure
mechanism. Whether the substrate would have qualified in an environment
with pytest installed is unobserved; installing it and rerunning would
be rescue, and is not permitted under this ID.

No diagnosis, tuning, re-observation, or second invocation was
performed after the first runner outcome.

## Authorization consumed

The corrected one-run authorization was consumed the moment `python3`
successfully started the Q2 runner process. Per the authorization, no
second qualification invocation may occur under RSI-006-Q2 regardless
of verdict, exception, harness failure, timeout, partial execution,
precondition failure, or substrate failure.

## Standing state

- RSI-006-Q2 is closed with this freeze. Anti-rescue is in force: no
  rerun, repair, threshold movement, diagnosis-driven tuning,
  reinterpretation, repository substitution, operator changes, or seed
  changes under this ID.
- RSI-006 science does not begin; no new experiment ID is opened by
  this freeze.
