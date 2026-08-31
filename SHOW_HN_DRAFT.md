# Show HN draft — replace fixture numbers with one real public run

## Title

**Show HN: Airlock – I let 12 coding agents attack the same bug and only one was allowed through**

## Opening

Cheap coding agents changed the bottleneck for me. Generating 12 patches is easy. Reviewing 12 patches is still awful.

Airlock sits between the generators and Git. It gives every agent its own worktree, freezes the repository's existing tests/release configuration, then independently eliminates candidates that edit protected success criteria, fail static checks, regress the suite, or lack enough target evidence to justify unattended admission.

The coding agents never get to decide that their own patch earned release standing.

## Publish the real receipt here

```text
12 agents dispatched.
9 produced candidate patches.
6 said their local checks passed.
4 failed independent regression/static checks.
3 touched protected or insufficiently covered surfaces.
1 survived.

PR #___ opened.
Reported spend: $___ (or say which costs were unknown).
Elapsed: ___
Protected success surfaces modified by admitted patch: 0
```

Do not publish synthetic fixture counts as the launch result. If the first public run produces zero survivors, publish zero survivors.

The question is not whether Airlock's agent is smarter than Cursor/Claude/Codex. Airlock has no model.

> When generation is cheap enough to run 12 agents, what decides which output deserves production?
