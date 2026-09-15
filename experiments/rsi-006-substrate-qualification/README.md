# RSI-006-Q — Substrate Qualification

**Not a scientific experiment.** This stage qualifies the external discovery
substrate for RSI-006: generic, receiver-owned perturbations (seeded AST
mutations) applied to untouched real repositories must yield stable,
reproducible, signal-bearing observations — *without looking at arm
performance*. There are no researcher arms here: no parent, no child, no
hypotheses, no predictions, no model access, no LLM calls.

## Why this stage exists

RSI-006 will test whether an earned method mutation lets a successor extract
new predictive structure from evidence the parent already had. That claim is
only meaningful if the discovery substrate itself is sound: the archive must
contain stable behavioral regularities that recur under fresh perturbations.
RSI-006-Q proves the machinery can produce such observations before any
scientific thresholds are preregistered.

Precedent: RSI-002 sealed the method candidate before the independent
holdout existed, with generator != evaluator. RSI-006-Q applies the same
discipline to the substrate: the discovery archive is sealed before the
confirmation nonce exists.

## Layout

- `RSI_006_Q_SPEC.md` — frozen qualification spec (the authority: repo pool,
  operator set, seeds, budgets, thresholds, verdicts).
- `perturb.py` — frozen seeded perturbation generator (6 generic AST
  operators; same seed → byte-identical mutant list).
- `observe.py` — observation harness (overlay-copy mutation, fresh
  subprocess suite run, `--junitxml` parsing, baseline-relative kill).
- `run_rsi_006_q.py` — orchestrator: `--self-check` (non-executing) or
  `--qualify` (full causal-order run, local only).
- `tests/` — contract tests (frozen properties only, no arm performance).

## Repository pool (pinned, read-only)

more-itertools, cachetools, boltons, pluggy — each at a pinned commit,
verified by SHA before any observation. Checkouts are never modified
(verified by tree hash before/after); mutants run in overlay copies with
`PYTHONDONTWRITEBYTECODE=1` and no installs.

## Running

```bash
# non-executing self-check
python run_rsi_006_q.py --self-check

# full qualification (local only, ~25-40 min, zero API spend)
python run_rsi_006_q.py --qualify --work-dir /tmp/rsi-006-q --workers 2
```

Causal order enforced by the runner: verify SHAs → green deterministic
baselines → discovery mutants from frozen seeds → **seal the archive** →
fresh OS-entropy nonce → confirmation mutants → determinism rerun →
metrics vs frozen thresholds → verdict.

## Verdicts

- `QUALIFIED_RSI_006_SUBSTRATE`
- `NOT_QUALIFIED_RSI_006_SUBSTRATE` (names the failed criterion)
- `INCONCLUSIVE_RSI_006_Q_PRECONDITION_FAILURE` (SHA/baseline/harness)

No tuning under this ID: a failed substrate gets a new qualification ID
with a new frozen spec.

## After qualification

If `QUALIFIED`, the RSI-006 scientific protocol is frozen once — repository
pool, acquisition lineage, hypothesis DSL, rediscovery rule,
false-prediction bound, yield equation, acquisition economics, three
verdicts — and only then does any researcher see the archive.
