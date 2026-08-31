# Show HN: Airlock – run more coding agents without creating more review work

Coding agents made producing another patch cheap. Reviewing another patch is still human work.

That creates a strange bottleneck: I can ask several agents to try the same task in parallel, but if I have to inspect every result myself, I have not really escaped the expensive part.

I built OpenLine Airlock so the repository can be the first filter.

For local work, Airlock gives separate Git worktrees to multiple coding-agent attempts, evaluates the patches against the repo's own checks, and leaves only a survivor ready for review. If nothing survives, there is nothing for a human to review. If several survive, Airlock does not pretend it knows which implementation is globally best.

```bash
airlock run <issue-or-prompt> -n 12 --models claude-code,codex,aider --budget 2.00
```

There is also a GitHub contribution mode. An outside contributor pushes a candidate to a public fork and submits the commit SHA on an issue:

```text
/airlock submit USER/FORK@FULL_COMMIT_SHA
```

That comment is not a PR.

The repo checks the submitter and fork, rejects protected-file edits before candidate code runs, evaluates the patch in a secretless Docker container with no network or GitHub token, and reserves PR creation for a separate trusted job.

`BLOCKED` means the patch violated a repo rule or failed a configured check. `NEEDS_EVIDENCE` means the available checks do not justify sending it forward. `REOPEN` means the base moved and the candidate needs a fresh run. A `SURVIVED` patch can earn a normal PR for human review.

The coding agent never gets push access and never decides what passing means.

The thing I am interested in is less "which coding agent is smartest?" and more "how many machine attempts can a developer afford to run once failed attempts stop consuming human review?"

Repo: https://github.com/terryncew/openline-airlock

There is a deliberately small public challenge here if you want to see the pre-PR gate from the outside:

https://github.com/terryncew/openline-airlock/issues/8

**Use whatever coding agent you want. The repo decides what passes.**
