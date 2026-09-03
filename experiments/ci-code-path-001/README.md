# CI-CODE-PATH-001 — complete code-failure path

This is the first post-Doctor dogfood of the complete code-repair control path:

`Recorder → CODE_REPAIR_ALLOWED → Doctor → isolated candidate → ordinary Airlock evaluation`

The fixture is a real temporary Git repository with a deliberately incorrect retry boundary and a real failing `unittest` process. Its provider-shaped read adapter gives Recorder the exact workflow metadata and bytes emitted by that process. Recorder must independently classify the evidence and seal `CODE_REPAIR_ALLOWED`; no receipt is fabricated by the harness.

Doctor must then reproduce the configured failure before starting its subprocess worker, keep the worker in an isolated worktree, strip attempted GitHub/release credentials, admit only the source-file fix, and leave the trusted red baseline unchanged. The resulting candidate is run through the same protected-path, target, static, regression, and evidence-sufficiency functions used by ordinary Airlock evaluation.

The worker is deliberately deterministic. This is a positive control for product composition, not evidence that Hermes or another model can diagnose arbitrary CI failures. No live GitHub API call, retry, push, PR, merge, deployment, workflow edit, or baseline edit occurs.

Run a fresh dogfood copy:

```bash
PYTHONPATH=src python experiments/ci-code-path-001/run_ci_code_path_001.py --out /tmp/ci-code-path-001
```

Verify the committed receipt and survivor patch offline:

```bash
PYTHONPATH=src python experiments/ci-code-path-001/run_ci_code_path_001.py --verify
```

`CI_CODE_PATH_001_VERIFICATION.key` is intentionally public fixture material. Its HMAC proves the committed result and nested receipts still match this evidence package; it is not a claim of secret-key identity.

