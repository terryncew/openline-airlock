# AUTORESEARCH-LIVE-001

Live A100 follow-up to AUTORESEARCH-GATE-001. The worker is Meta Muse Code; the research substrate is the exact pinned `karpathy/autoresearch`; the receiver is the already-proved OpenLine gate.

The experiment changes no Karpathy scientific constant to manufacture discrimination. The upstream fixed seed remains 42, the training budget remains five minutes, and `val_bpb` remains the single continuous objective. There is one receiver-owned baseline run and one receiver-owned run per submitted candidate. At most two Muse proposals may be submitted; the experiment stops after the first ACCEPT or after proposal two regardless.

This is intentionally not a repeatability claim. A surviving candidate earns an observed fixed-seed improvement and a governance receipt. A rejected candidate can still complete the governance proof: Muse proposed, Airlock measured, Airlock refused advancement.

## Integrity boundary

Before the baseline, `live_driver.py snapshot` records every tracked file except `train.py`, the exact bootstrap commit/tree, the preregistration hash, observed GPU identity, Muse version when available, and the experiment clone's disabled push URL. Every receiver decision requires a clean worktree and verifies those protected hashes before and after measurement. New/untracked files fail closed. Existing `receiver_gate.py` additionally requires the candidate's committed diff from the accepted base to be exactly `train.py` and binds the signed receipt to the exact base and candidate.

This remains repository-state governance, not hostile-process isolation. Muse may have other network capability; the claim is narrower: the local accepted state in this experiment cannot advance through the protocol without the receiver's exact-candidate receipt.

## RunPod bootstrap

From a fresh RunPod terminal after this branch exists:

```text
cd /workspace && git clone --branch experiment/autoresearch-live-001 --single-branch https://github.com/terryncew/openline-airlock.git && cd openline-airlock && bash experiments/autoresearch-live-001/bootstrap_runpod.sh
```

The bootstrap verifies the GPU, clones the exact Karpathy pin, disables git push in the research clone, installs the existing receiver overlay, syncs the pinned upstream environment, prepares the persistent cache, freezes integrity evidence, and performs the one receiver-owned baseline run.

Then invoke Muse from `/workspace/autoresearch-live-001` with `MUSE_PROPOSAL.md`. When Muse has committed a clean local candidate, submit it with:

```text
python /workspace/openline-airlock/experiments/autoresearch-live-001/live_driver.py step HEAD
```

On REJECT, the driver preserves the candidate as `openline/rejected-<n>` and hard-resets the research branch to the receiver-accepted state before another proposal. On ACCEPT, Airlock promotes the exact signed candidate and the experiment becomes terminal immediately. Proposal two is terminal regardless of result.

Evidence is written outside the worker repo at `/workspace/autoresearch-live-evidence/`, including copied signed decision receipts and terminal `AUTORESEARCH_LIVE_001_RESULT.json`.
