# OpenLine Airlock

**Software that can earn its own improvements.**

Coding agents made attempts cheap. Human attention stayed expensive.

Airlock lets coding agents search for changes while keeping the definition of “better” outside the agents: in your tests, protected paths, metrics, limits, and promotion rules.

A failed attempt disappears into machine history. A weakly evidenced attempt stops. A uniquely measured improvement can become the next starting point on an isolated branch. **The agent can change the code. It cannot change what counts as an improvement.**

## The compounding loop

Give Airlock one protected objective and a bounded number of generations:

```bash
airlock init
airlock improve --objective .airlock/objective.json --generations 10 --agents 4
```

In every generation, agents compete to make one small, reversible improvement. Airlock independently reruns the repository checks and your measurement command. The candidate's worst measured result must beat the starting version's best result by your configured minimum. Complexity, changed files, and changed lines can all reduce or eliminate the candidate's score.

One candidate must win cleanly. Noise, a tie, a protected-file change, a regression, weak evidence, or no real gain stops the loop. Accepted generations form ordinary Git commits on `airlock/improve/<run-id>` with signed, hash-chained receipts. `main` never moves.

Start with the [operator objective guide](docs/CONTINUOUS_IMPROVEMENT.md) and the [test-runtime example](examples/objective-test-runtime.json).

### Let Hermes take the night shift

If Hermes is your persistent worker, use the same gate without turning Hermes into its own judge:

```bash
airlock nightshift --objective .airlock/objective.json --generations 10
```

Nightshift uses Hermes's scripted `-z` interface. The default is one Hermes attempt per generation, so one mutable profile can keep its memory and skills across the run. Parallel Hermes attempts require one distinct profile per candidate; Airlock refuses to call shared writable profile state "independent."

Hermes may improve the candidate code and its own worker state. It still cannot redefine the protected objective, repository checks, or promotion rule. The starting branch stays untouched. See [Hermes Nightshift](docs/NIGHTSHIFT.md).

## The five-command loop

Install Airlock:

```bash
python -m pip install "git+https://github.com/terryncew/openline-airlock.git"
```

Then the normal workflow is:

```bash
airlock init
airlock solve 417
airlock autopilot --label airlock
airlock inbox
airlock review
```

You do not need every command every time. The point is that these five commands form one loop.

### 1. `airlock init`

Airlock inspects the repository, finds common test/lint/type-check commands, confirms the starting commit passes, protects tests and important configuration, and saves editable **Starter Rules** in `.airlock/config.json`.

Read that output once. Change the Starter Rules if your repository needs a different bar.

### 2. `airlock solve 417`

Give Airlock one GitHub issue, issue URL, or plain-English task.

By default it runs four agent attempts across two rounds. Attempts get isolated Git worktrees. Later rounds can use bounded search notes from earlier failures, but those notes cannot rewrite the Starter Rules.

Zero survivors means zero review work. Several survivors remain several. One final survivor can become ready for review.

### 3. `airlock autopilot --label airlock`

A maintainer-controlled label becomes a bounded work queue.

Autopilot snapshots open issues carrying the label and attempts at most three by default. It remembers each issue's GitHub `updatedAt` value, so an unchanged terminal result is not automatically paid for again. Edit the issue and it becomes eligible again.

Autopilot does not create its own work or broaden its own label set.

### 4. `airlock inbox`

Machine search can create lots of evidence without creating lots of human work.

Inbox hides normal `NO_PATCH_READY` outcomes and shows only things that need a person: a survivor to review, multiple survivors that need a choice, a broken baseline, an environment failure, or a malformed record.

Use `airlock inbox --all` for the audit view.

### 5. `airlock review`

Review answers the question Inbox leaves open: **why did this patch earn my attention?**

Airlock re-verifies the signed survivor record and shows the issue, PR, base and candidate commits, changed files, exact recorded commands and exit codes, config hash, record hash, and reported cost.

It does not rerun candidate code or merge anything.

## What actually decides

Airlock does not ask an LLM judge which patch “looks best.”

A candidate is blocked if it changes protected files or fails the repository's configured checks. If the available checks do not justify unattended review, Airlock returns `NEEDS_EVIDENCE`.

In normal issue solving, several distinct survivors remain several; Airlock refuses to invent a winner. In the compounding loop, only a protected operator-authored scoring rule may establish one unique winner. An ambiguous score stops.

