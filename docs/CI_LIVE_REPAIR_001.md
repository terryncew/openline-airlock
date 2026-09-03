# CI-LIVE-REPAIR-001 — real Recorder → Hermes → Doctor dogfood

This is a live product dogfood, not a new search experiment. It tests the merged one-command path against real GitHub Actions evidence and one real pinned Hermes worker.

The source failure is deliberately narrow. A disposable branch named `dogfood/ci-live-repair-*` receives a marker file. `AIRLOCK-CI-LIVE-REPAIR-001 expected code failure` runs the already-frozen broken retry-policy fixture and must fail with a real assertion failure. The main branch stays green.

When that workflow completes red, `AIRLOCK-CI-LIVE-REPAIR-001 live Hermes repair` starts automatically. It checks out the exact failed SHA, installs the current Airlock package, replaces only the receiver-local `.airlock/config.json` with the dogfood rules, installs Hermes at commit `29112bef099274229cadff79cdff7bf7b99c4b77`, and runs:

```console
airlock nightshift --ci <failed-run-url> --repair-ci --budget 1.00 --repo .
```

The GitHub token is read-only (`contents: read`, `actions: read`) and is used by Recorder only. Doctor strips GitHub credentials before the worker boundary. Hermes receives `HERMES_HOME`; its single OpenAI credential is materialized inside that isolated home and is not forwarded as an ambient worker environment variable.

The dogfood rules protect the product source, tests, workflows, Airlock policy, all other frozen experiments, the fixture tests, and the repair worker. The only admissible changed path is:

`experiments/ci-code-path-001/fixture/src/retry_policy.py`

A separate verifier then rechecks the sealed Recorder and Doctor receipts, exact run/attempt/head binding, absence of retry/GitHub-write/merge/deploy/workflow authority, unchanged trusted HEAD, exact one-file patch scope, and an independent ordinary Airlock protected-path + target + regression + evidence-sufficiency evaluation.

The live path earns `LIVE_CODE_REPAIR_PATH_EARNED` only if Recorder returns `CODE_REPAIR_ALLOWED`, Doctor starts one worker and returns `READY_FOR_REVIEW`, and the independently evaluated candidate survives. The candidate is preserved as a patch in the workflow artifact. Nothing is pushed, no PR is opened, and no merge or deployment is authorized.

The expected red source workflow is evidence input, not a product regression. The consumer workflow is the gate that must finish green.
