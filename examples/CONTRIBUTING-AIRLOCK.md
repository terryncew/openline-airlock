## AI-assisted contributions

**AI agents are welcome. Raw AI-generated PRs are not.**

If an agent generated the patch, submit the commit through Airlock before opening a PR:

1. Fork the repository and start from the current default branch.
2. Let any coding agent make the change and push the commit to your public fork.
3. Copy the full commit SHA with `git rev-parse HEAD`.
4. On the issue you are fixing, comment:

```text
/airlock submit YOUR_GITHUB_USERNAME/YOUR_FORK@FULL_40_CHARACTER_COMMIT_SHA
```

Do not open the pull request yourself. Airlock replies with `BLOCKED`, `NEEDS_EVIDENCE`, `REOPEN`, or `SURVIVED`. Only a survivor is turned into a normal PR for maintainer review.

No agent gets push access. No candidate decides what passing means.

Use whatever coding agent you want. **The repo decides what passes.**
