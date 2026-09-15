# RSI-006-Q — Substrate Qualification Spec

**Status: FROZEN.** This file is the authority for RSI-006-Q. Thresholds below
were set before any mutant was generated or observed. If the substrate fails
qualification, it is not tuned under this ID; a repair is a new qualification
ID with a new frozen spec.

## What RSI-006-Q is

A substrate qualification, **not a scientific experiment**. It proves that the
external discovery machinery for RSI-006 can produce enough stable,
reproducible observations on untouched real repositories **without looking at
arm performance**. There are no researcher arms in RSI-006-Q: no parent, no
child, no hypotheses, no LLM calls, no model access. The orchestrator contains
no researcher code path by construction (asserted by contract test).

RSI-006-Q answers one question: *can generic, receiver-owned perturbations of
real repositories yield a discovery archive and a fresh-nonce confirmation set
with stable, reproducible, signal-bearing structure?* Whether any research
method can discover that structure is RSI-006 science, not this stage.

## Causal order (mirrors the RSI-006 contract)

1. This spec and its code are frozen; their hashes are recorded in the report.
2. Verify repository SHAs against the pinned pool. Verify baselines: every
   repo's unmutated suite must be fully green and deterministic across two
   runs.
3. Generate the discovery mutant set from the frozen perturbation generator
   with the frozen discovery seeds. Seal the discovery archive (SHA-256 of the
   canonical observation bytes).
4. **Only after the seal is written**, the receiver creates a fresh 256-bit
   nonce from OS entropy and generates the confirmation mutant set.
5. Compute the qualification metrics. Emit the report. No researcher ever
   sees the archive.

## Repository pool (untouched, read-only)

| repo | pinned commit | package dir | tests dir | suite time |
|---|---|---|---|---|
| more-itertools | `b2f3aff7633057d234ec9186c18a53f4df306d08` | `more_itertools/` | `tests/` | ~25 s |
| cachetools | `4500e3d04288738d25acbb4973eb3c3e1bf41db9` | `src/cachetools/` | `tests/` | ~4.5 s |
| boltons | `961dcff3f42e73b245aef65e377fe82763b257bb` | `boltons/` | `tests/` | ~2 s |
| pluggy | `0a4974175aa2d873f401345b151297af2e74c851` | `src/pluggy/` | `testing/` | ~0.4 s |

- Repos are cloned at the pinned commit and treated read-only. A SHA-256 tree
  hash (all files excluding `.git/`) is recorded before and after the run;
  Q-INTACT requires byte identity.
