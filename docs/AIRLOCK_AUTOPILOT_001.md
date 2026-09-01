# AIRLOCK-AUTOPILOT-001

Status: **IMPLEMENTED — merge candidate**

Base: `terryncew/openline-airlock@617ffdf8e7736cd9826fd3a9965af1225cf7e922`

## Goal

Move Airlock from “solve this issue” to a bounded autonomous work queue without letting the system choose its own mandate.

```bash
airlock autopilot --label airlock
```

The maintainer chooses the label. Airlock works only the open issues carrying it. Every candidate still goes through the existing Starter Rules and `solve` path.

## Behavior

- Reads a snapshot of open GitHub issues carrying the selected label through `gh issue list`.
- Processes issues in ascending issue-number order.
- Attempts at most 3 issues per invocation by default; `--max-issues` changes the cap.
- Uses the existing `solve` defaults: 4 agent attempts × 2 rounds per issue unless overridden.
- Any supplied `--budget` is divided across the selected issue snapshot. It remains a provider hint, not a billing guarantee.
- Records issue URL, title, GitHub `updatedAt`, exit code, and status in `.airlock/autopilot/state.json`.
- An unchanged issue with a terminal result (`READY` or no review-ready patch) is skipped on the next run. If the issue changes, it is eligible again.
- `--retry-unchanged` explicitly overrides that deduplication.
- An environment/setup error stops the remaining queue before more agent spend.
- A normal no-review-ready result does not stop the next authorized issue.

## Boundary

Autopilot selects work only from a maintainer-controlled GitHub label. It does not create issues, expand the label set, rewrite Starter Rules, modify protected paths, weaken checks, rank multiple survivors, or convert a failed candidate into a PR.

The existing legacy argparse command set remains unchanged. `autopilot` is a dispatch shortcut, like `solve`, so old parser-surface tests remain valid.

## Validation

- `src/airlock/autopilot.py`: 8/8 focused unit tests pass in an isolated harness.
- `src/airlock/cli.py`: compile check PASS.
- Autopilot parser/dispatch harness PASS.
- Legacy parser choices remain exactly `{init, swarm, run, verify, install-github}`.
- Full repository CI remains authoritative after merge.
