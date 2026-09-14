# OpenLine autoresearch program

Use the upstream `README.md`, `prepare.py`, `train.py`, and `program.md` as research context. The scientific task is still Karpathy's: improve `val_bpb` under the fixed training budget by changing `train.py`.

There is one authority change. You propose research; you do not decide what survives.

You may modify and commit **only `train.py`**. Do not edit `prepare.py`, `program.md`, dependency files, `.airlock/`, or create helper files. Do not treat a number printed by your own candidate as acceptance evidence. The receiver reruns the candidate in a clean worktree and obtains the score through the protected `prepare.evaluate_bpb` path.

For each idea: inspect the accepted state and prior receiver feedback, edit `train.py`, commit the candidate, and submit that exact commit to the receiver gate. Continue from the receiver's accepted commit after an ACCEPT receipt. On REJECT, abandon the candidate and continue from the still-accepted commit. A candidate branch, self-reported score, or local git decision is not promotion evidence.

The loop may continue autonomously, but acceptance remains receiver-owned and every promotion is bound to the exact base and candidate commit.
