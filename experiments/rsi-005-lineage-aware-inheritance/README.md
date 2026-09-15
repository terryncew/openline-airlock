# RSI-005 lineage-aware inheritance — harness qualification

**Stage: harness qualification only. No scientific primary exists in this stage.**

RSI-004's single authorized primary attempt crashed before any phase dispatch.
The frozen root cause: `build_fixture()` recorded `state_dir=<tmp>/state` but
never created that directory, so the orchestrator's phase-token write raised
`FileNotFoundError` before any phase dispatch or Nightshift contact
(see `proofs/rsi-004/`).

RSI-005 exists to answer the lineage question again — but its first job is
not the science. This stage answers only:

> Can the repaired successor harness create its complete runtime state,
> establish the internal phase-token path, cross a real fresh-process
> dispatch boundary, and arrive at the exact pre-Nightshift boundary without
> executing a candidate, contacting Nightshift, writing REOPEN evidence, or
> beginning the scientific primary?

## The earned repair

`build_fixture()` in `run_rsi_005.py` creates `state_dir` before returning
the state object, and `write_phase_token()` fails closed if the directory is
ever absent again. A regression test proves the old missing-directory
condition would have raised `FileNotFoundError`.

## Marker alignment

RSI-004 proved marker creation and Nightshift contact were not the same
event. Here they are the same event by construction: the
primary-contact marker is written in exactly one place —
`nightshift_entry()` — immediately before the Nightshift path, and
`run_nightshift()` is called in exactly one place — inside
`nightshift_entry()`. The qualification stage never calls it, so the marker
stays absent.

## Qualification

```bash
python run_rsi_005.py --qualify-harness --output qualification.json
```

This runs the ordinary self-check, builds a real temporary fixture, writes
the real internal phase token, dispatches a fresh child process through the
same token-gated boundary future phases use, has the child reload state from
disk and verify the runtime evidence (repo, fixture base, installed refs at
the base, provider path, writability, token round-trip), records distinct
parent/child PIDs, reaches `PRE_NIGHTSHIFT_BOUNDARY`, and cleans up.

It never: calls `run_nightshift`, executes a candidate shim, writes the
primary-contact marker, creates a Nightshift generation/promotion, mints
lineage, issues REOPEN, runs checkpoint/reprojection, probes gen4, produces
a scientific verdict, or consumes any future one-run authorization.

Result terminology is `QUALIFIED_RSI_005_PRE_NIGHTSHIFT_HARNESS` /
`NOT_QUALIFIED_RSI_005_PRE_NIGHTSHIFT_HARNESS` — never scientific verdicts.

Distinct PIDs prove only distinct processes. No process, memory, filesystem,
or hostile-process isolation is claimed.

## Sealed predecessors

RSI-004, RSI-003, and Verified Memory are sealed. The runner's self-check
verifies their frozen bytes (RSI-004 runner SHA-256, RSI-004 preregistration
SHA-256, Verified Memory commit and `evidence.py` SHA-256) and the base
ancestry (`f2f2ece`). Nothing in this experiment modifies them.

The scientific RSI-005 preregistration is NOT frozen in this stage. No
lineage question is answered, authorized, or claimed here.