- Observation runs execute with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH`
  pointing at the package dir, cwd in a temp dir, `-p no:cacheprovider`.
  Nothing is installed into the environment and nothing is written into the
  checkout. Verified by the tree hash, not by assertion.

## Perturbation generator (frozen, generic, receiver-owned)

`perturb.py` implements a seeded AST mutation generator. The operator set is
fixed and defined without reference to any repository's semantics:

| operator | transformation |
|---|---|
| `CMP_SWAP` | `==`→`!=`, `!=`→`==`, `<`→`<=`, `<=`→`<`, `>`→`>=`, `>=`→`>` |
| `ARITH_SWAP` | `+`→`-`, `-`→`+`, `*`→`/`, `/`→`*` |
| `BOOL_FLIP` | `True`→`False`, `False`→`True` |
| `NUM_DELTA` | integer literal `n` (abs(n) ≤ 1000) → `n+1` |
| `LOGIC_SWAP` | `and`→`or`, `or`→`and` |
| `NOT_DROP` | `not x` → `x` |

- A mutant is exactly one operator application at one site.
- Sites are enumerated deterministically: all eligible AST sites in the
  package dir, sorted by (file path, line, column). Test directories are
  never mutated: the regularity must come from library behavior, not from
  breaking the tests themselves.
- Given a seed string, `random.Random(seed)` shuffles the site list and the
  first N sites become the mutant set. Same seed → byte-identical mutant
  list (asserted by contract test).
- Frozen seeds: discovery halves `RSI-006-Q-discovery-A` and
  `RSI-006-Q-discovery-B`. The confirmation nonce is generated fresh in
  step 4 of the causal order and recorded in the report.

## Observation

`observe.py` applies one mutant (in-memory AST rewrite written to a temp
overlay directory shadowing the package dir via `PYTHONPATH` ordering —
the checkout itself is never modified) and runs the repo's suite once in a
fresh subprocess with a per-run timeout of 120 s.

- Per-test outcomes are parsed from `--junitxml` (stdlib only).
- Observation record: `{repo, mutant_id, operator, site_key, outcomes,
  kill, collection_error, timeout}`.
- `kill = true` iff any test outcome differs from the pinned baseline
  vector, or collection fails, or the run times out. Timing values are
  excluded from the record: identity is behavioral, not temporal.
- Baseline: the unmutated suite outcome vector per repo, pinned at step 2.

## Mutant budgets

| set | boltons | cachetools | pluggy | more-itertools |
|---|---|---|---|---|
| discovery A | 60 | 60 | 60 | 20 |
| discovery B | 60 | 60 | 60 | 20 |
| determinism rerun | 20 | 20 | 20 | 10 |
| confirmation (fresh nonce) | 60 | 60 | 60 | 20 |

Estimated single-threaded wall time ≈ 35 min; the runner parallelizes
across 2 workers.

## Qualification criteria

All thresholds frozen before any observation.

- **Q-DET (determinism):** rerun of the determinism subset must reproduce
  byte-identical observation records. Required agreement: **1.0 exact**.
- **Q-SIG (signal):** per-repo discovery kill rate must lie in
  **[0.05, 0.95]**. Below: no behavioral variation to discover. Above:
  saturated, no structure.
- **Q-STAB (stability of structure):** the load-bearing check. For each
  operator with ≥ 10 mutants in each discovery half, per-half kill rates
  must agree within **±0.25 absolute**, and the Spearman rank correlation
  of operator kill rates across halves must be **≥ 0.7**. Fewer than 3
  qualifying operators in a repo → criterion fails for that repo.
  This proves the operator→behavior mapping is a property of the
  repository, stable across independent samples — which is what makes
  fresh-nonce confirmation meaningful.
- **Q-FRESH (fresh-nonce confirmation feasibility):** on the confirmation
  set, per-operator kill rates within **±0.30** of the pooled discovery
  rates, and overall kill rate within **±0.15**.
- **Q-COST (economics):** report-only. Observations per minute per repo and
  the projected cost of an RSI-006-scale archive. No bound.
- **Q-INTACT (untouched repos):** tree hash identical before and after.
  Required: exact.
- **Sanity bound:** collection-error rate per repo **< 0.10** (guards
  operator validity).

## Verdicts

- `QUALIFIED_RSI_006_SUBSTRATE` — every criterion met on every repo.
- `NOT_QUALIFIED_RSI_006_SUBSTRATE_<CAUSE>` — any metric criterion fails.
  The report names the failed criterion, repo, observed vs bound.
- `INCONCLUSIVE_RSI_006_Q_PRECONDITION_FAILURE` — SHA mismatch, baseline
  not green, baseline not deterministic, or harness error. Not a substrate
  failure; not a pass.

Precondition failures take precedence over metric failures.

## Anti-tuning

Thresholds, seeds, operator set, and repo pool are frozen in this spec.
No threshold, operator, repo, or budget may change after the first
observation without a new qualification ID and a new frozen spec. The
report records the SHA-256 of this spec file and of `perturb.py`,
`observe.py`, and `run_rsi_006_q.py` as executed.

## Explicitly out of scope

- No researcher arms, no hypotheses, no predictions, no scoring of any
  research method. A contract test asserts the Q package imports no LLM /
  model-access modules.
- No claim that any pattern in the archive is discoverable, interesting,
  or scientifically meaningful. Q proves signal-bearing reproducible
  structure exists, nothing more.
- No network isolation claim beyond: observation runs share the host
  network namespace; the pinned suites require no network access.
