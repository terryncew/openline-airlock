# OpenLine Airlock

**Turn machine attempts into software improvements without turning them into review debt.**

One coding agent gives you one answer. Airlock lets you spend many machine attempts on the same software problem while keeping human attention scarce.

Give your repository an issue. Let Claude Code, Codex, Aider, OpenCode, local models, or custom agents explore different fixes across multiple rounds. Agents can share bounded search discoveries and inspect earlier failed attempts. Airlock keeps the repository's tests, protected paths, and verification commands outside that coordination loop.

At the end, you review only what survived.

**Zero survivors is a valid result. More compute does not have to mean more PRs.**

## Autonomous software search

```bash
python -m pip install "git+https://github.com/terryncew/openline-airlock.git"

airlock init
airlock swarm <issue-or-prompt> \
  --agents 8 \
  --rounds 3 \
  --models claude-code,codex,aider \
  --budget 6.00
```

`airlock swarm` repeats the search instead of treating the first agent answer as special.

Each attempt runs in its own Git worktree. Across rounds, agents can share typed search notes such as root-cause hypotheses, failing tests, relevant symbols, attempted approaches, counterexamples, and performance findings. Later agents can inspect prior candidate commits and Airlock outcomes instead of rediscovering every dead end from scratch.

The shared blackboard is deliberately **not** part of the admission authority. It cannot rewrite protected files, tests, Airlock config, verification commands, or the evidence sufficiency rule. Search can coordinate. Passing cannot.

A swarm run can therefore end with:

- `READY` — exactly one final candidate survived and is ready for review.
- `MULTIPLE_SURVIVORS` — several survived; Airlock refuses to invent a winner.
- `NO_PATCH_READY` — nothing earned review.
- `BASELINE_NOT_GREEN` — the repository was already failing, so Airlock refuses to start unattended search.

Airlock records the run under `.airlock/swarms/` with attempts, shared findings, generated patches, blocked candidates, evidence gaps, survivors, elapsed time, and reported provider cost.

The `--budget` value is a planning and provider hint split across the scheduled attempts. Airlock records actual provider cost when agents report it, and leaves missing cost unknown. It does not claim a hard provider billing cap unless the provider itself enforces one.

## Why use this instead of one agent at a time?

Software debugging is search. A single agent can anchor on the wrong diagnosis, produce a locally convincing regression, or simply choose a weaker implementation.

Machine attempts are cheap enough to explore more of the solution space. Human review is not.

Airlock lets you make being wrong cheap: run many attempts, let later agents learn from earlier failures, and discard unsuccessful search before it becomes maintainer work.

**The goal is not more AI-written code. It is better code per minute of human attention.**

## The repo keeps the final veto

Airlock does not use an LLM judge to pick the least-bad patch.

A candidate that touches protected files is stopped. A candidate that fails the repository's configured checks is blocked. If the available checks do not justify sending the change forward, Airlock returns `NEEDS_EVIDENCE`.

When several patches survive, Airlock does not rank one into existence. When none survive, the output is zero.

**Agents search. The repository decides what earns attention.**

## Public machine contributions without raw agent PRs

Airlock also supports an Actions-only public contribution gate. It requires no hosted service or webhook server.

From your repository:

```bash
airlock init
airlock install-github
git add .airlock .github/workflows/airlock.yml CONTRIBUTING.md
git commit -m "chore: install OpenLine Airlock"
```

A contributor can use any coding agent, push the result to a public fork, and submit the commit SHA on the relevant issue:

```text
/airlock submit alice/widget@0123456789abcdef0123456789abcdef01234567
```

That comment is **not** a PR.

Airlock evaluates the candidate first. `BLOCKED` means the patch failed a repo rule. `NEEDS_EVIDENCE` means the available checks do not justify sending it to a maintainer. `REOPEN` means the base moved and the patch needs a fresh run. `SURVIVED` means the candidate cleared the configured boundary and can earn a normal PR for human review.

No agent gets push access. No candidate gets a GitHub token. No agent decides what "passing" means.

## What happens before a public PR exists

Airlock splits the public path into three jobs with different authority.

**1. Static admission.** Airlock checks the submitter, fork relationship, submission limits, base commit, patch size, and changed paths. Tests, `.github/**`, `.airlock/**`, and other configured protected files cannot be changed by the candidate. A protected-path change is rejected before Docker starts.

**2. Evaluation.** A GitHub-hosted runner builds the evaluator image from the frozen base commit, then runs the candidate with no network and no GitHub token. The repository's configured tests, lint, type checks, and issue-specific commands are authoritative. The evaluator also rejects new tracked-file mutations made by the checks themselves.

**3. Publication.** A separate trusted job gets the permission required to open a PR, but it never executes candidate code. It rechecks the exact patch, config, protected-file boundary, and base SHA. If the default branch moved after evaluation, the result becomes `REOPEN` instead of silently carrying the old result forward.

Every submission leaves an outcome. A survivor gets a PR with the base SHA, patch hash, config hash, exact commands, exit codes, and verification-record digest attached.

## One-round mode

If you only want independent best-of-N attempts without cross-round coordination:

```bash
airlock run <issue-or-prompt> -n 12 --models claude-code,codex,aider --budget 2.00
```

Exactly one survivor becomes ready for review. Zero survivors means zero candidates to review. Several survivors remain several survivors.

## What Airlock checks

`airlock init` discovers common repository checks and freezes the starting configuration. Current automatic discovery includes Python (`pytest`, `ruff`, `mypy`), Node (`npm test`, `lint`, `typecheck`), Rust (`cargo test --all-targets`), and Go (`go test ./...`).

Airlock protects test directories, workflow/config files, and detected build/test configuration so a candidate cannot make itself look green by rewriting the referee.

When the available tests do not meaningfully touch the changed module and there is no issue-specific target check, the result is `NEEDS_EVIDENCE`.

For a stronger task-specific bar, add a frozen target command before running the task:

```json
{
  "verification": {
    "target_commands": [["pytest", "-q", "tests/test_issue_417.py"]]
  }
}
```

## Bring your own agents

Airlock shells out to agent commands you already use.

Built-in adapters cover installed Claude Code, Codex, Aider, and OpenCode CLIs. Custom commands can be added in `.airlock/config.json`.

Agent subprocesses do not receive GitHub tokens, release/signing keys, SSH-agent state, or the user's normal Git credential configuration unless explicitly allowed as provider credentials. Worktree isolation is not a strong sandbox; if you treat an agent command as hostile native code, run generation inside a container or VM.

## What Airlock does not promise

Airlock does not make weak tests strong, prove perfect correctness, decide that one passing implementation is globally best, or guarantee a provider obeys a budget hint.

It solves a narrower problem:

**let machine search scale without making human review scale at the same rate.**
