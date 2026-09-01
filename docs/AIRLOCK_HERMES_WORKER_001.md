# AIRLOCK-HERMES-WORKER-001

Hermes is a worker. Airlock remains the admission boundary.

The built-in adapter invokes Hermes in scripted one-shot mode:

```text
hermes -z "{prompt}"
```

Airlock's existing tournament/swarm path gives that worker an isolated candidate worktree, then evaluates the resulting patch using repository-owned checks and protected paths. The worker does not choose the evaluator, rewrite Airlock's protected config, or receive Airlock release authority.

## Credential boundary

The built-in Hermes adapter forwards only `HERMES_HOME` from the maintainer environment. It does not automatically forward a catalog of model-provider keys.

A key-based setup must name at most one additional provider credential in the protected `.airlock/config.json`, for example:

```json
{
  "providers": {
    "hermes": {
      "command": ["hermes", "-z", "{prompt}"],
      "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"]
    }
  }
}
```

Trying to configure `HERMES_HOME` plus multiple provider credentials fails closed.

Repository/release credentials remain denied by Airlock's existing worker-environment scrub, including `GITHUB_TOKEN`, `GH_TOKEN`, `SSH_AUTH_SOCK`, `AIRLOCK_VERIFICATION_KEY`, `OPENLINE_RELEASE_KEY`, and release/deploy/signing-key patterns. Worker Git push is disabled and `AIRLOCK_RELEASE_AUTHORITY=ABSENT`.

## Claim boundary

This adapter constrains environment-variable forwarding. It is not a filesystem sandbox. `HERMES_HOME` is trusted principal-side state and may itself contain auth material; Airlock does not inspect or redact files inside it. Native worktree execution also does not prevent a hostile process from probing other readable host paths.

Therefore the earned claim here is narrower: Airlock does not spray ambient provider-key environment variables into the Hermes worker, and the worker does not receive Airlock's repository/release authority through the adapter.

A real installed-Hermes unattended run is still required before claiming an end-to-end live Hermes demonstration.
