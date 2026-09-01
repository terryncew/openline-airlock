# AIRLOCK-PUBLIC-COLD-ADOPTION-001

Status: **FAIL — boundary was not exercised**

The intended test required a candidate commit from a real public fork to enter through `/airlock submit OWNER/REPO@SHA`, survive the live GitHub Actions evaluator, and cause Airlock itself to open the resulting PR.

PR #14 did something different.

- Frozen base: `739da7711809e4d765141fc73170ca430e0ef4a2`
- Candidate head: `32b2e0d8f1ccdc10ae69e549ecb76736794e3569`
- Merge commit: `11506b95de8b22a88cf26d960ac8f9ae2d82f8ca`
- Base repository: `terryncew/openline-airlock`
- Head repository: `terryncew/openline-airlock`
- Path used: ordinary same-repository PR
- `/airlock submit`: **not used**
- Airlock-created PR: **no**

Therefore this run cannot support any claim about the live public-fork boundary.

The merged code change itself is retained. It is the behavior-preserving one-line `sha256_file()` refactor and does not weaken Airlock. Reverting it would only create noise.

## Next

`AIRLOCK-PUBLIC-COLD-ADOPTION-002` must begin from a newly frozen current `main` and wait for the discriminating event: a commit owned by a genuinely separate public fork enters through the issue-comment submission path.

No feature work is authorized before that passes.
