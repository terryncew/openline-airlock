# CI Flight Recorder

`airlock ci` answers a narrow question before a coding agent reacts to red GitHub Actions CI:

> What does this exact failed execution authorize us to do next?

```bash
airlock ci https://github.com/OWNER/REPO/actions/runs/123456789
```

Recorder is read-only. It retrieves one completed GitHub Actions run attempt, freezes the available run/job/step/annotation/workflow/log evidence in memory, hashes that source bundle, applies a versioned deterministic rule set, seals the resulting receipt with Airlock's existing local HMAC mechanism, and prints a routing decision.

Possible dispositions are:

- `CODE_REPAIR_ALLOWED` — every primary blocking finding is a concrete code regression. This authorizes only an isolated candidate-generation process under ordinary Airlock boundaries.
- `RETRY_RECOMMENDED` — every primary blocking finding is environment/external-service failure and an equivalent later attempt supports transient recovery.
- `REPORT_ONLY` — evidence is unresolved, mixed, incomplete, contradictory, or workflow configuration is implicated.
- `NO_ACTION` — the analyzed run contains no failed blocking finding.

These dispositions never authorize merge, deployment, a trusted-baseline change, or workflow repair.

## Exact attempts

A URL ending in `/attempts/N` selects that exact attempt. A normal run URL or numeric run ID selects GitHub's current completed attempt. Evidence from different attempts is never blended. A later passing attempt may support `stability: TRANSIENT` only when the run identity, workflow hash, head SHA, event/ref semantics, job identity, and runner labels remain equivalent. It never proves a patch safe.

Recorder preserves GitHub's provider run head SHA/ref separately from triggering/execution identity. Unknown fields stay `UNKNOWN`.

## `patch_implicated`

`YES`, `NO`, and `UNKNOWN` are substantive states. `NO` is earned only by a deterministic non-code rule whose direct evidence places the blocking failure outside candidate-code execution, such as a runner filesystem/capacity failure. A passing rerun alone never earns `NO`.

## Missing evidence

GitHub-authoritative absence or expiry (for example a job log that is no longer available) is recorded as missing evidence and can produce a valid `UNRESOLVED` / `REPORT_ONLY` receipt. If Recorder itself cannot retrieve authoritative evidence that should be retrievable, it seals nothing and exits `3`; authentication, authorization, network, and provider failures exit `4`.

## Output

Text is the default human receipt. The canonical signed JSON is always written to `--out PATH` or to `.airlock/ci/` when a local repository is available.

```bash
airlock ci 123456789 --repo OWNER/REPO --format json --out receipt.json
```

Credentials are read from `GH_TOKEN`, then `GITHUB_TOKEN`, or from an environment-variable name configured as `.airlock/config.json` → `github.read_token_env`. Secret values are never written to receipts.

The receipt's HMAC proves only that the local Airlock installation sealed these bytes and they have not changed since. GitHub does not sign Airlock's classification.

## Examples

A named failing test with a concrete deterministic code signal can route to `CODE_REPAIR_ALLOWED`; Airlock may then let a worker generate an isolated candidate, but existing protected paths and independent checks still decide whether it deserves review.

The frozen runner-filesystem fixture modeled on the PR #60 incident routes to `ENVIRONMENT / RUNNER_FILESYSTEM`. When a later equivalent attempt passes, the receipt reports `TRANSIENT` and `RETRY_RECOMMENDED`; it grants no code-repair authority and makes no claim that the patch is safe.
