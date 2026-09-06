# AIRLOCK-REPO-EVIDENCE-002

Verdict: **INCONCLUSIVE_EXTERNAL_TRUTH**

| Case | External truth | Noncompliant | Compliant | Pair |
| --- | --- | --- | --- | --- |
| percentify-generic-pr-flake8 | PASS | BLOCKED | SURVIVED | DISCRIMINATED |
| ahrs-generic-pr-flake8 | INCONCLUSIVE_EXTERNAL_TRUTH | — | — | INCONCLUSIVE |
| lwe-pr-flake8 | PASS | BLOCKED | SURVIVED | DISCRIMINATED |
| sqlparse-generic-pr-ruff-wrapper | PASS | BLOCKED | SURVIVED | DISCRIMINATED |

The external verifier is ground truth only. It was never supplied to Airlock as a target, regression check, or benchmark rule.

The harness ran every frozen case even if an earlier pair already falsified the aggregate claim.

AIRLOCK-SWE-GATE-001 and AIRLOCK-REPO-EVIDENCE-001 were not rerun.
