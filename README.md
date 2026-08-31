# OpenLine Airlock

**Run more coding agents than you could ever review. Only verified patches get through.**

Airlock is an adversarial release membrane for autonomous coding agents. Give the same issue to Claude Code, Codex, Aider, OpenCode, local models, or your own runner. Airlock isolates the attempts, freezes your repository's existing release checks, kills candidates that touch protected success criteria or break regression/static invariants, and surfaces a survivor only when the repository has enough evidence to justify one.

It is not another coding agent. It is the gate between untrusted generation and a Git repository.

```text
$ airlock run https://github.com/acme/widget/issues/417 --agents 12 --models claude-code,codex,aider --budget 1

[outer chamber]  12 agents dispatched
[decontaminate]  8 candidates purged
[decontaminate]  3 candidates held for insufficient evidence
[inner chamber]  1 candidate cleared declared invariants
[inner chamber]  admitted candidate-07 -> airlock/admitted/...
Proof: .airlock/proofs/....json
Reported spend: $0.94
```

The important line is not the agent count. It is this:

> **The process that generated the patch never gets to define whether the patch earned admission.**

## Three commands

```bash
pip install .
airlock init
airlock run <issue-or-prompt> --agents 12 --models claude-code,codex,aider --budget 2.00
airlock verify .airlock/proofs/<run>.json
```

`airlock init` scans the local repository, auto-discovers common test/static commands, protects tests and release/configuration surfaces, and executes the discovered suite once. Airlock refuses unattended admission from a red baseline.

Auto-discovery currently understands common Python (`pytest`, `ruff`, `mypy`), Node (`npm test`, `lint`, `typecheck` scripts), Rust (`cargo test --all-targets`), and Go (`go test ./...`) repositories.

`airlock run` fans one task across isolated Git worktrees. Each agent sees its own branch and an environment with release/signing/GitHub credentials stripped. Every candidate is evaluated after generation by Airlock, not by the candidate's self-report.

`airlock verify` validates a proof receipt deterministically without running the swarm again. It checks the receipt signature, exact base/candidate diff boundary, protected-path boundary, frozen protected-file fingerprint, and the integrity of the recorded command artifacts.

## The elimination sieve

Airlock v0.1 applies four rules in order.

**1. Protected surface.** Tests, GitHub workflows, Airlock configuration, and detected build/test configuration files are protected by default. A candidate that changes one is purged before its tests count as evidence.

**2. Static invariants.** Detected lint/typecheck commands run in a fresh detached worktree at the exact candidate commit.

**3. Frozen regression suite.** Detected repository tests run against the candidate while the protected evaluator/test surfaces remain unchanged from the frozen base.

**4. Evidence sufficiency.** A green suite is not automatically treated as reality. When no explicit target check is configured, v0.1 performs a conservative heuristic: at least one frozen baseline test must reference a changed source module. If Airlock cannot find even that connection, the candidate becomes `INSUFFICIENT_EVIDENCE`, not admitted.

That last rule is intentionally modest. Referencing a module does not prove full semantic coverage. The proof receipt states the exact evidence Airlock observed and explicitly does **not** claim the patch “broke nothing.”

For stronger use, add target-specific commands to `.airlock/config.json` before the run:

```json
{
  "verification": {
    "target_commands": [["pytest", "-q", "tests/test_issue_417.py"]]
  }
}
```

## Bring your own agents

Airlock contains thin command adapters, not an agent framework. `airlock init` auto-registers common installed CLIs when their binaries are present:

- `claude-code` → `claude -p {prompt}`
- `codex` → `codex exec {prompt}`
- `aider` → `aider --message {prompt}`
- `opencode` → `opencode run {prompt}`

Every command is overrideable in `.airlock/config.json`, which is the source of truth for the local installation.

A provider definition is deliberately boring:

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

Placeholders: `{prompt}`, `{prompt_file}`, `{candidate_id}`, `{worktree}`, `{branch}`, `{budget}`.

Agents may write optional telemetry to the path in `AIRLOCK_AGENT_REPORT`:

```json
{
  "reported_cost_usd": "0.078",
  "local_checks_passed": true,
  "provider": "OpenRouter",
  "model": "deepseek/..."
}
```

Airlock never treats `local_checks_passed` as release evidence. Missing costs remain missing; they are never replaced with token estimates and presented as measured spend.

`--budget` is recorded and passed to generic adapters as `AIRLOCK_BUDGET_USD` per agent. Airlock cannot promise a hard provider-side spend cap unless the configured adapter itself enforces one.

## Admission is fail-closed

Candidate outcomes are intentionally asymmetric:

- `PURGED` — known boundary failure: protected surface, static invariant, regression, target check, branch integrity, or no patch.
- `INSUFFICIENT_EVIDENCE` — the available repo evidence cannot justify unattended admission.
- `SURVIVED` — the candidate passed all declared checks and the v0.1 sufficiency requirement.

Exactly one survivor becomes `ADMITTED`. If several survive, Airlock does not invent a winner; the run ends `MULTIPLE_SURVIVORS` and leaves the choice to a human or a future independent selector.

If zero survive, zero PRs are produced. That is a successful safety outcome, not a failed demo.

## PRs

A successful run always creates a local `airlock/admitted/<run-id>` branch and a signed proof in `.airlock/proofs/`. When the repository has a GitHub `origin` and the `gh` CLI is available, Airlock then attempts to push that already-admitted branch and open a PR. Agent subprocesses do not receive GitHub/release credentials. The PR body points back to the proof receipt.

Use `--no-pr` for a local-only tournament.

For stronger production separation, run generation, evaluation, and PR/promotion in separate CI jobs/containers with separate credentials. v0.1's local worktree isolation is application-level isolation, not a hostile same-kernel sandbox.

## Proofs and the evidence index

Receipts are content-addressed JSON bundles signed with a local HMAC key generated by `airlock init`. The local key makes accidental/tampered receipt edits detectable and supports deterministic offline verification. It is not marketed as a portable public-key identity system or a replacement for KMS-backed signing.

`.airlock/index.json` is a flat reverse evidence index. Each admitted proof is indexed by the hashes of the frozen evaluator surface, config, prompt, and observed command outputs. That gives later OpenLine standing/reconsideration machinery a cheap way to answer: “which admitted changes depended on this evidence?” without turning v0.1 into a graph database.

## What Airlock does not do

Airlock does not make weak tests strong. It does not prove unasserted edge cases, semantic optimality, arbitrary-repository correctness, complete dynamic-language reachability, or general coding-agent safety.

Its narrower promise is useful precisely because it is enforceable:

**an untrusted coding agent can propose a patch, but it cannot confer release standing on itself.**

## Why this exists

Cheap agent generation changes the bottleneck. If 50 agents can produce 50 patches while you sleep, reviewing 50 patches is still a terrible product.

Airlock turns the repository checks you already invested in into an elimination boundary for far more autonomous attempts than a human team could review manually.

**Bring any agent. Keep the keys.**
