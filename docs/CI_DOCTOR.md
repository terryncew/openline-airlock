# CI Doctor

CI Doctor turns a sealed `CODE_REPAIR_ALLOWED` CI Recorder receipt into at most one isolated repair candidate.

Direct Doctor use:

```console
airlock doctor .airlock/ci/OWNER-REPO-RUN-attempt-N.json --budget 2
```

Use `--model NAME` to select a configured Airlock adapter. The default is `hermes`.

The one-command Nightshift handoff keeps classification and repair authority separate while removing the manual receipt-routing step:

```console
airlock nightshift --ci https://github.com/OWNER/REPO/actions/runs/RUN_ID --repair-ci --budget 2
```

`--repair-ci` is explicit local repair authority. It requires `--ci` and a positive budget, is mutually exclusive with `--retry-ci`, and always runs exactly one Doctor attempt. A single `--profiles PROFILE` value is preserved as `hermes@PROFILE`; multi-agent or multi-profile repair is refused instead of silently choosing a worker. If Recorder returns anything other than `CODE_REPAIR_ALLOWED`, Doctor does not start and ordinary Nightshift does not start.

Doctor fails closed in this order:

1. Verify the local Airlock signature and canonical CI receipt.
2. Require `CODE_REPAIR_ALLOWED` with code-repair authority and no retry, merge, deployment, workflow-repair, or baseline authority.
3. Bind the receipt to the local GitHub repository and exact repair-base commit. Pull-request receipts use the authoritative triggering head SHA when present; push receipts use the provider run head SHA.
4. Reproduce the same failure class with the repository's configured Airlock checks before any agent spend. A test receipt must reproduce in the regression checks, lint/type in static checks, and compile/build in target checks. If it does not reproduce, Doctor stops with `NO_LOCAL_REPRODUCTION` and starts no worker.
5. Start one isolated candidate with GitHub credentials stripped and Git push disabled.
6. Reject Git configuration changes, protected-path changes, empty patches, and candidates that do not make every configured check green.
7. If the candidate earns admission, create only a local `airlock/doctor-ready/...` branch and a signed Doctor receipt. Doctor never pushes, opens a PR, reruns CI, merges, deploys, or edits the trusted baseline.

The Doctor receipt binds the source CI receipt hash, source evidence-bundle hash, exact run and attempt, repair base, local reproduction, prompt hash, candidate commit, changed paths, configured checks, and the absence of GitHub write/merge/deployment/workflow authority.

`READY_FOR_REVIEW` means an isolated candidate repaired a locally reproduced failure and passed the configured Airlock checks. It is still only a candidate for human review.
