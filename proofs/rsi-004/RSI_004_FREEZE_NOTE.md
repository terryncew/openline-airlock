# RSI-004 freeze note — first and only primary outcome

**Date (PDT):** 2026-09-14 17:56:00
**Experiment:** RSI-004 lineage-aware inheritance
**Status:** PERMANENTLY CLOSED. No scientific outcome was produced. No rerun,
repair, tuning, threshold change, or reinterpretation under RSI-004.

## Authorization

Terrynce authorized exactly one primary run after PR #151 merged to main.
PR #151 was merged as `3323b9b6cb36325c7a936476a53b6dad61489e94`.
Reviewed commit `a0e3d40a33c7c2e3f073f507b568e908bf1327e3` was verified an
ancestor of the merged main. That authorization has been consumed.

## The single primary run

- Command: `~/workspace/.venvs/rsi004/bin/python run_rsi_004.py
  --execute-primary --output result.json`
- Working directory: `experiments/rsi-004-lineage-aware-inheritance/`
- Interpreter/environment: the existing `rsi004` venv that previously passed
  the pinned-dependency self-check. Nothing in the environment, runner,
  preregistration, fixture, thresholds, or verdict logic was modified.
- Merged main used: `3323b9b6cb36325c7a936476a53b6dad61489e94`
- Pre-run gates all passed on the merged main: self-check clean
  ("16 prereg bindings unambiguous, pins verified, gates closed"), 34/34
  contract tests green, preregistration SHA-256 verified
  (`8e9ceb9bc928c710920893a79fa99661f93d2456bc3acf1586a8175eb51ca8fd`),
  Verified Memory pins verified (commit
  `36e3d0e0dab6a121abc1c14accbaa7310b5c2186`, evidence.py SHA-256
  `ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9`).

## What happened

The run exited in under one second with exit code 1 and this exact stderr:

```
RSI-004 harness error: [Errno 2] No such file or directory: '/tmp/airlock-rsi-004-rsooyorf/state/.phase_token'
```

Root cause (present in the reviewed, merged code): `build_fixture()`
records `state["state_dir"]` as `<tmp>/state` but never creates that
directory. `orchestrate()` then writes the orchestrator phase token to
`<tmp>/state/.phase_token` (`run_rsi_004.py`, line 2278) before dispatching
any phase. The parent directory does not exist, so the write raises
`FileNotFoundError`, which is not a `PreconditionFailure` and therefore
bypasses the verdict path entirely. The failure is deterministic: every run
of this code fails the same way at the same place.

## What did NOT happen

- No phase dispatch: zero of the 12 phases ran (`--phase` was never invoked,
  by the orchestrator or manually).
- No Nightshift contact: the primary-contact marker was written immediately
  before the token write (see below), but no Nightshift call ever occurred.
- No REOPEN, no checkpoint, no reprojection, no candidate-shim execution.
- No `result.json`, no primary receipt, no phase-PID map, no verdict, and no
  cause_code were produced. There is no formal outcome to reinterpret —
  this freeze records a harness crash, not PASS, FAIL, or INCONCLUSIVE.
- The runner's `finally` block removed the temporary fixture directory.
- gen4 remained probe-only and was never executed.
- RSI-003 was untouched (`proofs/rsi-003/RSI_003_RECEIPT.json` SHA-256 still
  `81fae997106c825e3d5ed38f1c20a507eb7961bee50025577b3e4af12ae963ae`).
- Verified Memory was untouched (installed package only, evidence.py hash
  unchanged).

## Anti-rescue

The preregistered Nightshift-contact anti-rescue trigger was not reached
because no Nightshift contact occurred. Separately, the explicit
authorization permitted exactly one primary invocation and prohibited rerun
or repair after that first attempt. That one-run authorization was consumed
when the authorized top-level primary command was executed. RSI-004 is
therefore permanently closed with a harness crash and no scientific
outcome.

The primary-contact marker WAS written at 2026-09-14 17:56:00 PDT, before
the crash. It is evidence that the authorized primary invocation began,
not evidence of actual Nightshift contact: marker creation and the
preregistered Nightshift-contact trigger are distinct, and only the former
occurred here. No rerun, no repair, no tuning, no threshold change, no
reinterpretation, no completion of the outcome under this experiment ID. A
successor repair would require a new experiment ID and separate
authorization.

## Scope notes (for the record, not claims)

- The "12-phase process PID" design is a process-separation mechanism only
  (each phase in a fresh subprocess with distinct PIDs); no result was
  produced, so nothing here establishes process, memory, or filesystem
  isolation.
- Raw historical receipt byte-identity was never exercised (no checkpoint).
- Installed-ref/policy identity checks never ran (no phases ran).

## Evidence preserved

- `RSI_004_PRIMARY_HARNESS_ERROR.txt` — the exact captured stdout/stderr and
  exit code of the single primary run.
- `RSI_004_INTEGRITY_MANIFEST.json` — SHA-256 values for every relevant
  artifact: preregistration, runner, primary-contact marker, RSI-003 receipt,
  Verified Memory evidence.py, plus the merged main SHA, command, and
  timestamps.
- The primary-contact marker itself remains at its canonical location
  `experiments/rsi-004-lineage-aware-inheritance/.rsi-004-primary-contact`
  (untracked, runtime artifact; preserved in place, not moved).

No experiment code was changed in this freeze. This commit contains only
`proofs/rsi-004/` additions.
