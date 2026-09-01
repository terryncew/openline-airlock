# Changelog

## 0.3.0 — Autonomous work loop

- Makes `airlock init → solve → autopilot → inbox → review` the canonical product loop.
- Adds `airlock solve` as the one-command path from a GitHub issue or prompt to bounded multi-round agent search under existing Starter Rules.
- Adds `airlock autopilot --label ...` for bounded maintainer-authorized issue queues with unchanged-work deduplication and fail-closed environment handling.
- Adds `airlock inbox` to keep normal machine dead ends out of the human to-do list while surfacing review, choice, baseline, environment, and record work.
- Adds `airlock review` to re-verify a signed survivor record and reduce it to the evidence a human needs without rerunning candidate code.
- Makes top-level `airlock --help` show the normal loop first while preserving `swarm`, `run`, and `verify` as advanced controls.
- Freezes the existing v1 record names for the 0.3.x line; incompatible meaning changes require a new schema name.
- Keeps budget semantics honest: requested budget remains a provider hint unless the provider enforces it, and missing reported economics remain unknown.
- Keeps the public outside-fork GitHub contribution path as a separate evidence boundary; v0.3 does not convert local autonomous-search results into a claim that the live public-fork path has passed.

## Unreleased — Governed continuous improvement

- Repairs AIRLOCK-SELF-001 after its first dispatch stopped before worker contact: infrastructure failure is now distinct from a valid negative result, the full baseline is proven in the prerequisite job, the local opportunity is single-file, shared Hermes attempts are serial, and every conclusion is rendered in the GitHub job summary.
- Adds `airlock nightshift`, a Hermes-specific surface over the same protected objective/check/receipt chain.
- Uses Hermes's scripted `-z` interface and keeps one persistent worker attempt per generation by default.
- Requires distinct Hermes profiles for parallel candidate competition so shared mutable memory/skills cannot masquerade as independent workers.
- Adds bounded Hermes credential forwarding: `HERMES_HOME` by default and at most one explicitly named provider credential in protected config.
- Binds worker identity, compact process execution evidence, optional provider/model usage reports, and per-generation reported economics into signed improvement receipts.
- Freezes the claim boundary that software admission is not a substitute for sub-second live feasibility control in physical systems.
- Adds `airlock improve`, a bounded loop that measures the current commit, runs competing agent attempts, and compounds only one uniquely scored improvement on an isolated Airlock branch.
- Keeps the objective, metric command, minimum gain, scoring penalties, and blast-radius limits under operator-owned `.airlock/` configuration.
- Uses conservative repeated measurement: a candidate's worst result must clear the base version's best result, so overlapping noisy observations do not count as gain.
- Preserves normal issue-solving semantics: multiple ordinary survivors remain multiple. Only a protected objective contract can identify a unique improvement winner; ambiguity stops the loop.
- Writes signed, hash-chained generation receipts and a final report that can be verified without running candidate code.
- Leaves `main` untouched and makes every accepted generation a normal reversible Git commit.
- Does not claim that a local metric captures total product value or that a local benchmark improvement survives production.

## 0.2.2 — Candidate-bound checks

- Makes local baseline, agent, and candidate-check processes put the active Git worktree's `src/` and repository root first on `PYTHONPATH`.
- Prevents a Python editable install from the starting checkout from masking a candidate source change with the already-installed base package.
- Aligns the legacy container worker with the Actions evaluator's candidate-worktree Python path.
- Adds the `AIRLOCK-COLD-ADOPTION-001` regression that turns an unconditional candidate failure into `BLOCKED / TESTS_FAILED` instead of a signed survivor.

## 0.2.1 — Starter Rules

- Turns `airlock init` into a zero-config onboarding step with plain-English sections for detected project tools, paths accepted patches cannot change, commands every patch must pass, and starting-repo status.
- Keeps the existing `airlock.config.v1` format and preserves developer-edited rules, target commands, providers, limits, and paths on rerun.
- Keeps Python, Node, Rust, and Go discovery, while adding reliable names for detected test runners, linters, and type checkers.
- Reports a pytest count only when the already-completed successful run provides an exact summary; otherwise it omits the count.
- Stops with actionable output when no meaningful checks are found, a command cannot run, or the starting commit is red.
- Ends every successful setup with one next command: `airlock swarm "fix issue #417"`.

## 0.2.0 — Autonomous software search

