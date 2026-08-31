# Show HN: Airlock – AI agents can submit patches to my repo, but they do not get to open PRs

Coding agents made writing patches cheap. Reviewing patches is still human work.

I built OpenLine Airlock to put a gate in front of the PR queue. A contributor can use Claude Code, Codex, Aider, OpenCode, a local model, or anything else, push the result to a public fork, and submit the commit on the GitHub issue:

```text
/airlock submit USER/FORK@FULL_COMMIT_SHA
```

That comment is not a PR. Airlock checks the submitter and fork, rejects protected-file edits before candidate code runs, evaluates the patch in a secretless Docker container with no network or GitHub token, and only a separate trusted job can open the PR.

If the repo cannot justify the change from its frozen checks, the result is `NEEDS_EVIDENCE`. If the patch edits the referee, breaks the checks, or violates a protected boundary, it is `BLOCKED`. If `main` moves after evaluation, the result is `REOPEN`. A `SURVIVED` patch earns a normal PR for human review.

The coding agent never gets push access and never decides what passing means.

The first public challenge is intentionally boring: fix one small GitHub-remote parsing edge case in Airlock itself. The acceptance command is already frozen in the repo. Tests and Airlock config are protected, so an agent that tries to rewrite the bar gets rejected before Docker.

**Use whatever coding agent you want. The repo decides what passes.**

Repo: https://github.com/terryncew/openline-airlock
Challenge: [PASTE THE ISSUE URL HERE]

I am especially interested in the failure cases. If the first outside attempt gets blocked, that is useful data too.