**Agents search. The repository decides what earns attention.**

## Advanced search controls

The five-command loop is the normal product surface. These lower-level commands remain available when you want explicit control.

Multi-round search:

```bash
airlock swarm "fix issue #417" \
  --agents 8 \
  --rounds 3 \
  --models claude-code,codex,aider \
  --budget 6.00
```

One independent best-of-N tournament:

```bash
airlock run <issue-or-prompt> -n 12 --models claude-code,codex,aider --budget 2.00
```

The `--budget` value is a planning/provider hint. Airlock records reported cost and preserves unknown cost as unknown. It does not claim a hard billing cap unless the provider enforces one.

## Starter Rules

Automatic discovery currently covers common Python (`pytest`, `ruff`, `mypy`), Node (`npm test`, `lint`, `typecheck`), Rust (`cargo test --all-targets`), and Go (`go test ./...`) repositories.

Generated Starter Rules protect test directories, workflows, Airlock files, and detected project configuration. They also list every command a patch must pass.

For Python repositories, Airlock puts the active candidate worktree's `src/` and repository root first on `PYTHONPATH`, so an editable install from the starting checkout cannot hide candidate source changes.

If Airlock finds no meaningful checks, or if the starting commit already fails them, unattended search stops.

For task-specific evidence, add a frozen target command before the run:

```json
{
  "verification": {
    "target_commands": [["pytest", "-q", "tests/test_issue_417.py"]]
  }
}
```

## Public machine contributions without raw agent PRs

Airlock also has an Actions-only contribution gate for outside forks.

Install it:

```bash
airlock init
airlock install-github
git add .airlock .github/workflows/airlock.yml CONTRIBUTING.md
git commit -m "chore: install OpenLine Airlock"
```

A contributor pushes a candidate to a public fork and comments on the issue:

```text
/airlock submit alice/widget@0123456789abcdef0123456789abcdef01234567
```

That comment is not a PR.

The public path separates:

1. **Admission** — fork relationship, base commit, limits, patch size, and protected paths.
2. **Evaluation** — candidate checks run without a GitHub token and without network access.
3. **Publication** — a trusted job rechecks the frozen binding and can open a PR without executing candidate code.

Possible outcomes are `BLOCKED`, `NEEDS_EVIDENCE`, `REOPEN`, and `SURVIVED`.

A survivor PR carries the base SHA, patch hash, config hash, exact commands, exit codes, and verification-record digest.

The public-fork path remains a separate claim boundary. Local autonomous search does not by itself prove the live outside-fork workflow.

## Bring your own agents

Airlock shells out to agent commands you already use.

Built-in adapters cover installed Claude Code, Codex, Aider, OpenCode, and Hermes CLIs. Hermes uses `hermes -z`; its built-in adapter forwards only `HERMES_HOME`. A key-based Hermes setup may explicitly name one additional provider credential in protected `.airlock/config.json`.

Agent subprocesses do not receive GitHub tokens, release/signing keys, SSH-agent state, or the user's ordinary Git credential configuration through Airlock's worker adapter. Provider credentials cross only when explicitly named.

Worktree isolation is not a strong sandbox. If an agent command must be treated as hostile native code, run generation inside a container or VM.

## Stable record formats in v0.3

The v0.3 release freezes the current v1 record names used by the loop:

`airlock.config.v1`, `airlock.run.v1`, `airlock.verification.v1`, `airlock.swarm.v1`, `airlock.autopilot.v1`, `airlock.autopilot.run.v1`, `airlock.inbox.v1`, and `airlock.review.v1`.

The additive continuous-improvement records are `airlock.objective.v1`, `airlock.improvement.generation.v1`, and `airlock.improvement.v1`. Nightshift adds the embedded run-context schema `airlock.nightshift.context.v1`.

“Frozen” means v0.3.x changes must remain backward-readable or move to a new schema name instead of silently changing the meaning of an existing one.

## What Airlock does not promise

Airlock does not make weak tests strong, prove that one scalar captures total product value, decide that one passing implementation is globally best, guarantee a provider obeys a budget hint, deploy to production, turn a local receipt into authority on a different system, or replace a sub-second live feasibility controller for physical systems.

It solves a narrower problem:

**cheap intelligence may propose improvements; it does not get to manufacture success or promotion authority.**
