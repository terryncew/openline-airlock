<!-- openline-airlock:begin -->
## AI-assisted contributions

**AI agents are welcome. Raw AI-generated PRs are not.**

If an agent generated the patch, submit the commit on the relevant issue before opening a PR:

```text
/airlock submit YOUR_GITHUB_USERNAME/YOUR_FORK@FULL_40_CHARACTER_COMMIT_SHA
```

Airlock checks the patch against this repository's protected files and configured tests before it reaches the maintainer queue. If it survives, Airlock opens the PR. If it fails, the issue gets the exact reason.

Use whatever coding agent you want. **The repo decides what passes.**
<!-- openline-airlock:end -->
