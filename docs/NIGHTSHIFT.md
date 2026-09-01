# Hermes Nightshift

`airlock nightshift` connects Hermes to Airlock's governed continuous-improvement loop.

Hermes remains the worker. Airlock remains the independent promotion boundary.

```bash
airlock nightshift \
  --objective .airlock/objective.json \
  --generations 10
```

The default is one Hermes attempt per generation. Airlock invokes the official scripted one-shot interface:

```text
hermes -z "{prompt}"
```

The same Hermes profile may persist across generations, so its memory, sessions, and skills can evolve while it works. That mutable worker state does not become the objective, evaluator, or promotion rule.

Each generation follows the existing Airlock chain:

1. measure the frozen base with the operator-owned objective;
2. let Hermes propose one candidate in an isolated worktree;
3. reject protected-path changes and failed repository checks;
4. measure the surviving candidate independently;
5. promote only a uniquely evidenced improvement onto `airlock/improve/<run-id>`;
6. sign the generation receipt and continue from the promoted commit.

The starting branch never moves.

## Credentials

The built-in Hermes adapter forwards `HERMES_HOME` only. A key-based setup may name one additional provider credential in protected `.airlock/config.json`:

```json
{
  "providers": {
    "hermes": {
      "command": ["hermes", "-z", "{prompt}"],
      "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"]
    }
  }
}
```

Airlock still strips GitHub tokens, SSH-agent state, verification/release keys, and release/deploy/signing-key patterns from the worker environment. Worker Git push is disabled and `AIRLOCK_RELEASE_AUTHORITY=ABSENT`.

`HERMES_HOME` is trusted worker state, not a sandbox. It may contain credentials, memory, sessions, or skills. Native worktree execution also does not stop a hostile process from reading other host paths that the operating-system user can read.

## Parallel Hermes workers

A writable Hermes profile is part of the worker's state. Two supposedly independent candidates sharing one profile can influence one another through memory, skills, sessions, or configuration.

Airlock therefore refuses parallel Nightshift competition unless every candidate has a distinct Hermes profile:

```bash
airlock nightshift \
  --agents 2 \
  --profiles worker_a,worker_b \
  --generations 5
```

This becomes:

```text
hermes -p worker_a -z "{prompt}"
hermes -p worker_b -z "{prompt}"
```

Profile isolation is a worker-independence rule. It is not a claim that the host filesystem is isolated.

## Usage receipts

Every generation receipt binds the worker alias, compact external-process execution record, optional provider/model report, repository checks, objective measurement, selection result, and promoted commit. The final signed report carries per-generation worker usage.

Provider-reported spend remains provider-reported. If Hermes or its provider does not supply cost data through Airlock's agent-report seam, cost stays unknown rather than being estimated.

## Where the Independent Gate's three clocks land

The three-clock distinction is relevant, but only two clocks belong inside this software promotion loop.

**Truth / epistemic clock:** repository checks and the protected measurement command run downstream of generation. Hermes can propose an improvement but cannot rewrite the evidence that defines success.

**Authority / transactional clock:** protected config, objective standing, branch isolation, signed receipts, and the later merge/deployment decision remain outside Hermes. A passing patch is evidence, not permission to deploy itself.

**Time / dynamical clock:** Airlock Nightshift is not a sub-second live feasibility controller for physical systems. For robots or other fast actuators, a separate live inhibit layer must still check the feasible action set at execution time. A batch software receipt cannot substitute for that control loop.

The planner may imagine what could happen. A live physical boundary still decides what can happen now.

## Claim boundary

The bundled external-process test uses a fake executable named `hermes` through the exact `hermes -z` adapter. It proves that a worker can receive one explicitly selected model credential, receive no GitHub credential or Airlock release authority, produce a patch, have that patch independently admitted and measured, and leave the starting branch unchanged.

It is not a paid live-Hermes receipt. A real installed Hermes run remains the final compatibility gate before claiming an end-to-end public Nightshift demonstration.
