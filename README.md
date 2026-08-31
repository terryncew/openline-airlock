# OpenLine Airlock

**Let coding agents work your backlog without turning every attempt into a PR you have to review.**

Coding agents made patches cheap. Review is still expensive.

If you give 20 agents a bug, you can get 20 different attempts back. That is useful until somebody has to read all 20 diffs. Airlock moves that filtering step before the PR queue.

Give the same issue to Claude Code, Codex, Aider, OpenCode, local models, or your own agent. Airlock runs each attempt separately, then checks the resulting patch against the repo's tests, lint, type checks, and protected files.

Bad patch? It stops there.

The repo does not have enough tests to tell whether the change works? Airlock says `NEEDS_EVIDENCE` instead of pretending a green run proves enough.

One patch survives? That is the one a maintainer sees.

**Use whatever coding agent you want. The repo decides what passes.**

## What this lets you do

Airlock makes high-volume autonomous coding practical without scaling human review at the same rate.

Use it to let agents attack stale bugs, dependency upgrades, security fixes, compatibility work, repetitive maintenance, and open issues while you spend human attention only on the attempts that survive your repo's checks.

For an open-source maintainer, that means you no longer have to choose between banning AI-generated contributions and letting raw agent PRs pile up in the queue.

You can use a simple rule instead:

> **AI PRs welcome — Airlock first.**
>
> Use whatever coding agent you want. Run the patch through Airlock before opening a PR. If it passes this repo's checks, it can enter the normal review queue. If it fails, you find out before a maintainer has to.

That is the product: **agents get unlimited attempts; human attention stays scarce.**

## What a run looks like

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
```

The numbers above are an example of the output format. Airlock reports measured run results and preserves unknown costs as unknown.

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

```text
$ airlock init

Found checks:
  pytest -q
  ruff check .
  mypy src

Protected:
  tests/**
  .github/**
  pyproject.toml
  .airlock/**

Baseline: GREEN
Config: .airlock/config.json
```

### `airlock run`

Airlock gives the same issue or prompt to N agents on separate Git worktrees.

Each agent can edit code and run whatever local checks it wants. Its own "done" message does not count. After generation finishes, Airlock checks the exact patch itself.

Airlock blocks a patch when it changes protected tests/config, fails lint or type checks, or breaks the repo's existing tests. If the available tests do not exercise the changed code well enough, the patch becomes `NEEDS_EVIDENCE` instead of being sent through automatically.

Exactly one survivor becomes ready for review. More than one survivor means Airlock refuses to guess which implementation is best. Zero survivors means zero PRs.

### `airlock verify`

A surviving patch gets a JSON verification file in `.airlock/records/`.

`airlock verify` checks that file offline against the exact base commit and candidate commit. It verifies the signature, changed-file list, protected-file boundary, clean baseline fingerprint, and hashes of the recorded command results.

It does not rerun the agents.

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

If you treat an agent command as hostile native code, run generation inside a container or VM.

## Weak tests stay weak

Airlock cannot invent tests your repo does not have.

When no issue-specific check is configured, v0.1 uses a conservative fallback: a changed source module must at least be referenced by a frozen baseline test. If Airlock cannot establish even that, the patch is `NEEDS_EVIDENCE` and no unattended PR is opened for it.

For a stronger check, add an issue-specific command before the run:

```json
{
  "verification": {
    "target_commands": [["pytest", "-q", "tests/test_issue_417.py"]]
  }
}
```

The verification file says exactly what passed. It never claims that passing the configured checks proves unknown behavior is correct.

## Cost reporting

Agents can optionally report provider, model, and cost telemetry to `AIRLOCK_AGENT_REPORT`.

If every agent reports cost, Airlock shows the measured total. If one does not, Airlock reports the known total and the number of missing costs. It does not invent a number for missing data.

## What Airlock does not promise

Airlock does not make weak tests strong. It does not prove perfect correctness or decide that one surviving patch is globally the best implementation.

It solves a narrower problem that becomes more important as coding gets cheaper:

**let lots of agents try without making a maintainer review lots of bad attempts.**
