# Repository acceptance evidence

AIRLOCK-SWE-GATE-001 produced a clean underconstraint case: two Flake8 patches
passed Airlock's configured checks, but only one satisfied the maintainer-derived
tooling constraint.

This change closes the class of failure without teaching Airlock SWE-Gate or
adding a pyright-specific rule.

The product boundary is now explicit:

- configured tests/static checks establish executable correctness;
- additional repository-owned acceptance evidence is discovered separately;
- a candidate cannot introduce a new project-control file and use it to redefine
  the judge after the base is frozen;
- replayable acceptance commands found in existing CI, project scripts,
  contributor commands, Make targets, and supported tool-script config are run
  against the candidate;
- the files that define those commands, plus directly invoked judge scripts, are
  restored from the frozen base before execution;
- recognized acceptance evidence that cannot be replayed causes
  `NEEDS_EVIDENCE` through the existing sufficiency gate.

No model invents an acceptance rule. The repo either already owns evidence for
the constraint, or Airlock declines to treat ordinary test passage as enough.

This does not change or attempt to repair the separate zero-config
initialization failures observed by AIRLOCK-SWE-GATE-001.

## Fresh falsifier

Do not rerun AIRLOCK-SWE-GATE-001.

The next external experiment must use fresh unrelated repositories. Each case
must contain repository-owned acceptance evidence before the candidate patches
are created. Both paired patches must pass the obvious functional tests; only
one may satisfy that pre-existing acceptance evidence.

The fix earns the stronger claim only if noncompliant patches are withheld
without benchmark-specific rules or manual patch labeling. Cases where the
acceptance evidence cannot be replayed must stop at `NEEDS_EVIDENCE`, not
`SURVIVED`.

## AIRLOCK-REPO-EVIDENCE-001 follow-up

AIRLOCK-REPO-EVIDENCE-001 found a fresh `UNDERCONSTRAINED` pair in
`korean-romanizer`: the repository's pull-request workflow contained a
`Quality gates` job with a mypy requirement, but the workflow itself was named
`Python application` and stored in `python-app.yml`. Airlock stopped at the
outer workflow name and never reached the repository-owned quality evidence.

The correction is intentionally narrower than "run every GitHub Actions step."
For pull-request workflows, Airlock now treats filename and top-level name as
hints rather than a prerequisite. It also inspects nested job ids, job/step
names, and quality-like run commands. The existing safe command parser and
quality-command allowlist still decide what can actually be replayed.

Push-only, release-only, and deployment-only workflows do not become acceptance
authority merely because they contain a quality-looking job.

Do not rerun AIRLOCK-REPO-EVIDENCE-001. The underconstraint is the frozen
receipt. The corrected product must be tested on fresh cases.

## AIRLOCK-REPO-EVIDENCE-003 follow-up

AIRLOCK-REPO-EVIDENCE-003 found a fresh `UNDERCONSTRAINED` pair in
`significantdigits`. Airlock correctly recognized the generic pull-request
workflow and replayed `uv run pytest`, but it silently dropped the repository's
strict `uvx flake8 ...` acceptance command because `uvx` was not recognized as
a tool runner. Both functionally passing candidates therefore survived even
though the external repository-owned verifier rejected the noncompliant one.

The correction is wrapper-aware without making wrappers authoritative. `uvx`
is now accepted only when the command it wraps is already in Airlock's existing
quality-command families. `uvx lint-remote-repo`, for example, does not become
acceptance evidence merely because it is wrapped by `uvx`. If `uvx` itself is
unavailable, the recognized repository evidence remains unresolved and the
existing sufficiency gate fails closed instead of promoting the candidate.

Do not rerun AIRLOCK-REPO-EVIDENCE-003. Its `SURVIVED / SURVIVED` result is the
frozen receipt. Test this correction on fresh wrapper cases.

## AIRLOCK-REPO-EVIDENCE-004 follow-up

AIRLOCK-REPO-EVIDENCE-004 reproduced external truth on a fresh EMHASS pair, but
Airlock withheld both candidates. The `uvx` correction worked: Airlock found and
replayed the repository's `uvx ruff check ...` and `uvx ruff format --check ...`
gates. The conservative failure came from a different PR workflow. Airlock
replayed `uv run pytest` without the preceding same-job
`uv sync --reinstall --upgrade --extra test`, so the frozen base could not spawn
`pytest` and repository acceptance stopped at `acceptance_baseline_not_green`.

The correction preserves a narrow repository-owned execution context instead of
inventing dependencies. For GitHub pull-request workflows, a safe `uv sync ...`
step that appears earlier in the same job is attached to later recognized
acceptance commands and replayed before them on both the frozen base and the
candidate. Setup from one job cannot leak into another job. `uv sync` itself is
not acceptance evidence, and other `uv`/`poetry` subcommands do not gain
acceptance authority merely because their text mentions a quality tool.

Setup is still fail-closed. If its executable is unavailable, the associated
acceptance evidence is unresolved. If setup fails, times out, or changes tracked
repository state, Airlock withholds the candidate rather than silently changing
the frozen judge.

Do not rerun AIRLOCK-REPO-EVIDENCE-004. Its `BLOCKED / BLOCKED` result is the
frozen receipt. Test this correction on a fresh repository whose pull-request
quality command genuinely depends on a preceding same-job `uv sync` context.
