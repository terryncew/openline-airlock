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

