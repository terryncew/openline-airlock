# RIL-RANK-EXEC-001 — executable transfer of the frozen ranking signal

RIL-RANK-001 found a predictive ranking signal in a controlled synthetic, family-held-out calibration. That result was positive, but it did **not** show that the signal transfers to receiver-measured executable work.

RIL-RANK-EXEC-001 is the smallest next falsifier. It inherits the exact frozen RIL-RANK-001 policy seal and asks whether that ordering finds acceptable improvements earlier on fresh executable microtasks than (a) the frozen baseline ordering and (b) the frozen history-shuffled ordering. No new ranker training occurs in this experiment.

Primary metric: acceptable improvement found within four receiver evaluations. The same 12 candidates, task, evaluator, and four-evaluation budget are used by all three methods. Candidate orders are durably sealed before the task-data nonce exists. Candidate outcomes come from executing implementations against correctness oracles and deterministic operation-count objectives; they are not sampled from the synthetic RIL-RANK-001 gain function.

A positive result establishes only **executable transfer of the inherited ranking signal in this controlled microtask world**. It does not establish Level 4, live-agent productivity advantage, repeatability, production value, or universal transfer. If this transfer fails, do not spend on a larger live recursive campaign around this ranker. If it passes, the next earned boundary is a matched live-agent experiment using the same frozen policy and equal history access across arms.
