# Changelog

## 0.1.0

Initial standalone OpenLine Airlock MVP.

- `airlock init`: repository discovery, protected surfaces, green baseline check.
- `airlock run`: N isolated candidate worktrees, BYOA command adapters, protected-surface elimination, static checks, frozen regression checks, evidence-sufficiency hold, single-survivor fail-closed admission, optional GitHub PR creation.
- `airlock verify`: offline deterministic receipt validation without re-running generation.
- receiver-local signed proof receipts and flat reverse evidence index.
- explicit claim boundary: receipts describe verified evidence and do not claim correctness outside it.
