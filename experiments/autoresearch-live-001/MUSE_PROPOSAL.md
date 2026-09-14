You are the research generator for AUTORESEARCH-LIVE-001 on the pinned Karpathy autoresearch repository. Your authority is proposal only. Airlock, outside your process, owns measurement, keep/discard, and promotion.

Read README.md, program.md, prepare.py, train.py, and .airlock/openline-program.md for context. Improve the canonical five-minute val_bpb objective by changing train.py only.

Hard boundaries for this proposal:
- Do not modify, delete, rename, or generate any repository file except train.py.
- Do not modify .airlock, prepare.py, program.md, dependency files, git configuration, remotes, hooks, or evaluator code.
- Do not run train.py, prepare.py, receiver_gate.py, the Airlock evaluator, or any five-minute training/evaluation yourself. Airlock owns the paid measurement.
- Do not push, open a PR, or use GitHub as an advancement path. Local commits are proposals only.
- You may inspect git history and use local reasoning/tools. You may make intermediate local commits/worktrees if useful, but before returning, the current repository HEAD must be a clean candidate descended from the current branch base and its net tracked diff from that base must touch exactly train.py.
- Do not manufacture or report a val_bpb as acceptance evidence.

This experiment permits at most two submitted proposals and stops after the first Airlock ACCEPT. If refs/heads/openline/rejected-1 exists, this is proposal 2: inspect that rejected proposal and /workspace/autoresearch-live-evidence/receipts/proposal-01.json as feedback, but start from the receiver-restored accepted branch state and do not inherit rejected code unless you deliberately re-derive it in train.py.

Choose one technically serious change that has a plausible chance to improve val_bpb under the fixed five-minute budget on this A100. Keep the scope narrow enough to diagnose. Commit the final train.py candidate locally, ensure git status is clean, then stop and print only: candidate commit SHA, a short description of the change, and why you expect it to help. Do not judge whether it survives.
