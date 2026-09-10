# AIRLOCK-GITHUB-AW-001 — Frozen Receipt

Status: **FROZEN — AIRLOCK_DISCRIMINATED; GITHUB LIVE ARM INCONCLUSIVE**

Freeze base: `3ef34fb0100516e458cb362a7448c78a72da097b`

Original comparator: `AIRLOCK_GITHUB_AW_001.md`

## What completed

The fresh target remained pinned to:

```text
mrphrazer/binary-ninja-headless-mcp
49c39c2d4427b586ce1ec3499baa86c38f980ece
```

The frozen pair preserved the preregistered distinction:

- Candidate A fixed the requested filename-extension behavior and passed ordinary
  functional testing, but violated the repository's pre-existing Ruff lint
  requirement.
- Candidate B made the same functional fix without that violation.

Current, unmodified Airlock evaluated both candidates against repository-owned
acceptance evidence.

Result:

```text
candidate A -> BLOCKED / LINT_OR_TYPECHECK
candidate B -> SURVIVED
pair class  -> AIRLOCK_DISCRIMINATED
```

The verified Airlock-arm run was:

```text
AIRLOCK-GITHUB-AW-001 run 34523934483
Airlock arm: success
Verifier: AIRLOCK_DISCRIMINATED
GitHub AW live arm: PENDING_LIVE_ARM
```

The comparator was then merged by PR #111 at:

```text
3ef34fb0100516e458cb362a7448c78a72da097b
```

Post-merge main remained green:

```text
CI                         34524851599  success
FAR-003                    34524851601  success
AIRLOCK-GITHUB-AW-001      34524851641  success
```

The GitHub Agentic Workflow source compiled successfully and its live-arm setup
artifact was produced.

## What did not complete

The live GitHub Agentic Workflows A/B arm was not executed.

Therefore this experiment does **not** establish whether GitHub Agentic
Workflows would independently discover the same repository-owned Ruff
requirement and withhold Candidate A before human review.

The missing GitHub live arm is an environmental / operating-path inconclusive.
It is not evidence that GitHub failed the comparator.

## Earned result

This experiment earns only the Airlock-side result:

> On this fresh public repository and frozen candidate pair, current Airlock
> independently replayed pre-existing repository-owned acceptance evidence,
> blocked the functionally correct candidate that violated that evidence, and
> allowed the compliant candidate to survive.

That is a concrete confirmation of Airlock's acceptance-evidence behavior on
this case.

## Not earned

Do not claim from AIRLOCK-GITHUB-AW-001 that:

- Airlock has a demonstrated moat over GitHub Agentic Workflows.
- GitHub Agentic Workflows would publish Candidate A.
- GitHub lacks repository-aware validation, CI, review, branch protection,
  threat detection, or safe-output controls.
- Airlock always discovers every maintainer requirement.
- One successful fresh repository establishes general superiority.

The cross-system category claim remains unearned because the GitHub live arm
did not run.

## Why this experiment is closed

Further work on this comparator would require changing the user's established
operating path rather than testing a new Airlock invariant.

That is not a reason to add an Airlock feature or weaken the comparator.

Freeze the partial result instead.

## Reopen condition

Reopen AIRLOCK-GITHUB-AW-001 only if one of these becomes true:

1. the same GitHub live A/B arm can be executed cleanly within the permitted
   operating routine;
2. GitHub exposes an equivalent externally observable pre-publication decision
   that can be tested without changing the frozen pair; or
3. a new external comparator directly challenges Airlock's repository-owned
   acceptance-evidence boundary.

Otherwise leave this receipt frozen and return Airlock to market-learning mode.
