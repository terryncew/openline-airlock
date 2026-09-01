# Governed continuous improvement

**airlock improve** lets coding agents search repeatedly without letting them define success or update **main**.

The operator commits one objective under **.airlock/**. That file names a measurement command, the direction of improvement, the minimum gain, a complexity penalty, and hard limits on files, changed lines, and generations.

    mkdir -p .airlock/objectives
    cp examples/objective-test-runtime.json .airlock/objective.json
    cp examples/measure-test-runtime.py .airlock/objectives/measure-test-runtime.py
    git add .airlock
    git commit -m "chore: define Airlock objective"

    airlock improve --generations 10 --agents 4

For a persistent Hermes worker, the specialized surface is:

    airlock nightshift --generations 10

Nightshift defaults to one Hermes profile per generation and keeps the same operator-owned objective and receipt chain. Parallel Hermes competition requires distinct profiles. See `docs/NIGHTSHIFT.md`.

The measurement command must print a JSON object on its final non-empty stdout line:

    {"value": 12.34}

## What happens in one generation

1. Airlock measures the frozen starting commit several times.
2. Isolated agents each propose and implement one bounded improvement.
3. Existing Starter Rules reject protected-path changes and failed checks.
4. Airlock measures each structurally surviving commit in a fresh worktree.
5. A candidate's worst measured result must clear the starting commit's best result by the configured minimum. Overlapping noisy measurements do not count as improvement.
6. The operator-owned score subtracts the configured change-complexity penalty from that conservative gain.
7. Exactly one score must win by the configured gap. A tie or weak result stops the loop.
8. The winner becomes the next generation's base on **airlock/improve/&lt;run-id&gt;**.

Each accepted generation is one normal Git commit, so the sequence is inspectable and reversible. Airlock writes a signed, hash-chained receipt for every generation and a final report under **.airlock/improvements/**.

Verify the chain without running candidate code:

    airlock improve --verify .airlock/improvements/<run-id>/report.json

## The authority boundary

The objective and evaluator belong to the operator. Keep evaluator implementation under **.airlock/** or another protected path and list non-obvious dependencies in **measure.protected_evaluator_paths**. Airlock fingerprints those files, refuses to start when any listed evaluator path is unprotected, and independently rejects a candidate whose actual changed-file set reaches a protected path.

Candidate and measurement subprocesses receive no release key, GitHub token, SSH agent, or ordinary Git credential configuration. Measurement commands receive only environment variables explicitly listed in **measure.pass_env**.

The loop never checks out or moves **main**. It compounds only on its dedicated Airlock branch. A pull request, merge rule, deployment gate, or human still decides whether that branch becomes real.

## What this does not establish

A number is only as good as the objective behind it. This mechanism does not prove that one scalar captures total product value, that a local benchmark predicts production, or that a worktree is a hostile-code sandbox.

Airlock records provider-reported spend and keeps unknown spend unknown. It does not use that self-reported value to choose a winner. Dollar ROI needs independently authenticated billing evidence, which is not part of this release.

For production-facing objectives, use frozen telemetry snapshots or a separately isolated evaluator. Do not expose production credentials to candidate code. A live canary/deployment loop remains outside this release.
