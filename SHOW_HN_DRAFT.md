# Show HN: Airlock – let coding agents keep trying without filling your PR queue

Coding agents made attempts cheap. Human attention stayed expensive.

Airlock gives a repository a bounded autonomous work loop while keeping “what counts as passing” in the repository instead of in the agent.

```bash
python -m pip install "git+https://github.com/terryncew/openline-airlock.git"

airlock init
airlock solve 417
```

`init` finds the repo's existing checks and saves editable Starter Rules. Read that output before unattended search. `solve` gives the issue to several coding-agent attempts across multiple rounds. Failed attempts stay machine work. Exactly one final survivor can earn review.

The loop can keep going:

```bash
airlock autopilot --label airlock
airlock inbox
airlock review
```

The label chooses what the system is allowed to work on. `inbox` hides normal dead ends and shows only outcomes that need a person. `review` re-verifies the signed survivor receipt and shows why the patch earned attention: exact commits, changed files, checks, exit codes, hashes, PR, and reported cost.

Airlock never asks an LLM judge to pick the nicest-looking patch. Protected files stay protected. Repository checks remain authoritative. Weak evidence returns `NEEDS_EVIDENCE`. Multiple survivors remain multiple. Zero survivors remains zero.

Lower-level `swarm` and `run` commands are still there when you want explicit attempts, rounds, models, and budget hints. For example: `airlock swarm "fix issue #417"`.

There is also a separate Actions-only outside-contributor path: a contributor submits a public-fork commit on an issue, candidate code runs without GitHub credentials or network access, and a trusted publication job can open a PR only after the frozen candidate survives.

v0.3 is the first release where the pieces read as one product instead of a collection of experiments:

**init → solve → autopilot → inbox → review**

The idea is simple: machine search can scale. Your review queue should not have to.

Repo: https://github.com/terryncew/openline-airlock
