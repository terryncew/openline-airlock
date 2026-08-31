# Changelog

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
