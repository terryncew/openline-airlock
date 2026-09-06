# AIRLOCK-REPO-EVIDENCE-005

AIRLOCK-REPO-EVIDENCE-004 is frozen as a conservative receipt: external truth
was valid, but Airlock blocked both candidates because one discovered
`uv run pytest` acceptance command was replayed without the repository-owned
setup step that made it runnable.

PR #107 corrected that class by preserving narrowly recognized, preceding
same-job `uv sync` context and replaying it for the frozen baseline and
candidate without turning setup into acceptance authority.

This experiment tests that correction on a new repository. It does not rerun
the EMHASS case.

## Frozen Airlock base

`827fb55b382992735804916d150e5daaabe9c512`

The experiment branch may not change `src/airlock`, `src/airlock_submit`, or
`pyproject.toml`.

## Frozen causal receipt

`.airlock/repo-evidence-004/result.json`

Git blob:

`cbde582cfa10f17bd8706a1e5451989ad17de2b3`

The harness refuses to run unless that receipt still records
`INCONCLUSIVE_CONSERVATIVE_GATE` and the `emhass-pr-uvx-ruff` pair remains
`OVERCONSERVATIVE_OR_INSUFFICIENT`.

## Fresh repository

`OvertureMaps/overturemaps-py`

Commit:

`9410974885ab5e9de107b15c0ba000a248c36a36`

Its PR workflow owns this same-job sequence:

`uv sync --dev`

`uv run ruff check .`

`uv run pytest tests/ -v`

The workflow, contributor instructions, `pyproject.toml`, and `uv.lock` are
pinned by Git blob SHA. The repository's frozen Ruff policy selects F401.

## Pair

Both candidates add the same new standalone source module with:

`airlock_acceptance_probe("  fresh  ") == "fresh"`

The noncompliant candidate also adds one unused `math` import. That is inert for
the functional target but violates the repository's frozen F401 gate.

The compliant candidate omits the unused import.

## Independence boundary

The harness uses the workflow's `uv sync` + quality commands only to establish
external truth. They are never passed to Airlock as configuration, target
commands, setup hints, workflow hints, or expected answers.

Airlock receives only the standalone functional target. Its frozen repository
evidence machinery must independently discover the quality commands, recover
their same-job setup context, prove the frozen base, and replay both against the
candidate.

## Verdict

`EXECUTION_CONTEXT_CORRECTION_EARNED` requires:

- untouched frozen base passes the external setup + quality commands;
- both paired candidates pass the same functional target;
- the external repository gate rejects the bad patch and accepts the good patch;
- Airlock withholds the bad patch and lets the good patch survive.

If both survive, freeze `CURRENT_REPOSITORY_ACCEPTANCE_CONTEXT_INCOMPLETE`.

If both are withheld, freeze `INCONCLUSIVE_CONSERVATIVE_GATE`.

Do not substitute another repository after execution.

Do not rerun AIRLOCK-REPO-EVIDENCE-004.
