# AIRLOCK-REPO-EVIDENCE-002

AIRLOCK-REPO-EVIDENCE-001 found a clean underconstraint: a generic
`python-app.yml` pull-request workflow contained a nested quality gate, but
Airlock's workflow-surface detector stopped at the outer filename/name and never
reached it.

PR #102 corrected that class of failure. Airlock now treats the workflow's outer
name as a hint rather than a prerequisite and can discover quality evidence
from nested PR jobs, steps, and commands.

This experiment is the fresh falsifier for that corrected product.

## Frozen product

`f3a2d1477636100add061b2fc13585a43552a0ce`

The experiment branch is not allowed to modify `src/airlock`,
`src/airlock_submit`, or `pyproject.toml`.

## Four fresh repositories

None appeared in AIRLOCK-SWE-GATE-001 or AIRLOCK-REPO-EVIDENCE-001.

1. `Ad-meliorael/percentify` — generic `python-app.yml` / `Python application`;
   strict flake8 nested in the PR workflow.
2. `Mayitzin/ahrs` — generic `python-app.yml` / `Python application`;
   strict flake8 nested in the PR workflow.
3. `llm-workflow-engine/llm-workflow-engine` — committed flake8 policy plus
   PR lint/test workflow.
4. `andialbrecht/sqlparse` — generic `python-app.yml` / `Python application`;
   Ruff is encoded behind `uv run --group dev`, with the pinned
   `pyproject.toml` defining the Ruff policy.

Every case freezes the upstream commit and the files that carry the relevant
acceptance evidence before execution.

## Pair construction

Each case gets two one-commit source patches.

Both add the same tiny functional behavior and must pass the same explicit
functional target.

The noncompliant patch also contains a dead-code undefined name. It remains
functionally inert, but the repository's lint policy must reject it.

The compliant patch contains no such violation.

The experiment first proves the repository's acceptance verifier is green on
the frozen base. This is a deliberate correction to the REPO-EVIDENCE-001
harness: a nominally "good" control is not useful if the external verifier was
already red before either candidate existed.

## Independence boundary

The external verifier establishes ground truth only.

It is **not** supplied to Airlock as a target, regression check, configuration
rule, or expected answer. Airlock gets the functional target and must discover
the repository's additional acceptance evidence itself.

For the sqlparse case, external truth runs `ruff check sqlparse/` directly
against the pinned project configuration. The repository-owned workflow encodes
the equivalent constraint as `uv run --group dev ruff check sqlparse/`. Airlock
is told neither command.

## Verdict

The strong claim is earned only if all four fresh pairs are `DISCRIMINATED`:
the noncompliant candidate is withheld and the compliant candidate survives.

One clean `UNDERCONSTRAINED` pair falsifies the claim. It stops the claim, not
the harness: the remaining frozen cases still execute so the downstream receipt
is complete.

`OVERCONSERVATIVE_OR_INSUFFICIENT` is not success. Neither is `INVERTED`.

Do not rerun AIRLOCK-SWE-GATE-001 or AIRLOCK-REPO-EVIDENCE-001. If this result
is negative, freeze it before touching the product again.
