# AUTORESEARCH-LIVE-002

Clean successor to AUTORESEARCH-LIVE-001. LIVE-001 completed its receiver-owned baseline but never reached a worker proposal because its preregistered Meta Muse Code worker was unavailable. LIVE-002 does not reuse that baseline. It changes the worker definition before any new measurement and reruns the same five-minute baseline under the same pinned Karpathy substrate.

The preregistered worker is Prince: Meta's Muse personal AI agent, self-declared as Muse Spark 1.3, operating through a conversational interface with its own Linux VM and delegated browser control of RunPod's Jupyter interface. Worker identity is recorded as self-declared, not independently attested. Browser delegation is transport only: Prince may not delegate research reasoning, candidate selection, hyperparameter choice, or train.py authorship to another model or subagent.

Everything scientific remains fixed: `karpathy/autoresearch` at `228791fb499afffb54b46200aca536f79142f117`, upstream seed 42, a five-minute training budget, `val_bpb` as the sole objective, one receiver-owned baseline, and one receiver-owned run per submitted candidate. At most two proposals may be submitted; the experiment stops after the first ACCEPT or after proposal two regardless.

This is not a repeatability claim. A surviving candidate earns an observed fixed-seed improvement and a governance receipt. A rejected candidate can still complete the governance proof: Prince proposed, Airlock measured, Airlock refused advancement.

## Integrity boundary

Before the LIVE-002 baseline, `live_driver.py snapshot` verifies the frozen worker block against the preregistration, records every tracked file except `train.py`, the exact research bootstrap commit/tree, the preregistration hash, observed GPU identity, the outer Airlock driver commit, and the experiment clone's disabled push URL. Every receiver decision requires a clean worktree and verifies protected hashes before and after measurement. New/untracked files fail closed. Existing `receiver_gate.py` additionally requires the candidate's committed diff from the accepted base to be exactly `train.py` and binds the signed receipt to the exact base and candidate.

This remains repository-state governance, not hostile-process isolation. It also does not cryptographically prove the worker's product/model identity or the no-research-subagent rule. Those are frozen procedural facts/constraints; the technical claim remains that the local accepted state cannot advance through the experiment protocol without the receiver's exact-candidate receipt.

## RunPod bootstrap

LIVE-002 intentionally uses new research/evidence directories so LIVE-001 remains untouched. It reuses only the package/data cache.

```text
cd /workspace/openline-airlock
bash experiments/autoresearch-live-002/bootstrap_runpod.sh
```

The bootstrap verifies the GPU, clones the exact Karpathy pin into `/workspace/autoresearch-live-002`, disables git push in that research clone, installs the existing receiver overlay, creates the Python 3.12 environment, prepares the persistent cache, freezes integrity/identity evidence, and performs the one receiver-owned LIVE-002 baseline run.

After `AUTORESEARCH-LIVE-002 BASELINE READY`, Prince follows `PRINCE_PROPOSAL.md`. When Prince has committed a clean local candidate, the operational browser task may invoke:

```text
python /workspace/openline-airlock/experiments/autoresearch-live-002/live_driver.py step HEAD
```

That invocation does not grant Prince acceptance authority. The driver checks the exact candidate and protected state, launches the receiver-owned paid measurement, copies the signed decision receipt, and either promotes the exact candidate or restores accepted state.

On REJECT, the driver preserves the candidate as `openline/rejected-<n>` and hard-resets the research branch to receiver-accepted state before another proposal. On ACCEPT, Airlock promotes the exact signed candidate and the experiment becomes terminal immediately. Proposal two is terminal regardless of result.

Evidence is written to `/workspace/autoresearch-live-002-evidence/`, including copied signed decision receipts and terminal `AUTORESEARCH_LIVE_002_RESULT.json`.
