# AIRLOCK-HYDRAFUSION-001

Status: PREREGISTERED DESIGN — NO WORKER RUNS YET

## Trigger

GitHub released HydraFusion as a GitHub Copilot CLI research preview on
2026-09-04. HydraFusion chooses a compound workflow across multiple models at
runtime and is currently recommended for substantial, well-scoped, first-turn
coding tasks.

This external event reopens Airlock for one bounded experiment.

## Question

Can worker identity and worker orchestration change underneath Airlock while
the repository-owned definition of earned improvement remains fixed?

This experiment does **not** ask whether HydraFusion is better than Opus or
Codex. Different workers may produce different patches and therefore receive
different decisions.

It asks whether the same candidate is judged the same way regardless of the
producer label, and whether live candidates from different workers can be
admitted through the same frozen evaluator without provider-specific judgment
logic.

## Claim under test

> Worker identity may change. Judgment does not.

A successful result would support the narrower architectural claim:

> Airlock can evaluate candidates from different worker systems under one
> receiver-owned scoreboard without giving those workers control over the
> scoreboard.

It would **not** prove that every coding agent is interchangeable, that
HydraFusion is superior, or that one tournament predicts general coding quality.

## Two-stage protocol

### Stage A — producer-label invariance

Freeze one base commit, one candidate patch, one Airlock configuration, one
objective, one evaluator, one protected-path set, and one minimum improvement
threshold.

Evaluate the exact same candidate three times.

The only experiment metadata that changes is:

- producer = `hydrafusion`
- producer = `opus`
- producer = `codex`

Producer identity MUST NOT be an input to the substantive evaluator.

Pass condition:

- same substantive admission decision;
- same reason codes;
- same measured objective result;
- same protected-surface result;
- same evaluator/config hash;
- no producer-specific code path changes the decision.

Receipt metadata may record the producer label. Timestamps, run IDs, signatures,
and receipt hashes are expected to differ and are excluded from the invariance
comparison.

Failure condition:

- producer identity changes any substantive admission result for the identical
  candidate.

Stage A is a neutrality check only. It is not the live market test.

### Stage B — live worker tournament

Freeze before any worker invocation:

- target repository;
- exact starting commit;
- exact first-turn task;
- repository checks;
- protected paths;
- objective and measurement command;
- minimum improvement threshold;
- attempt count per worker;
- wall-clock/budget treatment;
- candidate patch format;
- Airlock evaluator/config hash.

Workers:

1. HydraFusion research preview through GitHub Copilot CLI.
2. Claude Opus through its ordinary coding-host path.
3. Codex through its ordinary coding-host path.

Each worker receives the same task text and the same starting repository state.
Each gets the same number of attempts unless a host limitation makes that
impossible; any asymmetry must be frozen before the first worker runs.

A thin launcher or output-normalization adapter is allowed only to obtain a
standard candidate patch. It may not change tests, protected paths, objective,
thresholds, evaluator behavior, or promotion logic.

Every candidate is judged by the same Airlock gate.

## Recorded metrics

Per worker:

- attempts;
- candidate patches produced;
- Airlock disposition for each candidate;
- verified improvements;
- objective delta;
- rejects;
- protected-surface violations;
- test/regression failures;
- unknown/failed attempts;
- provider-reported spend when available, otherwise `UNKNOWN`;
- human task assignments;
- final promotion outcome.

Cross-worker:

- config hash;
- evaluator/objective hash;
- protected-path set;
- threshold;
- whether any provider-specific judgment exception was required.

Do not convert `UNKNOWN` spend to zero.

## Falsifier

The architectural claim fails if a worker's candidate cannot be judged fairly
without changing the receiver-owned definition of success for that worker.

Examples:

- a HydraFusion-specific acceptance threshold;
- provider-specific protected-file exceptions;
- provider identity influencing score or disposition;
- evaluator changes made after seeing one worker's candidate;
- changing the frozen task or objective between workers;
- silently discarding failed/unknown attempts from accounting.

A worker needing a different launcher is not itself a failure. A worker needing
a different scoreboard is.

## Outcome labels

`WORKER_NEUTRALITY_EARNED`
- Stage A passes; and
- Stage B completes with one frozen scoreboard for all workers; and
- no provider-specific judgment logic is introduced.

`WORKER_NEUTRALITY_FAILED`
- producer identity affects Stage A; or
- Stage B requires provider-specific judgment logic.

`INCONCLUSIVE_HOST_LIMITATION`
- the live tournament cannot complete because a research-preview or host
  limitation prevents one worker from producing a standard candidate before
  substantive evaluation.

Worker quality outcomes are reported separately and do not determine the
neutrality verdict.

## Sequencing rule

This is one externally-triggered Airlock experiment, not a new Airlock roadmap.

After the result is frozen:

1. Stop Airlock work again.
2. Return to `RUNTIME-CONTRACT-001`.
3. Do not build a HydraFusion dashboard, generic Copilot integration, worker
   marketplace, or v0.5 feature set unless outside use produces a separate
   trigger.

## Required task-freeze receipt

Before Stage B runs, commit a separate task-freeze receipt containing the
target repo, base SHA, exact task text, objective/evaluator hashes, checks,
protected paths, threshold, attempt counts, and execution commands.

No worker may run before that receipt is merged.
