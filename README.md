# OpenLine Airlock

**Run 12 coding agents. Review the one that survives.**

Use Claude Code, Codex, Aider, OpenCode, local models, or your own command. Airlock gives them the same task on separate Git worktrees, then independently checks every patch against the repo you already have.

It blocks patches that change tests or release config, fail lint/type checks, break existing tests, or are not covered well enough to justify an unattended PR.

If one patch survives, Airlock opens a PR and saves exactly what it checked. If none survive, you get zero PRs.

```text
$ airlock run 417 -n 12 --models claude-code,codex,aider --budget 1

Agents started: 12
Patches produced: 9

Blocked: 6
  2 changed protected tests/config
  3 broke existing tests
  1 failed lint/type checks
Needs evidence: 2
Survived: 1

Ready for review: candidate-07 -> airlock/ready/...
PR: https://github.com/acme/widget/pull/418
Verification file: .airlock/records/....json
Reported spend: $0.94
Elapsed: 4h 17m
```

That is the whole idea: **run more agents than you could ever review, then review only the patches that survive your own repo checks.**

## Three commands

```bash
pip install .
airlock init
airlock run <issue-or-prompt> -n 12 --models claude-code,codex,aider --budget 2.00
airlock verify .airlock/records/<run>.json
```

### `airlock init`

Airlock looks at the repo and finds the checks developers already use.

Current auto-detection includes:

- Python: `pytest`, `ruff`, `mypy`
- Node: `npm test`, `lint`, `typecheck`
- Rust: `cargo test --all-targets`
- Go: `go test ./...`

It also protects files agents should not be able to rewrite to make themselves look green, including common test directories, GitHub workflows, Airlock config, and detected build/test configuration.

Then it runs the discovered checks once. If the starting repo is already red, Airlock stops there.

Typical output:

```text
OpenLine Airlock

Found checks:
  ✓ pytest -q
  ✓ ruff check .
  ✓ mypy src

Protected automatically:
  • tests/**
  • .github/**
  • pyproject.toml
  • .airlock/**

Baseline: GREEN
Config: .airlock/config.json
Agent adapters found: claude-code, codex

Ready: airlock run <issue> -n 12
```

### `airlock run`

Airlock gives the same issue or prompt to N agents on separate Git worktrees.

Each agent can edit code and run whatever local checks it wants. Its own “done” message does not count. After generation finishes, Airlock checks the exact patch itself.

The default sequence is straightforward:

1. **Did it change tests or protected config?** Block it.
2. **Does lint/typecheck still pass?** If not, block it.
3. **Do the repo's existing tests still pass?** If not, block it.
4. **Can the repo actually tell whether this change was exercised?** If not, mark it `NEEDS_EVIDENCE` instead of pretending green CI proves enough.

Exactly one survivor becomes ready for review. More than one survivor means Airlock refuses to guess which one is best. Zero survivors means zero PRs.

### `airlock verify`

The surviving patch gets a JSON verification file in `.airlock/records/`.

`airlock verify` checks that file offline against the exact base commit and candidate commit. It verifies the signature, changed-file list, protected-file boundary, clean baseline fingerprint, and hashes of the recorded command results.

It does **not** rerun the agents.

## Bring your own agents

Airlock is not a coding agent and does not care which coding agent wins.

Built-in command adapters cover common installed CLIs:

- Claude Code
- Codex
- Aider
- OpenCode

Add anything else in `.airlock/config.json`:

```json
{
  "providers": {
    "my-agent": {
      "command": ["my-agent", "--task", "{prompt_file}"],
      "pass_env": ["MY_MODEL_API_KEY"],
      "timeout_seconds": 3600
    }
  }
}
```

Available placeholders: `{prompt}`, `{prompt_file}`, `{candidate_id}`, `{worktree}`, `{branch}`, `{budget}`.

Agent subprocesses do not receive GitHub tokens, release/signing keys, SSH-agent state, or the user's normal Git credential configuration. Provider credentials must be explicitly allowed.

This is application-level separation. If you treat the agent command as hostile native code, put generation in a container or VM.

## Cost reporting that does not lie

Agents can optionally report provider/model/cost telemetry to `AIRLOCK_AGENT_REPORT`:

```json
{
  "reported_cost_usd": "0.078",
  "local_checks_passed": true,
  "provider": "OpenRouter",
  "model": "deepseek/..."
}
```

`local_checks_passed` is informational only.

If every agent reports cost, Airlock can show a total. If one does not, Airlock says the known total and how many costs are missing. It does not turn missing numbers into an estimate and call the estimate measured spend.

## Weak tests stay weak

Airlock cannot invent tests your repo does not have.

When no issue-specific check is configured, v0.1 uses a deliberately conservative fallback: a changed source module must at least be referenced by a frozen baseline test. If Airlock cannot establish even that, the patch is `NEEDS_EVIDENCE` and no unattended PR is opened for it.

For a stronger check, add an issue-specific command before the run:

```json
{
  "verification": {
    "target_commands": [["pytest", "-q", "tests/test_issue_417.py"]]
  }
}
```

The verification file says exactly what passed. It never says the patch “broke nothing.”

## What gets saved

Every run keeps:

- base commit
- candidate commits and changed files
- agent/model telemetry when reported
- each independent check and exit code
- hashes of stdout/stderr artifacts
- reported cost with unknowns preserved
- elapsed time
- the surviving branch, if there is one
- the verification file for the survivor

`.airlock/index.json` maps those recorded hashes back to the patch that used them. That gives future tooling a cheap way to answer a practical question: **which patches should we re-check if one of these inputs changes?**

## What Airlock does not promise

Airlock does not make weak tests strong. It does not prove unknown edge cases, perfect correctness, or that one surviving patch is globally the best implementation.

What it does give you is simpler:

**the agent that wrote the patch does not get to rewrite the checks, grade itself, or hold the credentials that ship it.**

## Why use it?

Because cheap coding agents create a new bottleneck: review.

Running 50 agents is easy. Reading 50 diffs is terrible.

Airlock lets you use more autonomous coding without turning your GitHub inbox into agent spam.

**Give them the work. Keep the keys. Review the survivor.**
