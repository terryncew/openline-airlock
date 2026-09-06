# AIRLOCK-REPO-EVIDENCE-003

AIRLOCK-REPO-EVIDENCE-002 remains a valid **INCONCLUSIVE_EXTERNAL_TRUTH**
receipt: three interpretable fresh pairs were discriminated, while the AHRS
control failed its own external-truth precondition.

This experiment does not rerun or repair that receipt. It adds one new frozen
repository and asks whether the current product can earn a fourth interpretable
discrimination.

## Frozen Airlock base

`2245907bcb8bb581dd520565457383d5098ecd88`

The experiment branch may not change `src/airlock`, `src/airlock_submit`, or
`pyproject.toml`.

## Frozen prior receipt

`.airlock/repo-evidence-002/result.json`

Git blob:

`97414b9b6ce78f33aa9dde5de8c1ce6eec6b4af0`

The harness refuses to run the new case unless that receipt still says exactly:
three `DISCRIMINATED`, one `INCONCLUSIVE`, zero underconstrained, zero inverted,
with the same four case identities.

## Fresh case

`verificarlo/significantdigits`

Commit:

`05769c5ba43fadebaee933c5d0cf2c5b5d0f69eb`

Its PR workflow is generically named `Python application`. The strict
undefined-name acceptance gate is nested inside it and executed as:

`uvx flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --extend-exclude=.venv,venv`

The workflow and relevant source/config/lock files are frozen by Git blob SHA
before execution.

## Pair

Both candidates add the same tiny functional probe and must pass the same
explicit import/behavior target.

The noncompliant candidate additionally introduces a dormant undefined name in
an existing source module. That should not affect the functional target, but it
must violate the repository's strict flake8 gate.

The compliant candidate omits that violation.

## Independence boundary

The external `uvx flake8` command proves ground truth only. It is not supplied
to Airlock as a target, regression check, configuration rule, wrapper hint, or
expected answer.

Airlock gets only the functional target. Its current frozen repository-evidence
discovery/replay path must decide whether the additional repo-owned acceptance
constraint counts.

## Verdict

If the fresh pair is `DISCRIMINATED`, this experiment may report
`CUMULATIVE_FOUR_INTERPRETABLE_DISCRIMINATIONS` because the three frozen 002
wins were re-verified by receipt and the new case supplies the fourth.

That does **not** change AIRLOCK-REPO-EVIDENCE-002's own verdict.

If both candidates survive, the fresh result is
`CURRENT_REPOSITORY_ACCEPTANCE_DISCOVERY_INCOMPLETE`.

If both are withheld, that is conservative/inconclusive, not success.

Do not substitute another repo after execution. Freeze the result first.
