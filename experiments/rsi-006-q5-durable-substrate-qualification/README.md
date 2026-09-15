# RSI-006-Q5: durable substrate qualification (pre-contact)

Pre-contact integration of Q3's frozen scientific machinery with Q4's
merged durable transaction layer, plus a receiver-owned durable
execution ledger around the real observation path.

- `RSI_006_Q5_SPEC.md` — lineage, frozen constants, ledger contract,
  contact preservation, Stage 1 receipt requirements, claim boundary.
- `execution_ledger.py` — atomic prepared / started / spawn_failed /
  completion records; resume classifies each observation as committed /
  fresh / retry_allowed / recoverable, or fails closed
  (`UncertainExecution`) on any unverifiable state.
- `q5_adapter.py` — single-writer `Coordinator`: worker threads race at
  real process-start/contact (Q3 `ContactGate`) and return evidence;
  the coordinator serializes all Q4 journal mutations through its one
  live `ScientificTransaction` (opened at most once per process), with
  `reconcile_contact` for the gate-win/journal-append crash window.
- `self_check.py` — binds every frozen Q3 constant, verifies Q3 files
  against the frozen environment receipt, verifies Q4's
  `stransaction.py` against the merged PR #161 hash, rejects forbidden
  imports, and smoke-tests the adapter with a real subprocess.
- `tests/` — ledger contract tests, crash-injection integration tests
  with actual subprocesses (including deterministic spawn failure),
  single-coordinator contact-race tests, and a coordinator
  crash/resume test asserting exactly one `restart` entry.

Run: `python3 self_check.py`, then
`python -m pytest tests/ -q -p no:cacheprovider` from this directory.

No Stage 1, no real repositories, no real mutants, no scientific
contact. Q3, Q4, and `proofs/` are not modified.
