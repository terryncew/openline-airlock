# Show HN: Airlock – turn a GitHub issue into autonomous software search

Coding agents made attempts cheap. Human attention is still expensive.

Airlock lets a repository spend many coding-agent attempts on one issue without turning every attempt into a pull request.

```bash
python -m pip install "git+https://github.com/terryncew/openline-airlock.git"
airlock init
```

`airlock init` looks at the repository, chooses editable Starter Rules from the checks already there, and prints exactly what it found: project type, paths accepted patches cannot change, commands every patch must pass, and whether the starting commit passes them. Read that output. If the checks are missing or already red, Airlock stops there.

Then:

```bash
airlock swarm "fix issue #417" \
  --agents 8 \
  --rounds 3 \
  --models claude-code,codex,aider \
  --budget 6.00
```

Each attempt gets an isolated Git worktree. Agents can use bounded, typed notes from earlier rounds — root-cause hypotheses, failing tests, relevant symbols, attempted approaches, counterexamples, and performance findings — so later attempts can avoid rediscovering the same dead ends.

The important part is what shared notes cannot rewrite and accepted patches cannot change: the repository's Starter Rules.

Changes to listed files are rejected. The configured tests, lint/type checks, task-specific commands, and evidence-sufficiency rule remain repository-owned. Shared agent notes are untrusted search hints only.

That means a swarm can spend twenty attempts and still produce zero PRs.

If exactly one final patch survives, it can become ready for review. If several survive, Airlock refuses to invent a winner. If none survive, the maintainer gets nothing to clean up.

The public contribution path is separate and Actions-only: outside contributors submit a fork commit on an issue, candidate code runs without a GitHub token or network access, and only a trusted publisher can open a PR after the patch survives.

The product idea is simple:

**machine search should be allowed to scale without forcing human review to scale with it.**

Repo: https://github.com/terryncew/openline-airlock
