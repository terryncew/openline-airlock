# AIRLOCK-V0.3-001

Status: **RELEASE INTEGRATION — merge candidate**

Base: `terryncew/openline-airlock@84dd117701080ab7de6d090ec574bb896af51365`

## Goal

Stop adding isolated product nouns and turn the merged Airlock pieces into one release-shaped workflow.

The v0.3 user surface is:

```text
init → solve → autopilot → inbox → review
```

`swarm`, `run`, and `verify` remain available as advanced/lower-level controls.

## What this increment changes

- Bumps the package to `0.3.0`.
- Makes top-level `airlock --help` show the canonical workflow instead of hiding newer commands behind dispatch shortcuts.
- Makes `airlock --version` originate from the installed public router.
- Consolidates the unreleased Solve, Autopilot, Inbox, and Review work into one `0.3.0` changelog entry.
- Rewrites onboarding around the five-command loop while preserving the separate public-fork contribution path.
- Adds a repository release verifier and CI installed-wheel smoke for the public router.
- Freezes current v1 schema names for the 0.3.x line.

## Schema freeze

The following identifiers keep their present meaning throughout 0.3.x:

- `airlock.config.v1`
- `airlock.run.v1`
- `airlock.verification.v1`
- `airlock.swarm.v1`
- `airlock.autopilot.v1`
- `airlock.autopilot.run.v1`
- `airlock.inbox.v1`
- `airlock.review.v1`

Backward-compatible optional fields are allowed. A meaning change that would make an existing reader unsafe requires a new schema name.

## Boundary

This is an integration/release increment, not evidence that every execution boundary has been exercised.

In particular, `AIRLOCK-PUBLIC-COLD-ADOPTION-001` remains FAIL. v0.3 must not claim the live public-fork submission path is proven until a genuinely separate fork enters through `/airlock submit`, survives live Actions, and Airlock itself opens the correctly bound PR.

## Release sequence

1. Merge this branch.
2. Require green CI on the release commit.
3. Tag that exact commit `v0.3.0`.
4. Run the first unattended GitHub execution from the tagged release.
5. Freeze features and use outside-repository adoption runs as the next source of product changes.
