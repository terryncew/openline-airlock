## AI-assisted contributions

AI-assisted contributions are welcome here. Raw agent-generated PRs are not.

If an agent produced the patch, submit the commit through Airlock from the issue you are fixing:

```text
/airlock submit YOUR_GITHUB_USER/YOUR_FORK@FULL_40_CHARACTER_COMMIT_SHA
```

Airlock runs the patch against this repository's checks before it reaches the maintainer queue. If it survives, Airlock opens a normal PR with the exact checks that ran attached to the PR. If it fails, no maintainer has to spend time discovering that for you.

Use whatever coding agent you want. The repo decides what passes.
