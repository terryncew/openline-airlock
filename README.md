# OpenLine Airlock

**Run more coding agents without creating more review work.**

Coding agents made producing another patch cheap. Reviewing another patch is still human work.

Airlock lets you be much more aggressive about generation without being equally aggressive about your own attention. Give the same task to Claude Code, Codex, Aider, OpenCode, a local model, or several of them at once. Each attempt is isolated. Your repository's checks stay authoritative. Failed attempts stop before they become somebody's review problem.

Locally, Airlock can run several agent attempts against one task and leave only a survivor ready for review. In the GitHub contribution path, an outside contributor submits a commit from a fork; only a patch that survives the repo's frozen rules can earn a PR.

**Use whatever coding agent you want. The repo decides what passes.**

The point is simple: you should be able to increase machine attempts without increasing human review at the same rate.

## Run several agents on one task

```bash
python -m pip install "git+https://github.com/terryncew/openline-airlock.git"
airlock init
airlock run <issue-or-prompt> -n 12 --models claude-code,codex,aider --budget 2.00
airlock verify .airlock/records/<run>.json
```

Each agent gets a separate Git worktree. Airlock evaluates the resulting patches after generation finishes.

Exactly one survivor becomes ready for review. Zero survivors means zero candidates to review. If several patches survive, Airlock refuses to invent a winner; a human can decide whether any deserves attention.

That changes the practical question from "Which model should I trust enough to try?" to "How many cheap attempts can I afford to let the repo filter first?"

The `--budget` value is passed to agents as a budget hint and recorded with the run. Airlock does not claim provider-level spend enforcement unless the provider itself honors that limit. Missing cost telemetry stays unknown.

## Install the GitHub gate in your repo

Airlock does not require a hosted service or webhook server. The public contribution path runs entirely in GitHub Actions.

From your repository:

```bash
airlock init
airlock install-github
git add .airlock .github/workflows/airlock.yml CONTRIBUTING.md
git commit -m "chore: install OpenLine Airlock"
```

After that commit reaches your default branch, a contributor can use any coding agent, push the result to a public fork, and submit only the commit SHA on the relevant issue:

```text
/airlock submit alice/widget@0123456789abcdef0123456789abcdef01234567
```

That comment is not a PR.

Airlock checks the patch first. A patch that changes protected files is stopped before candidate code runs. A patch that breaks configured checks is `BLOCKED`. If the repo does not have enough evidence to justify sending the change forward, Airlock returns `NEEDS_EVIDENCE`. If `main` moves after evaluation, the result is `REOPEN`.

A patch that survives can earn a normal PR for human review.

No agent gets push access. No candidate gets a GitHub token. No agent decides what "passing" means.

## What happens to a public submission

Airlock splits the path into three jobs with different authority.

**1. Static admission.** Airlock checks the submitter, fork relationship, submission limits, base commit, patch size, and changed paths. Tests, `.github/**`, `.airlock/**`, and other configured protected files cannot be changed by the candidate. A protected-path change is rejected before Docker starts.

**2. Evaluation.** A GitHub-hosted runner builds the evaluator image from the frozen base commit, then runs the candidate with no network and no GitHub token. The repository's configured tests, lint, type checks, and issue-specific commands are authoritative. The evaluator also rejects new tracked-file mutations made by the checks themselves.

**3. Publication.** A separate trusted job gets the permission required to open a PR, but it never executes candidate code. It rechecks the exact patch, config, protected-file boundary, and base SHA. If the default branch moved after evaluation, the result becomes `REOPEN` instead of silently carrying the old result forward.

Every submission leaves an outcome. A survivor gets a PR with the base SHA, patch hash, config hash, exact commands, exit codes, and verification-record digest attached.

The default public gate is conservative: one evaluation at a time per repository, one unresolved candidate per submitter per issue, a seven-day GitHub-account floor, five submissions per user per rolling day, and patch size/file-count ceilings.

## What Airlock checks

`airlock init` discovers common repository checks and freezes the starting configuration. Current automatic discovery includes Python (`pytest`, `ruff`, `mypy`), Node (`npm test`, `lint`, `typecheck`), Rust (`cargo test --all-targets`), and Go (`go test ./...`).

Airlock also protects test directories, workflow/config files, and detected build/test configuration so a candidate cannot make itself look green by rewriting the referee.

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

Airlock is not a coding model or orchestrator. It shells out to agent commands you already use.

Built-in adapters cover common installed CLIs including Claude Code, Codex, Aider, and OpenCode. Custom commands can be added in `.airlock/config.json`.

Agent subprocesses do not receive GitHub tokens, release/signing keys, SSH-agent state, or the user's normal Git credential configuration unless explicitly allowed as provider credentials. If you treat an agent command as hostile native code, run generation inside a container or VM.

## Try the gate from the outside

There is a deliberately small public Airlock challenge in this repository:

https://github.com/terryncew/openline-airlock/issues/8

The bug is intentionally small. The interesting part is the boundary: an outside agent works in a repo it does not control, cannot change the protected tests or Airlock rules, and cannot open its own PR. A surviving patch earns one through the repository.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the exact contribution rule.

## Tested boundary

Airlock tests its own Actions-only path in normal CI on GitHub-hosted runners. The integration job builds the evaluator image with real Docker and freezes three outcomes: a surviving patch, a patch that returns `NEEDS_EVIDENCE`, and a protected-path candidate that is `BLOCKED` before execution. It also checks that the candidate container receives no GitHub token.

## What Airlock does not promise

Airlock does not make weak tests strong, prove perfect correctness, or decide that one passing implementation is globally best.

It solves a narrower problem:

**let lots of agents try without making a maintainer review lots of bad attempts.**
