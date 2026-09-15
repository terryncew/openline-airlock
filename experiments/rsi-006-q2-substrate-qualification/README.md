# RSI-006-Q2 — Substrate Qualification

**Not a scientific experiment.** This stage qualifies the external discovery
substrate for RSI-006: generic, receiver-owned perturbations (seeded AST
mutations) applied to untouched real repositories must yield stable,
reproducible, signal-bearing observations — *without looking at arm
performance*. There are no researcher arms here: no parent, no child, no
hypotheses, no predictions, no model access, no LLM calls.

## Lineage

RSI-006-Q froze `NOT_QUALIFIED_RSI_006_SUBSTRATE` (proof-only PR #156).
Review found the failure was broader than first thought, but three of the
defects were in the qualification design, not the substrate:

1. Q-STAB was arithmetically impossible for more-itertools (20 mutants per
   half < 3 operators × 10 observations).
2. Nothing checked reachability before spending test executions.
3. The runner kept only aggregates — the exact cachetools determinism
   mismatch and pluggy collection-error sites are unidentifiable from the
   Q1 receipt.

RSI-006-Q2 is the minimal repair: same repositories, pins, operator set,
discovery seeds, thresholds, fresh-nonce semantics, and scoring. Only
three changes: (1) per-half budgets raised to the exact static minima at
which 3×10 is deterministically reachable (72 / 102 / 70 / 51);
(2) a deterministic pre-observation feasibility guard that stops the run
before any test execution if Q-STAB is unreachable; (3) canonical
per-mutant records persisted for discovery, confirmation, and determinism
rerun pairs, bound by SHA-256 in the report.

A known generator quirk (`_is_bool_candidate` matches integer `0`/`1` by
`==`) is documented in the spec and deliberately left frozen — fixing it
would change the mutant population and is out of scope for Q2.

## Layout

- `RSI_006_Q2_SPEC.md` — frozen qualification spec (the authority:
  lineage, repo pool, operator set, seeds, budgets, feasibility guard,
  record persistence, thresholds, verdicts).
- `perturb.py` — frozen seeded perturbation generator, byte-identical to
  RSI-006-Q (6 generic AST operators; same seed → byte-identical mutant
  list).
- `observe.py` — observation harness, unchanged from RSI-006-Q
  (overlay-copy mutation, fresh process per mutant, JUnit comparison to
  the green baseline).
- `run_rsi_006_q2.py` — orchestrator: SHA verification → feasibility
  guard (no test execution) → baselines → discovery + records + seal →
  fresh-nonce confirmation + records → determinism reruns + pairs →
  metrics → verdict → report.
- `tests/test_rsi_006_q2_contract.py` — 20 contract tests: frozen
  properties only, no substrate qualification, no arm performance.
- `tests/fixtures/tinypkg/` — tiny fixture package for the
  observation-path tests.

## Running

Self-check (non-executing; safe anywhere):

```
python run_rsi_006_q2.py --self-check
```

Full qualification (local only; clones four real repos, ~950 observations,
roughly an hour with two workers; zero API spend):

```
python run_rsi_006_q2.py --qualify --work-dir /tmp/rsi-006-q2 --workers 2
```

The full run is never invoked in CI (asserted by the
`rsi-006-q2-gate.yml` workflow) and is only launched when authorized.
