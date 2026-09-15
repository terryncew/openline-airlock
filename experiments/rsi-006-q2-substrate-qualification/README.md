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
discovery seeds, thresholds, fresh-nonce semantics, and Q1 scoring
(a collection error marks the observation as killed AND counts
independently against the <0.10 sanity bound). Only three changes:
(1) discovery-half budgets raised to the exact static minima at which 3×10
is deterministically reachable (72 / 102 / 70 / 51) — determinism and
confirmation budgets keep their Q1 values, so the final tuples are
(72, 72, 10, 20), (102, 102, 20, 60), (70, 70, 20, 60), (51, 51, 20, 60);
(2) a deterministic pre-observation feasibility guard that stops the run
before any test execution if Q-STAB is unreachable; (3) canonical
per-mutant records persisted for discovery, confirmation, and determinism
rerun pairs, bound by SHA-256 in the report. Confirmation samples the same
site pool with a fresh post-seal nonce, so Q-FRESH means resampling
stability under a fresh seed — not unseen-site transfer, which belongs to
the RSI-006 science layer.

A known generator quirk (`_is_bool_candidate` matches integer `0`/`1` by
`==`; application computes `not node.value`, so `0 -> True` and
`1 -> False`) is documented in the spec and deliberately left frozen —
fixing it would change the mutant population and is out of scope for Q2.
The `BOOL_FLIP` label therefore covers genuine boolean flips and
integer-to-boolean conversions, and must not be described as a semantically
pure boolean operator.

## Layout

- `RSI_006_Q2_SPEC.md` — frozen qualification spec (the authority:
  lineage, repo pool, operator set, seeds, budgets, feasibility guard,
  record persistence, thresholds, verdicts).
- `perturb.py` — frozen seeded perturbation generator, byte-identical to
  RSI-006-Q (6 generic AST operators; same seed → byte-identical mutant
  list).
- `observe.py` — observation harness, byte-identical to the frozen
  RSI-006-Q harness (SHA-256 pinned by contract test): Q1 scoring exactly —
  a collection error marks the observation as killed and counts
  independently against the sanity bound.
- `run_rsi_006_q2.py` — orchestrator: SHA verification → feasibility
  guard (no test execution) → baselines → discovery + records + seal →
  fresh-nonce confirmation + records → determinism reruns + pairs →
  metrics → verdict → report.
- `tests/test_rsi_006_q2_contract.py` — 26 contract tests: frozen
  properties only, no substrate qualification, no arm performance.
- `tests/fixtures/tinypkg/` — tiny fixture package for the
  observation-path tests.

## Running

Self-check (non-executing; safe anywhere):

```
python run_rsi_006_q2.py --self-check
```

Full qualification (local only; clones four real repos, ~870 observations,
roughly an hour with two workers; zero API spend):

```
python run_rsi_006_q2.py --qualify --work-dir /tmp/rsi-006-q2 --workers 2
```

The full run is never invoked in CI (asserted by the
`rsi-006-q2-gate.yml` workflow) and is only launched when authorized.
