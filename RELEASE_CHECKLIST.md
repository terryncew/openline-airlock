# Airlock v0.3 release gate

The release candidate is the exact commit that must satisfy this list. Do not repair evidence after seeing a failed outcome and call it the same run.

## Package

- `pyproject.toml` and `src/airlock/__init__.py` both report `0.3.0`.
- CI passes on Python 3.11, 3.12, and 3.13.
- The wheel builds from the release commit and installs into a fresh virtual environment.
- Fresh-wheel `airlock --version` prints exactly `0.3.0`.
- Fresh-wheel `airlock --help` exposes the canonical loop: `init`, `solve`, `autopilot`, `inbox`, `review`.
- Fresh-wheel `airlock review --help` routes through the installed console script.

## Product loop

- `airlock init` preserves developer-edited Starter Rules and refuses a red baseline.
- `airlock solve` does not rewrite existing Starter Rules.
- Zero survivors create zero review work.
- Multiple survivors remain multiple; no automatic winner is invented.
- Autopilot works only issues selected by the maintainer-controlled label and stays bounded by `--max-issues`.
- Inbox hides normal no-patch outcomes by default but keeps them auditable with `--all`.
- Review fails closed on an invalid or mismatched signed survivor record and reruns zero candidate code.

## Frozen v1 record names

For the 0.3.x line, these names are backward-reading commitments:

- `airlock.config.v1`
- `airlock.run.v1`
- `airlock.verification.v1`
- `airlock.swarm.v1`
- `airlock.autopilot.v1`
- `airlock.autopilot.run.v1`
- `airlock.inbox.v1`
- `airlock.review.v1`

If a future change makes an old reader unsafe or materially changes the meaning of an existing field, use a new schema name.

## Evidence boundaries

- Preserve candidate dispositions and agent-reported economics exactly; unknown cost stays unknown.
- Keep GitHub/release credentials outside agent subprocesses.
- Do not claim that local `solve`/`autopilot` proves the live outside-fork GitHub path.
- `AIRLOCK-PUBLIC-COLD-ADOPTION-001` remains a failed boundary exercise.
- A public-fork claim requires a genuinely separate fork, `/airlock submit OWNER/REPO@SHA`, live Actions evaluation, and an Airlock-opened PR bound to the exact base, patch, config, checks, exits, and verification digest.
