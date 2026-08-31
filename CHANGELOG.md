# Changelog

## 0.1.0

First standalone OpenLine Airlock release.

- `airlock init` finds the repo’s existing test, lint, and typecheck commands and confirms the starting branch is green.
- `airlock run` fans one task out to isolated agent worktrees and blocks patches that touch protected files, fail static checks, break existing tests, or lack enough evidence for unattended review.
- `airlock verify` validates a saved verification record against the exact base commit, candidate commit, changed-file boundary, and recorded check results.
- Built-in adapters support common installed coding-agent CLIs, with custom commands available in `.airlock/config.json`.
- Cost output preserves missing provider economics as unknown instead of estimating them.
