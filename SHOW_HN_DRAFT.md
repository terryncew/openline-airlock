# Show HN: Airlock – software that can earn its own improvements

A dollar can now buy hours of coding-agent work. The hard part is deciding whether any of it should become real.

Airlock is a bounded improvement loop for software. Agents can search, write code, and compete. They cannot edit the metric, weaken the repository checks, sign the result, or move `main`.

```bash
python -m pip install "git+https://github.com/terryncew/openline-airlock.git"

airlock init
airlock improve --objective .airlock/objective.json --generations 10 --agents 4
```

Read that output once and keep the objective and Starter Rules under maintainer control. For explicit multi-round search on one task, the lower-level command remains:

```bash
airlock swarm "fix issue #417"
```

The objective is an operator-owned JSON file. It names a measurement command, direction, minimum gain, complexity penalty, and hard limits on generations, changed files, and changed lines.

For every generation Airlock freezes the current commit, measures it repeatedly, launches competing agent attempts, reruns the repo's checks, and measures every survivor in a fresh worktree. A candidate's worst result has to beat the base version's best result. One candidate must win by the configured score gap. Noise, ties, regressions, protected-file changes, or weak gains stop the loop.

Accepted generations become ordinary commits on an isolated `airlock/improve/<run-id>` branch. Each generation gets a signed, hash-chained receipt. `main` is untouched; the normal PR/merge boundary still decides whether the improvement becomes real.

The same repo also supports one-issue search and a maintainer-authorized GitHub issue queue:

```bash
airlock solve 417
airlock autopilot --label airlock
airlock inbox
airlock review
```

There is no LLM judge. Normal issue solving still refuses to choose among several surviving patches. Continuous improvement can choose only when the protected operator objective produces one unambiguous winner.

The honest boundary: this is local governed search, not a claim that one scalar captures product value or that a benchmark improvement will survive production. A live canary/deployment loop is still outside the project. The repo includes the objective schema, a concrete test-runtime example, receipt verification, and adversarial tests for objective tampering, measurement side effects, noisy overlap, ambiguous winners, generation bounds, and chain tampering.

The idea is simple:

**The agent can change the code. It cannot change what counts as an improvement.**

Repo: https://github.com/terryncew/openline-airlock
