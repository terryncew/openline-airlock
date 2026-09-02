# SEARCH-004 — Unattended Yield

SEARCH-003 showed that autonomous Hermes could leave an already-earned improvement behind and find fresh verified value. SEARCH-004 tests the product consequence directly:

> Can Airlock remove the developer from task-picking without making the economics worse?

The first workflow attempt was an infrastructure-only run: Airlock rejected the
frozen provider environment before Arm A could launch a worker. Amendment
`SEARCH-004-INFRA-001` repairs that controller handoff and the latent raw-usage
receipt projection before the first experimental worker contact. It does not
change either prompt, the opportunity surface, cost rules, resource ceilings,
endpoint, or verdict thresholds.

Two arms start from the same small repository, the same nine active opportunities, the same GPT-5.6 Sol model, the same pinned Hermes v0.21.0 commit, the same starting Hermes harness fingerprint, the same evaluator, and the same contact/spend ceilings.

**Arm A — Airlock unattended** receives one standing instruction: `Improve this repo. Keep finding the next useful improvement.` No maintainer selects a concrete task. Accepted dimensions retire to zero marginal value only inside Arm A.

**Arm B — Maintainer-guided Hermes** receives the committed task sequence in `.airlock/search-004/guided-tasks.json`. Each actual worker contact counts as one maintainer task assignment. Accepted dimensions retire only inside Arm B. The schedule is frozen before either experimental arm begins.

The opportunity pools are independent clones. This is an A/B evaluation, not a race to consume one shared pool.

## Primary endpoint

`distinct verified improvements / metered USD`

Provider-reported `estimated_cost_usd` is retained only as untrusted metadata. Airlock reads the Hermes `--usage-file`, hashes the raw usage file, validates every known token class, and recomputes cost against `.airlock/search-004/price-table.json`.

A tiny real model preflight must prove non-zero input/output usage and non-zero independently reconstructed cost before either arm contacts Hermes. Missing usage, zero usage, an unknown token class, an unexpected model/provider/service tier, or pricing that cannot be reconstructed invalidates the run as `COST_TELEMETRY_FAILURE` and stops further contact.

Hermes v0.21.0 reports aggregate usage for a one-shot run. GPT-5.6 Sol has a per-request long-context price step above 272K prompt tokens. Therefore SEARCH-004 also fails closed if aggregate prompt tokens for one Hermes contact exceed 272K: at that point aggregate telemetry alone cannot prove which per-request multiplier applies.

## Product endpoint

`maintainer task assignments required`

Arm A must remain at zero. Arm B records one intervention for every concrete maintainer-selected target actually sent to Hermes. There is no live yield dashboard or running tally during the experiment.

## Frozen verdicts

- `UNATTENDED_YIELD_GAIN`: `Y_A >= 1.15 × Y_B`, with `T_A = 0` and `T_B >= 1`. If `Y_B = 0` and `Y_A > 0`, this verdict is automatic.
- `UNATTENDED_YIELD_PARITY`: `0.85 × Y_B <= Y_A < 1.15 × Y_B`, with `T_A = 0` and `T_B >= 1`.
- `GUIDANCE_YIELD_ADVANTAGE`: `Y_A < 0.85 × Y_B`.
- `NULL_YIELD`: both arms produce zero verified improvements.
- `COST_TELEMETRY_FAILURE`: the denominator cannot be trusted; no economics claim is allowed.

The experiment is bounded to four worker contacts and a $5 contact-start spend ceiling per arm. All in-flight metered spend is counted even if the last contact crosses the ceiling.
