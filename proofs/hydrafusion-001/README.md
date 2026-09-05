# AIRLOCK-HYDRAFUSION-001 — Frozen result

Status: **FROZEN**

Main at freeze:

`2c28e9dde63f9fef01244b3348baffd73abeb7c4`

## Stage A

`STAGE_A_PRODUCER_LABEL_INVARIANCE_PASS`

With the same patch and the same receiver-owned evaluator, changing only the
producer label did not change Airlock's judgment.

That established label invariance. It did not establish live-worker invariance.

## Stage B host preflight

Workflow run:

`33935101501`

Result:

```text
INCONCLUSIVE_HOST_LIMITATION

Codex       PASS / gpt-5.6-sol
HydraFusion HOST_LIMITATION
Opus        PASS / claude-opus-5

task prompt sent  false
worker contact    false
```

HydraFusion could not be authenticated/listed through the documented GitHub
Actions `GITHUB_TOKEN` path under the frozen noninteractive host contract.
Because the preregistration required an exact HydraFusion host before any task
contact, Stage B stops here.

Result SHA-256:

`14fc386db35e08a0757e2d908709c3554ac779d55ea581b25bab6db2ea10a69a`

Artifact ZIP SHA-256:

`70eab5ba39e123132843072761a324daae4f948ecdfa492ef0d0808d7fc2bb43`

Artifact ID:

`9959887805`

Frozen Stage B task prompt SHA-256:

`3fc95b7222c8e2be1e16225853baa493add997d7da583c4e656e541a840d76a0`

## Earned

Airlock Stage A was invariant to producer labels under a fixed patch and fixed
evaluator.

## Not earned

No real HydraFusion/Codex/Opus worker comparison occurred.

No Stage B task prompt was sent.

No provider performance, cost, or worker-neutrality claim is earned from this
experiment.

## State after freeze

`AIRLOCK_MARKET_LEARNING_MODE`

Do not keep probing HydraFusion internally. Reopen only if an external host
change, provider-supported noninteractive path, user demand, or competitive
event creates a genuinely new test condition.
