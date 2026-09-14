# RIL-RANK-LIVE-001 — matched Prince contact test for the frozen ranking signal

RIL-RANK-EXEC-001 established controlled executable transfer of the exact frozen RIL-RANK-001 evidence-derived ordering. It did not test whether a live researcher would preserve that advantage.

RIL-RANK-LIVE-001 is the smallest live successor. Two separately initialized Prince / Muse Spark 1.3 sessions receive matched 16-task packets. Candidate IDs, descriptions, feature metadata, shared history, public task information, available-tool policy, and limits are identical. The only visible packet input allowed to differ is the presentation order of the same 12 candidates: exact frozen evidence ranker versus exact frozen baseline order.

Prince may select any four candidates from the full 12, not merely the first four. The receiver logs exactly what Prince selects and then executes those four deterministic candidates in Prince's returned order. This is deliberate: if Prince ignores or reconstructs the presentation order and the inherited ranking advantage disappears, that is a valid negative result rather than a protocol failure.

The primary has 16 paired tasks. The preregistered 12.5-point threshold is therefore exactly **two additional receiver-confirmed successes** for the inherited-order arm. A pass also requires fewer downstream receiver evaluations, complete valid matched responses, and a complete cost record inside the frozen spend rule. Paired outcomes, selected candidate IDs and their presented positions, evaluation counts, tool-use telemetry, researcher session counts, incremental paid spend, and the inherited 768-evaluation learning cost are preserved separately.

The experiment has a hard additional paid-spend ceiling of **$2.56**. Each of the two required Prince sessions has at most **$1.28** of incremental paid-spend authorization; no separately billed extra tools/services are allowed. If either matched session cannot complete within its authorization, the experiment freezes `BUDGET_EXHAUSTED_BEFORE_MATCH_COMPLETE`. No retry, extra session, provider swap, threshold change, or budget increase is allowed under RIL-RANK-LIVE-001.

A positive result earns only **single-run live selection transfer** on these executable microtasks. It does not establish repeatability, live coding productivity, Level 4 recursive improvement, recursive self-improvement, production value, universal transfer, economic payback, or hostile-process isolation.

## Run boundary

1. Merge the corrected preregistered tree and pin the resulting exact commit.
2. Run `prepare` once. It seals candidate orders before task-data nonce creation, randomizes which blinded session receives which ordering, proves that visible packet content differs only by candidate-list order, and emits `session-1/packet.json`, `session-2/packet.json`, receiver-only mapping, and a cost-record template.
3. Give only the file named `packet.json` plus `PRINCE_PROTOCOL.md` to one fresh Prince session at a time. Do not reveal receiver mapping or the matched packet.
4. Record actual incremental paid costs and their billing basis/source. If a session would exceed its $1.28 authorization, stop and freeze the budget-exhausted outcome.
5. Score exactly one response from each session. Freeze the first terminal result. Structural CI never fabricates live evidence.
