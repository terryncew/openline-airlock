# AIRLOCK-UNATTENDED-001 — label an issue, walk away

Status: **IMPLEMENTED / LIVE GITHUB RUN NOT YET CLAIMED**

Base: `terryncew/openline-airlock@7a80eb2f5cf11afcf1033b68e6d637f7eea80cb1` (`v0.3.0` integration merge)

## Product boundary

Airlock already has the local loop:

`init → solve → autopilot → inbox → review`

AIRLOCK-UNATTENDED-001 moves one bounded unit of that loop onto GitHub infrastructure:

`maintainer applies airlock label → four independent attempts → independent gate → exactly one survivor may become a PR`

The maintainer does not run `airlock autopilot` from a laptop or phone. The label is the authorization to spend attempts on that issue.

This is also the first Airlock path that is deliberately shaped as a continuous-assurance control for autonomous software changes. The generator may propose code. It does not own the repository definition of passing, the evaluation environment, or GitHub publication authority.

## Three authority domains

### 1. Generation — capability, no repository write authority

Four independent candidate jobs start from the same frozen base SHA. The reference worker is the official OpenAI Codex GitHub Action, pinned to commit `86365089eb2b84e0a8fb0717b304f8bdcb13b20e`, using the `:workspace` permission profile.

Generation receives the provider credential needed to obtain model output. It has only `contents: read` GitHub permissions and checkout credentials are not persisted. After each attempt, trusted Airlock code captures the final repository tree as an inert binary patch plus a content-bound candidate manifest.

The generator action is a replaceable capability. The gate does not rely on Codex saying its own patch is correct.

### 2. Evaluation — no provider secret, no GitHub write authority

The independent gate checks out the same frozen base and builds the maintainer-owned `.airlock/Dockerfile` before candidate artifacts enter the job.

For every candidate it:

- verifies the candidate-manifest and patch hashes;
- refuses artifact capture if the generator altered the checkout's local Git configuration;
- re-derives the changed-file boundary from the patch;
- rejects protected paths before candidate code runs;
- executes configured target/static/regression commands in Docker with `--network none`;
- drops Linux capabilities, enables `no-new-privileges`, uses a read-only container root, and applies CPU/memory/PID ceilings;
- detects tracked-file side effects caused by evaluator commands;
- applies the existing evidence-sufficiency rule;
- preserves `NO_PATCH_READY` as a valid outcome;
- preserves multiple survivors as multiple survivors instead of inventing a winner.

The evaluation job receives neither `OPENAI_API_KEY` nor a GitHub write credential.

### 3. Publication — repository write authority, no candidate execution

Only the publication job can write to GitHub. It verifies the Airlock result receipt and survivor patch hash, fetches the current base branch, and refuses to rebase stale evidence.

If the base moved, the outcome is `REOPEN`.

If zero candidates survive, no PR appears.

If several candidates survive, Airlock comments that a human choice is required and does not choose one.

If every generator attempt failed as infrastructure, Airlock surfaces an environment failure rather than misreporting it as a normal dead end.

If exactly one candidate survives, the publisher applies the already-evaluated inert patch to the frozen base, rechecks the changed-path/protected-path binding, commits it, pushes a new Airlock branch, and opens a normal PR. It does not run tests, import candidate source, or execute candidate code after receiving GitHub write authority.

The PR body retains the base SHA, patch hash, config hash, receipt hash, workflow run identity, exact recorded commands, and exit codes.

## Mobile operating path

After this branch is merged, the live proof requires only two maintainer actions:

1. Add the repository Actions secret `OPENAI_API_KEY` once.
2. Add the `airlock` label to one open GitHub issue.

Both can be done from an iPhone. The live run should then require no terminal command and no manually opened PR.

Do not label a real issue until the secret is present. A missing credential is intentionally fail-closed.

## Pass condition for the next evidence claim

A real issue is labeled from the GitHub UI and, without local intervention:

1. four candidate artifacts are created from one frozen base;
2. the independent gate evaluates them without the provider secret and with candidate network disabled;
3. exactly one survivor, if one exists, is published by the trusted job;
4. the resulting PR contains the recorded Airlock receipt fields;
5. zero-survivor, multiple-survivor, base-moved, and generator-environment outcomes do not silently collapse into a PR.

Until that live run happens, the claim is **workflow mechanics implemented**, not **unattended production path proven**.

## Deliberate non-goals

This does not add SOC 2 mapping, compliance templates, dashboards, organization policy, hosted runners, or a vCISO product. It proves a narrower mechanical control: an AI-generated software change can be separated from the authority to decide that it earned review.

It also does not repair `AIRLOCK-PUBLIC-COLD-ADOPTION-001`; the genuine outside-fork contribution path remains a separate unproven boundary.
