# AIRLOCK-REVIEW-001

Status: **IMPLEMENTED — merge candidate**

Base: `terryncew/openline-airlock@8084175e84a4a51502a0f895ce24c6c33f421c7a`

## Goal

Close the loop between `airlock inbox` and human review.

```bash
airlock review
```

Inbox answers “what needs me?” Review answers “why did this patch earn my attention?” without rerunning candidate code.

## Behavior

- Selects the latest local `READY` swarm by default, or accepts an explicit `swarm.json`.
- Re-validates the signed Airlock verification record before showing the packet.
- Fails closed if the signature/evidence verification fails, the swarm and verification record disagree, the record is missing, or a record path escapes the repository.
- Shows the issue, Airlock-created PR when present, base and candidate commits, changed paths, exact recorded commands and exit codes, config hash, verification-record hash, and reported cost.
- Omits stdout/stderr bodies from the default review packet; their hashes remain available as evidence.
- `airlock review --json` emits `airlock.review.v1` for tooling.
- Review is read-only. It does not rerun candidate code, choose between multiple survivors, alter Starter Rules, approve, or merge.

## Entry routing

The installed `airlock` console script now points at `airlock.entry:main`. The router intercepts only `review`; every existing command is passed unchanged to the existing CLI, including `solve`, `autopilot`, `inbox`, `init`, `run`, `swarm`, `verify`, and `install-github`.

## Validation

- Focused review/entry suite: 8/8 pass.
- `src/airlock/entry.py` compile: PASS.
- `src/airlock/review.py` compile: PASS.
- Existing command passthrough is explicitly tested.
- Full repository CI remains authoritative after merge.
