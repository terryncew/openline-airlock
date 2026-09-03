# Airlock v0.4.0 — verified Nightshift demo

This directory turns the frozen `NIGHTSHIFT_COLD_ADOPTION_EARNED` receipt into a short terminal demo.

The underlying run was live. Released Airlock v0.4.0 cold-initialized the frozen `terryncew/openline-otel` repository, used its ordinary 32-test pytest baseline, accepted the generated Starter Rules unchanged, then ran one generation with pinned real Hermes. Hermes changed one source file. Airlock independently reran the checks and the operator-owned measurement, measured 2423 → 2421 source lines, admitted one unique winner, and did not move the starting branch.

The worker did not control the objective, evaluator, or promotion decision.

## Verify the evidence

```bash
python demo/nightshift-v040/show.py --verify-only
```

Expected:

```text
NIGHTSHIFT_COLD_ADOPTION_EARNED
```

`show.py` checks the frozen report and generation SHA-256 values against `dogfood/nightshift-cold-adoption-v040/receipt.json` before it prints anything.

## Record the 30-second terminal version

From the repository root:

```bash
clear
python demo/nightshift-v040/show.py --pace 0.8
```

Record only the terminal window. The replay is generated from the frozen receipt; it is intentionally not presented as a model running live during playback.

The story on screen is the product:

```text
outside repo
32 tests green
cold Airlock init
real Hermes attempt
1 file / 4 changed lines
Airlock independently measures 2423 -> 2421
UNIQUE_WINNER
worker controls objective/evaluator/promotion: NO/NO/NO
main moved: NO
```

## Claim boundary

This proves compatibility and the authority split for one real outside-repo Nightshift generation using released Airlock v0.4.0. It does not prove superior economics: the worker did not report provider spend. It also does not prove zero-config Nightshift: the operator still had to explicitly define and commit the objective before worker contact.

That remaining friction is intentional evidence for the next product decision rather than something this demo hides.
