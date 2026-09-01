# AIRLOCK-INBOX-001

Status: **IMPLEMENTED — merge candidate**

Base: `terryncew/openline-airlock@654cc34ac7141a8711df3bd2f152cd7617e5d4f6`

## Goal

Make the human-attention promise visible in one command:

```bash
airlock inbox
```

Autonomous search can generate many attempts, blocked patches, and legitimate zero-survivor runs. Those are evidence, not automatically a human to-do list. Inbox reduces the local Airlock record to the outcomes that actually need a person.

## Behavior

- `READY` with a surviving branch or PR becomes `REVIEW`.
- `MULTIPLE_SURVIVORS` becomes `CHOOSE`; Airlock still refuses to rank distinct passing patches into a winner.
- `BASELINE_NOT_GREEN` becomes `FIX_BASELINE`.
- Autopilot `ERROR` becomes `FIX_ENV` for the issue that stopped the queue.
- Normal `NO_PATCH_READY` results are hidden by default because they created zero review work.
- `airlock inbox --all` includes those machine-only outcomes for audit.
- `--json` exposes the same reduction as `airlock.inbox.v1`.
- `--limit` bounds visible output; the report still preserves the total human-attention count.
- Malformed local swarm/autopilot records become `FIX_RECORD` instead of disappearing silently.

Where possible, Inbox recovers the originating GitHub issue URL from the final run's frozen prompt and shows the Airlock-created PR URL when one exists.

## Boundary

Inbox is read-only reduction of existing local Airlock artifacts. It does not run agents, create or merge PRs, modify Starter Rules, select issues, alter evaluation, choose between distinct survivors, or change receipt semantics.

## Validation

- `tests/test_inbox.py`: 9/9 focused tests pass.
- `src/airlock/inbox.py` and `src/airlock/cli.py`: compile PASS.
- Inbox parser/dispatch harness PASS.
- Legacy parser choices remain exactly `{init, swarm, run, verify, install-github}`.
- Full repository CI remains authoritative after merge.
