<!-- openline-airlock:begin -->
## AI-assisted contributions

**AI agents are welcome. Raw AI-generated PRs are not.**

If an agent generated the patch, send the commit through Airlock before opening a PR.

1. Fork this repository and start from current `main`.
2. Let any coding agent make the change, then push the commit to your public fork.
3. Copy the full commit SHA with `git rev-parse HEAD`.
4. On the issue you are fixing, comment:

```text
/airlock submit YOUR_GITHUB_USERNAME/YOUR_FORK@FULL_40_CHARACTER_COMMIT_SHA
```

Do **not** open a pull request yourself. Airlock will reply on the issue.

The acceptance checks are frozen by the maintainer. Do not modify `tests/**`, `.github/**`, `.airlock/**`, or `pyproject.toml`; those are protected surfaces and Airlock will reject the submission before candidate code runs.

- `BLOCKED` — the patch failed a repository rule. No PR is opened.
- `NEEDS_EVIDENCE` — the repository does not have enough evidence to justify review yet. No PR is opened.
- `REOPEN` — the base branch moved after evaluation. Refresh the patch against current `main` and submit again.
- `SURVIVED` — Airlock opens a normal PR and a maintainer reviews it like any other contribution.

No agent gets push access. No candidate decides what passing means.

Use whatever coding agent you want. **The repo decides what passes.**
<!-- openline-airlock:end -->