- Adds `airlock swarm`: give one issue or prompt to repeated rounds of heterogeneous coding-agent attempts while Airlock keeps the repository's existing admission checks authoritative.
- Adds an ephemeral, typed blackboard for bounded search coordination across rounds. Agents can share root-cause hypotheses, failing tests, relevant symbols, attempted approaches, counterexamples, and performance findings.
- Blackboard content is explicitly untrusted and cannot change protected paths, verification commands, sufficiency rules, or admission decisions.
- Later-round agents can inspect prior candidate commits and Airlock outcomes, allowing failed approaches to become search information instead of human review work.
- Keeps zero survivors as a valid outcome and refuses to invent a winner when several candidates survive.
- Adds screenshot-friendly run summaries for attempts, findings, generated patches, blocked attempts, evidence gaps, survivors, and reported provider cost.
- Keeps `--budget` honest: it is divided across planned attempts as a provider hint and recorded, but Airlock does not claim provider-level spend enforcement unless the provider honors it.

## Launch-ready public contribution copy

- Makes the repository itself directly usable as an Airlock target with a four-step fork/commit/issue-comment flow.
- Removes fake sample run numbers from the README; public examples now describe commands and actual decisions only.
- Makes `airlock install-github` generate self-contained contributor instructions for `BLOCKED`, `NEEDS_EVIDENCE`, `REOPEN`, and `SURVIVED`.
- Documents installation directly from GitHub so maintainers can adopt Airlock before a package-index release.

## 0.1.3 — AIRLOCK-INTEGRATION-001

- Adds a GitHub-runner integration test for the Actions-only public contribution path.
- Exercises a real Docker evaluator with no GitHub token inside the candidate container.
- Freezes three outcomes: `SURVIVED`, `NEEDS_EVIDENCE`, and a protected-path `BLOCKED` that never executes candidate code.
- Uploads the three outcome files plus a machine-readable integration report as a CI artifact.
- Runs automatically in normal CI; maintainers do not start a separate workflow or operate a service.
- Corrects evaluator side-effect detection so the candidate patch itself is an allowed starting state while any new tracked-file mutation during a check is still blocked.

## 0.1.2 — AIRLOCK-ADOPTION-001

- Added `airlock install-github`, an Actions-only install path with no standing webhook service.
- Public submissions now run as three permission-separated GitHub Actions jobs: static admission, secretless Docker evaluation, and trusted publication.
- Protected-path rejection happens before Docker; blocked candidates never execute.
- The Actions path is serialized per repository and enforces account-age, daily-submission, fork-owner, and one-open-candidate-per-issue checks before expensive evaluation.
- The evaluator image is built from the frozen base commit, never from candidate files.
- A survivor opens a PR only if the base SHA is still current; otherwise the result is `REOPEN`.
- `CONTRIBUTING.md` and the protected runtime are generated by the installer so adopting repositories do not need an Airlock service or PyPI dependency at runtime.

## 0.1.1 — AIRLOCK-SUBMIT-002 hardening

- Reject protected-path changes before Docker starts.
- Write a signed outcome file for `BLOCKED`, `NEEDS_EVIDENCE`, and `SURVIVED`.
- Mark previously surviving submissions `REOPEN` when the base branch moves; never silently rebase old evidence.
- Bind the signed outcome hash into the trusted PR receipt.
- Add a frozen three-arm release-gate runner and a live HTTP spam-control probe.

## 0.1.0

First standalone OpenLine Airlock release.

- `airlock init` finds the repo’s existing test, lint, and typecheck commands and confirms the starting branch is green.
- `airlock run` fans one task out to isolated agent worktrees and blocks patches that touch protected files, fail static checks, break existing tests, or lack enough evidence for unattended review.
- `airlock verify` validates a saved verification record against the exact base commit, candidate commit, changed-file boundary, and recorded check results.
- Built-in adapters support common installed coding-agent CLIs, with custom commands available in `.airlock/config.json`.
- Cost output preserves missing provider economics as unknown instead of estimating them.

## Unreleased — AIRLOCK-SUBMIT-001

- Add an experimental pre-PR path for public coding-agent contributions.
- Authenticate submissions through signed GitHub issue-comment webhooks.
- Enforce one open candidate per submitter/issue, account-age and daily caps, and a global active-work ceiling.
- Reject protected-path changes before candidate code is executed, including rename/copy source and destination paths.
- Require public evaluation to run in Docker with no network, no repository credentials, dropped capabilities, a read-only root filesystem, and resource ceilings.
- Keep the GitHub write credential in a separate PR-opener process that consumes only a sealed static patch and evaluation record after the sandbox is gone.
- Attach base/patch/config hashes and exact check results to the resulting PR.

## AIRLOCK-CHALLENGE-001

- freezes the first real outside-contributor acceptance check in the repo-owned Airlock config
- makes protected contribution surfaces explicit in `CONTRIBUTING.md`
- refreshes the GitHub install manifest after the 0.1.3 runtime fixes
- replaces the synthetic Show HN fixture with launch copy that makes no run-count claims
