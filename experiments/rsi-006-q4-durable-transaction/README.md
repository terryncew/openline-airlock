# RSI-006-Q4 — Durable Scientific Transaction

Pre-contact successor to frozen RSI-006-Q3. Adds one thing: a durable,
receiver-owned scientific-transaction layer (`stransaction.py`) plus
deterministic crash-injection contract tests (`tests/`).

- `RSI_006_Q4_SPEC.md` — the authority: lineage, frozen Q3 constants,
  the transaction contract, the test matrix, and the exact claim
  boundary.
- `stransaction.py` — the transaction layer. Substrate-agnostic;
  journals opaque canonical observation bytes keyed by mutant ID.
- `self_check.py` — binds every Q3 scientific constant by AST
  extraction, verifies Q3 files still hash to the frozen receipt, and
  asserts no forbidden imports. Run: `python self_check.py`.
- `tests/fixture_driver.py` — deterministic fake driver replaying Q3's
  causal order; injects real `os._exit(1)` termination at named points.
- `tests/test_crash_continuity.py` — the contract tests. Run:
  `python -m pytest tests/ -q`.

No Stage 1, no real repositories, no real mutants, no scientific
contact. Q3 (`../rsi-006-q3-substrate-qualification/`) is not modified
by this change.
