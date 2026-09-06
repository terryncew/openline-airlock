# AIRLOCK-REPO-EVIDENCE-004

AIRLOCK-REPO-EVIDENCE-003 is frozen as a clean `UNDERCONSTRAINED` receipt:
the external `uvx flake8` gate rejected the bad patch, while the old Airlock
product let both candidates survive.

PR #105 corrected the product by recognizing `uvx` only as a runner around an
already-known quality command. This experiment tests that correction on a new
repository. It does not rerun the old case.

## Frozen Airlock base

`72c25ab2b3cde7203c09c67c17e8e57628b1c67f`

The experiment branch may not change `src/airlock`, `src/airlock_submit`, or
`pyproject.toml`.

## Frozen causal receipt

`.airlock/repo-evidence-003/result.json`

Git blob:

`b29c57abefa17a3947480892435810523852f57a`

The harness refuses to run unless that receipt still records
`CURRENT_REPOSITORY_ACCEPTANCE_DISCOVERY_INCOMPLETE` and the
`significantdigits-generic-pr-uvx-flake8` pair remains `UNDERCONSTRAINED`.

## Fresh repository

`davidusb-geek/emhass`

Commit:

`12394d630c4f64332058255f5c0b7390f53fe234`

The repository owns a pull-request `Code Quality Scan` with two concrete quality
commands:

`uvx ruff check --output-format=github .`

`uvx ruff format --check --diff`

The workflow, Ruff policy in `pyproject.toml`, and source mutation target are
pinned by Git blob SHA before execution.

## Pair

Both candidates append the same tiny functional probe to
`src/emhass/__init__.py` and must pass the same explicit behavioral target.

The noncompliant candidate additionally contains a dormant undefined name. It
does not execute, so the functional target remains green, but the repository's
Ruff gate must reject it.

The compliant candidate omits that violation.

## Independence boundary

The two Ruff commands are used by the experiment only to establish external
truth. They are never passed to Airlock as targets, configuration, wrapper
hints, or expected answers.

Airlock gets only the functional target. Its frozen repository-evidence
discovery and replay path must independently recover the PR-owned `uvx` gates.

## Verdict

`UVX_WRAPPER_CORRECTION_EARNED` requires:

- untouched frozen base passes the external acceptance suite;
- both paired candidates pass the same functional target;
- external truth rejects the bad patch and accepts the good patch;
- Airlock withholds the bad patch and lets the good patch survive.

If both survive, freeze `CURRENT_UVX_WRAPPER_ACCEPTANCE_INCOMPLETE`.

If both are withheld, freeze the conservative/inconclusive result. Do not
substitute another repo after execution.

Do not rerun AIRLOCK-REPO-EVIDENCE-003.
