# AIRLOCK-SOLVE-001

Status: **IMPLEMENTED — merge candidate**

Base: `terryncew/openline-airlock@11506b95de8b22a88cf26d960ac8f9ae2d82f8ca`

## Goal

Turn the existing Airlock pieces into one adoption-grade front door:

```bash
airlock solve 417
```

The command does not add a new evaluator or policy engine. It composes the existing Starter Rules and swarm path.

## Behavior

- If `.airlock/config.json` is missing, `solve` runs the existing zero-config `airlock init` path first.
- If Starter Rules already exist, `solve` leaves them untouched.
- `417` and `#417` resolve through `gh issue view`; a full issue URL or plain-English task can be passed directly.
- Installed provider adapters are used without silently rewriting existing Starter Rules.
- Default search is 4 attempts × 2 rounds.
- `--budget` remains a provider hint; Airlock makes no new billing-cap claim.
- Zero final survivors means zero review work.
- Multiple final survivors remain multiple; `solve` does not invent a winner.
- Exactly one final survivor follows the existing Airlock PR path.

## Boundary

`solve` is orchestration only. It does not change protected paths, configured checks, evidence sufficiency, candidate evaluation, signing, or PR eligibility.

The top-level argparse command set remains unchanged for backward-compatibility tests; `solve` is a dispatch shortcut handled before the legacy parser. `airlock solve --help` has its own parser and the top-level help epilog advertises the shortcut.

## Validation

- `src/airlock/cli.py` compiles.
- `tests/test_solve.py`: 7/7 pass in an isolated dependency-stub harness.
- Legacy parser choices remain exactly `{init, swarm, run, verify, install-github}`.
- README and Show HN onboarding order still satisfies the existing install → init → read → swarm contract while adding the shorter `solve` path.

The full repository CI remains authoritative after merge.
