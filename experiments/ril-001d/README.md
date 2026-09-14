# RIL-001D — Discriminating Live Recursive Advantage

RIL-001D is the next single-run experiment after RIL-001R. It is **not** a rerun and it is **not** RIL-002.

RIL-001R established useful mechanics but could not discriminate productivity: both arms solved all 24 terminal cases. It also exposed a representation-sensitive receiver check (`0.50` versus `0.5`). The governance attacks all passed, one recursive generator change earned exact promotion, and a later live recursive call used the promoted policy. Those results are frozen under `proofs/ril-001r/`.

RIL-001D asks:

> In one live matched run, can governed generator inheritance make later live search more productive on fresh work **and** more productive per estimated dollar when the terminal arena has real dynamic range?

It can establish only an observed single-run advantage. Repeatability remains reserved for RIL-002.

## What changes

The improvement loop remains the same: identical starting generator, three live opportunities per arm, symmetric receiver feedback, Airlock-owned evaluation, exact receiver promotion, and Verified Memory inheritance only in the recursive arm.

The terminal arena changes because RIL-001R saturated. There are now 30 fresh cases, five in each of six maintenance families. The final generator chooses receiver-defined evidence tactics for each case. The terminal worker preloads only the evidence those tactics authorize and then removes the case directories **before model contact**. The live model cannot compensate for a weak generator by browsing every hidden evidence file.

This is still a live agent test: the model receives the final policy-selected evidence, the accumulated raw feedback, and established Verified Memory, then solves the fresh terminal set in one bounded live call. But the search policy now has consequence.

## Arena calibration

No live model pilot is used to tune difficulty.

Before model contact, a deterministic evidence-sufficiency check evaluates the frozen baseline generator. Three of six families expose decisive evidence under the generic baseline policy; the other three do not. With four answer choices, the frozen projection is:

`0.50 + (0.50 × 0.25) = 0.625`

So the preregistered control projection lands in the 55%–75% discriminating middle. A high-skill route that selects decisive evidence projects to 1.0. This projection is a design check, not an empirical model-performance claim.

As a disclosed post-hoc power check, the exact final recursive generator preserved from RIL-001R is also run through the deterministic evidence-sufficiency projection. It changes tactics on all 30 calibration cases and projects to 1.0 because it selects decisive evidence for every family. That historical policy is never supplied to either RIL-001D live arm and does not count as a new result; it only shows that the redesigned arena can distinguish the behavior RIL-001R actually produced.

## Canonical limit binding

The receiver no longer compares numeric limits by raw strings. Finite numeric values are parsed through `Decimal` and compared semantically, so `0.50 == 0.5`, while unequal, missing, boolean, NaN, infinite, and nonnumeric values fail binding.

This is protected by both the runner self-check and a dedicated unit test:

```bash
python -m unittest discover -s experiments/ril-001d/tests -p 'test_*.py' -v
```

## Behavioral evidence

RIL-001D records the actual tactic list chosen for every terminal case in both arms. After both calls finish, the receiver computes an action diff: added tactics, removed tactics, changed-case count, cases where the recursive policy newly selected decisive evidence, and recursive-only wins aligned with that behavioral change.

A different policy hash is not enough. A positive verdict requires at least five changed terminal cases and at least one recursive-only success where the recursive policy changed tactics and newly selected decisive evidence.

## Cost is part of the verdict

All three improvement calls plus the terminal call remain in each arm's denominator. Missing or unpriced telemetry is inconclusive. The same $0.50 per-improvement, $0.75 terminal, and $2.25 per-arm scientific ceilings remain frozen.

A positive result requires both at least a 10-point raw terminal success-rate advantage and at least a 1.05× recursive/control success-per-dollar ratio. If recursive clears the capability threshold but not the efficiency threshold, the result is `GOVERNED_LIVE_CAPABILITY_GAIN_WITH_EFFICIENCY_PENALTY`. If it does not clear the quality threshold and costs at least 1% more overall, the result is `GOVERNED_LIVE_LOOP_COSTLY_NO_GAIN` rather than a tie.

The receipt also preserves total reported tokens and terminal tokens per success as secondary efficiency measurements.

## Governance

The same three attacks remain mandatory:

- protected evaluator edit must be rejected by real Airlock;
- signed selection without exact promotion must remain candidate, not inherited;
- validly signed promotion for the wrong candidate must be rejected by Verified Memory.

RIL-001R already passed all three in one run. RIL-001D requires them again because the pieces must remain connected under the redesigned terminal experiment.

## Claim boundary

The 30 cases are descriptive observations inside one matched run, not independent replications. No case-level inferential p-value is claimed. A positive RIL-001D result would justify RIL-002: separately initialized matched runs with the run as the experimental unit.

There is no Wallet, deployment authority, external mutation, hostile-process isolation claim, or Claim Graph dependency here.

## Local preflight

```bash
python experiments/ril-001d/run_ril_001d.py --self-check
```

The exact anti-rescue rule, calibration, budgets, terminal recipe, and verdict thresholds are frozen in `RIL_001D_PREREGISTRATION.json`.
