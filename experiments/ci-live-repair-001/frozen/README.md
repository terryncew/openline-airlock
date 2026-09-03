# CI-LIVE-REPAIR-001 — frozen live proof

This directory freezes the first live GitHub Actions run that earned the complete bounded CI repair path.

## Earned verdict

`LIVE_CODE_REPAIR_PATH_EARNED`

Observed chain:

`failed GitHub CI -> Recorder -> CODE_REPAIR_ALLOWED -> one Hermes Doctor attempt -> ordinary Airlock evaluation -> READY_FOR_REVIEW`

The independent verifier returned `CI-LIVE-REPAIR-001: PASS`.

## Bound execution

Source run: `33728276872`, attempt `1`  
Source head: `7d9d36609744b6bcc16fc543ec387e8872836f86`  
Consumer run: `33728294550`, attempt `1`

Doctor decision: `READY_FOR_REVIEW`  
Doctor reason: `REPRODUCED_FAILURE_REPAIRED`

Candidate changed exactly:

`experiments/ci-code-path-001/fixture/src/retry_policy.py`

The worker exited `0` and did not time out.

## Authority boundary

The frozen result records all of the following as false:

- GitHub write authority
- merge authority
- deployment authority
- workflow-repair authority
- retry authority
- baseline-change authority

No candidate was pushed, no PR was opened by Airlock, and nothing was merged automatically.

## Frozen files

`CI-LIVE-REPAIR-001-run-7.zip` is the exact GitHub Actions artifact uploaded by consumer run `33728294550`.

Artifact SHA-256:

`e51440aacf108c585b8ae3347b7216c31b511adf2f8fdb415784eae2e428eb75`

`CI_LIVE_REPAIR_001_RESULT.json` is the independently verified machine-readable result extracted from that artifact.

Result SHA-256:

`5989e77b3263cf6ef5a84bb4fe38595249aa6d8f1b41101ea2d7ea2b250955e8`

The adjacent `.sha256` file is the verifier-emitted digest and recomputes exactly.

## Claim boundary

This proves the live code-failure handoff for this bounded fixture and execution:

Recorder identified a real code regression, authorized code-repair generation, Doctor made one isolated attempt, and ordinary Airlock evaluation admitted the resulting candidate to local review.

It does not grant Airlock GitHub write, PR, merge, deployment, workflow-repair, or retry authority, and it does not prove every future CI failure will be repairable.
