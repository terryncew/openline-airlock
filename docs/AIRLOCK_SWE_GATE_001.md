# AIRLOCK-SWE-GATE-001

Status: PREREGISTERED EXTERNAL BENCHMARK — NO RESULT YET

## Trigger

SWE-Gate (arXiv:2609.04167) released a deterministic external corpus showing that a patch can pass functional tests while violating maintainer-derived review constraints.

This earns one bounded falsifier for current OpenLine Airlock. It does not earn a new feature.

## Question

Does Airlock v0.4.0, with its existing zero-config Starter Rules and acceptance logic unchanged, distinguish externally validated functional-pass/review-fail patches from corresponding functional-pass/review-pass gold patches?

The test is deliberately unfair to our marketing claim in the useful direction: Airlock does not get to import SWE-Gate's hidden constraint tests or add benchmark-specific rules before seeing the result.

## Frozen inputs

- Airlock repository: `terryncew/openline-airlock`
- Airlock base: `11e99ee762b4e4a8b593c96cf3a5e175a5edba88`
- SWE-Gate repository: `DeepSoftwareAnalytics/SWE-Gate`
- SWE-Gate commit: `5f303b30dd53af3499d05558cfd82eda641be22b`
- Sample seed: `AIRLOCK-SWE-GATE-001|11e99ee762b4e4a8b593c96cf3a5e175a5edba88|5f303b30dd53af3499d05558cfd82eda641be22b|distinct-repo-v1`

The workflow proves the experiment branch's product paths are byte-identical to the frozen Airlock base in `src/airlock`, `src/airlock_submit`, and `pyproject.toml`.

## Frozen sample

Select exactly 12 distinct SWE-Gate repo IDs.

For each repo, select one eligible instance deterministically. Both the repo order and the within-repo instance choice are ranked by SHA-256 from the frozen seed.

Eligibility is determined before execution from the released validation matrix:

- noncompliant patch passes the functional test;
- noncompliant patch fails the review constraint;
- gold patch passes the functional test;
- gold patch passes the review constraint;
- released patch and metadata files are present.

The selected IDs are written to `selected.json` before any selected image is evaluated. There are no post-hoc sample swaps. A different sample would require a separately preregistered run.

Primary sample: 12 repos / 12 instances / 24 Airlock patch evaluations.

## Protocol

For each selected instance:

1. Rebuild the exact released SWE-Gate Docker image from the pinned repository.
2. Re-run SWE-Gate's own evaluator on the noncompliant and gold patches.
3. If the released truth does not reproduce, mark the experiment inconclusive for external-truth drift; do not substitute another instance.
4. In a fresh copy of the released mutant baseline, run the current `airlock init` unchanged.
5. Do not inject SWE-Gate's hidden constraint tests, edit `.airlock/config.json`, add target commands, change protected paths, or alter thresholds.
6. Evaluate the noncompliant patch using the current Airlock primitives and current disposition semantics.
7. Evaluate the gold patch independently from the same baseline and same generated Starter Rules.
8. Record the full checks, reason, disposition, config hash, and pair class.

Current Airlock semantics are not rewritten for the benchmark:

- protected-surface change → `BLOCKED`
- target failure → `BLOCKED`
- static failure → `BLOCKED`
- regression failure → `BLOCKED`
- insufficient evidence → `NEEDS_EVIDENCE`
- configured checks + sufficiency pass → `SURVIVED`

## Pair classes

`DISCRIMINATED`
- noncompliant patch is withheld (`BLOCKED` or `NEEDS_EVIDENCE`);
- gold patch `SURVIVED`.

`UNDERCONSTRAINED`
- noncompliant patch `SURVIVED`;
- gold patch `SURVIVED`.

`OVERCONSERVATIVE_OR_INSUFFICIENT`
- both patches are withheld.

`INVERTED`
- noncompliant patch `SURVIVED`;
- gold patch is withheld.

Blanket rejection is not counted as successful discrimination. The gold control exists specifically to prevent that mistake.

## Preregistered verdicts

`CURRENT_GATE_NOT_REVIEW_COMPLETE`
- at least one live-verified `UNDERCONSTRAINED` pair exists.

`EXTERNAL_CONSTRAINT_DISCRIMINATION_EARNED`
- all 12 live-verified pairs are `DISCRIMINATED`;
- no external-truth, build, or initialization failure occurs.

`INCONCLUSIVE_CONSERVATIVE_GATE`
- no `UNDERCONSTRAINED` pair exists, but at least one pair is overconservative, inverted, or otherwise not cleanly discriminated.

`INCONCLUSIVE_EXTERNAL_TRUTH_DRIFT`
- one or more selected released truth pairs no longer reproduce.

`INCONCLUSIVE_AIRLOCK_INIT_FAILURE`
- current zero-config Airlock cannot establish a green Starter Rules baseline in one or more selected released environments.

Infrastructure failures remain inconclusive and do not earn a product claim.

## Falsifier

One clean `UNDERCONSTRAINED` pair is enough to falsify the strong reading that current zero-config Airlock is review-complete.

That result would mean:

- SWE-Gate independently proves both patches solve the functional issue;
- SWE-Gate independently proves only the gold patch satisfies the maintainer-derived constraint;
- current Airlock nevertheless admits both.

If that happens, freeze the negative result exactly. Do not patch Airlock during this experiment.

## Integrity rules

- No benchmark-specific changes to Airlock product code.
- No benchmark-specific Starter Rules or hidden constraint tests.
- No post-hoc evaluator changes.
- No sample replacement after `selected.json` is written.
- No reruns to improve the verdict.
- External truth is rechecked live before Airlock's result counts.
- Gold controls are mandatory.
- Build or environment failure is not converted into a substantive success or failure.

## Result handling

The GitHub Actions run uploads the full receipt directory. On a successful benchmark run, the workflow commits only the frozen `result.json` and human-readable result summary back to the experiment branch.

No product fix is authorized automatically by either outcome. The result must earn the next move.
