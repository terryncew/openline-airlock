# Show HN: Airlock – admission control for coding-agent patches

Coding agents can already generate more patches than humans want to review.

Cursor, Codex, Claude, Aider and the rest are getting very good at producing work. PR reviewers are getting very good at inspecting that work after it arrives.

I built Airlock for the boundary in between: **which machine attempts should be allowed to become review work at all?**

Airlock sits in front of the PR queue. Keep whatever agent stack you already like. The repository owns the tests, protected files, and acceptance rules. A machine patch has to clear that boundary before it can earn a normal PR.

For the public contribution path, an outside contributor pushes a candidate to a public fork and submits only the commit SHA on the relevant issue:

```text
/airlock submit USER/FORK@FULL_COMMIT_SHA
```

That comment is not a PR.

Airlock checks the submitter and fork, rejects protected-file edits before candidate code runs, evaluates the patch in a Docker container with no network and no GitHub token, and reserves PR creation for a separate trusted job that never executes candidate code.

`BLOCKED` means the patch violated a repo rule or failed a configured check. `NEEDS_EVIDENCE` means the available checks do not justify sending it forward. `REOPEN` means the base moved and the candidate needs a fresh run. A `SURVIVED` patch can earn a normal PR for human review.

The agent never gets push access and never decides what passing means.

Airlock also has a local best-of-N path for running several coding agents against the same task in isolated Git worktrees, but that is secondary to the point: generation can come from anywhere. Airlock is the independent admission boundary.

The question I care about is simple:

**As machine-generated patches become cheap, can we keep failed attempts from becoming human review work?**

Repo: https://github.com/terryncew/openline-airlock

There is a deliberately small public challenge here if you want to see the pre-PR boundary from the outside:

https://github.com/terryncew/openline-airlock/issues/8
