# AUTORESEARCH-GATE-001

**Receiver-owned advancement for Karpathy's `autoresearch`.**

Pinned upstream: `karpathy/autoresearch@228791fb499afffb54b46200aca536f79142f117`.
OpenLine base: `openline-airlock@4e726e47eccfa0e460aec7f69400e6eec8b0350e`.

Karpathy's loop deliberately gives the researcher one mutable file (`train.py`), a fixed evaluator/data layer (`prepare.py`), a five-minute training budget, and one metric (`val_bpb`, lower is better). The stock `program.md` also gives the agent the operational keep/discard loop: commit, run, read the score, keep or reset, repeat.

This experiment changes one thing: **the researcher can propose, but a receiver decides what survives.**

The OpenLine overlay keeps `train.py` as the only admissible research mutation. `prepare.py`, `program.md`, dependencies, and `.airlock/` are protected. A candidate is evaluated in a clean worktree. The mutable `train.py` may print anything it wants, but its printed `val_bpb` is not the receiver score: the protected measurement wrapper intercepts the protected `prepare.evaluate_bpb` result and emits the final machine-readable score itself. Acceptance receipts are HMAC-signed and bind the upstream pin, accepted base commit, exact candidate commit/tree, changed paths, objective, configuration, baseline measurement, and candidate measurement.

## What the CI proof establishes

`run_control_plane_proof.py` clones the exact upstream pin and proves the boundary without requiring an NVIDIA GPU. It requires all of the following to pass:

- the exact upstream commit and immutable blob set are bound;
- a `train.py`-only candidate is admissible;
- a `prepare.py` mutation is rejected;
- adding a new file such as `sitecustomize.py` is rejected;
- a fake `val_bpb` printed by candidate code cannot become the receiver score;
- bypassing the protected evaluation call produces no valid score;
- a signed receipt is bound to the exact base and candidate;
- changing the candidate in a signed receipt invalidates the signature;
- a valid receipt promotes once; replay after the accepted base moves fails closed.

Positive CI verdict: `PASS_AUTORESEARCH_GATE_001_CONTROL_PLANE`.

That verdict is **not** a model-training result. It does not say OpenLine improves `val_bpb`, research yield, or GPU economics. It also does not claim hostile-process or OS-level isolation. It says the external autoresearch loop can be wired so the generator no longer owns the protocol decision about what survives.

## Live GPU use

A live run needs the same environment Karpathy's pinned setup expects: a compatible NVIDIA GPU, Python 3.10+, `uv`, prepared data/tokenizer, and the pinned upstream dependencies.

Clone and checkout the exact pin, then apply the overlay with `setup_overlay.py --repo <clone> --commit`. Install Airlock into the Python environment used by the clone. Export `AUTORESEARCH_HOST_CACHE` to the already-prepared `~/.cache/autoresearch` directory. The receiver deliberately passes that one cache location through Airlock while leaving the candidate worktree HOME isolated.

Initialize the receiver once:

```text
python .airlock/receiver_gate.py init
```

Point the research agent at `.airlock/openline-program.md`. The agent may commit only `train.py`. For each candidate commit:

```text
python .airlock/receiver_gate.py evaluate <candidate-sha>
python .airlock/receiver_gate.py promote <receipt-path> --candidate <candidate-sha>
```

`step <candidate-sha>` performs those two protocol phases consecutively when the receiver receipt says ACCEPT. The split commands are preferable for evidence inspection.

The accepted baseline measurement is cached receiver-side. After initialization, each new candidate therefore needs one receiver training run rather than re-running the accepted baseline every generation.

## Why this is not RIL-002

RIL-002 remains reserved for repeatability after a recursive advantage is actually observed. AUTORESEARCH-GATE-001 is an externally recognizable integration test: can the existing OpenLine acceptance boundary wrap a real autonomous research loop without handing acceptance authority to the researcher?
