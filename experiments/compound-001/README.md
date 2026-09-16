# COMPOUND-001 — implementation only (precontact)

New study. Not RSI-006-Q7. Does not reopen RSI-006 or reinterpret the
RSI-006-Q6 NO-GO. Frozen RSI-006 standing is unchanged.

## Question

Within a frozen small software-maintenance task distribution, a
three-generation horizon, and a bounded direct-dollar budget, can
independently accepted improvements to an AI research/work method lower the
acquisition-cost-adjusted price of later independently verified work?

Amortization and successive improvement are adjudicated separately.
Repeatedly reusing one trick is not compounding.

## Status of this branch

Implementation of the frozen contract only. No scientific contact, no live
calibration, no paid model invocation. The precontact budget-enforcement
feasibility gate returns `NO_GO_BUDGET_ENFORCEMENT`: static/config
inspection of the repo's Hermes/provider invocation path shows no
enforceable per-invocation billable maximum (no max output tokens, no
bounded retry/API-call count; timeout alone does not bound tokens), and the
frozen contract forbids building a new provider gateway to rescue the
study. The implementation encodes that gate rather than working around it.

## Files

- `experiments/compound-001/run_compound_001.py` — the single COMPOUND
  runtime module (contract machinery: metering, reservation arithmetic,
  ledgers, provisional selection, economic adjudication, partitions,
  lineage integrity, feasibility gates). CLI: `--check-feasibility`,
  `--verify-prereg`, `--complexity`.
- `experiments/compound-001/README.md` — this file.
- `tests/test_compound_001.py` — deterministic contract tests (fake
  fixtures only).
- `.airlock/compound-001/preregistration.json` — frozen contract.
- `.airlock/compound-001/price-table.json` — frozen rates (SEARCH-004
  rates, compound schema).
- `.airlock/compound-001/baseline-method.md` — frozen baseline method
  artifact (track A; common fork state for B/C).
- `.airlock/compound-001/task-schedule.json` — frozen deterministic
  task-ID schedule (seed commitment `c001-seed-commitment-9f2e4a1b7d`).

No changes to `src/airlock/**`. No new dependencies, DB, or daemon.

## Reuse

Cost-metering semantics mirror
`experiments/airlock-search-004/run_search_004.py` (token classes,
total-consistency, model/provider alias, service-tier, long-context
aggregate guard; provider estimated price untrusted). Authority-separation
and harness-fingerprint ideas follow Nightshift; no persistent writable
worker state is inherited — every contact requires a fresh worker session.
