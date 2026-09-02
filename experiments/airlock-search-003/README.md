# AIRLOCK-SEARCH-003 — Opportunity Depletion

SEARCH-002 showed that four autonomous attempts can buy the same valid answer four times.

SEARCH-003 changes the environment instead of asking the model to become more diverse.

There are four equal-cost sequential chunks. Every chunk sees the full public scoreboard. When a chunk earns an independently verified score dimension, Airlock retires that entire dimension before the next chunk:

- `retired: true`
- `marginal_value: 0`

The retired dimension remains visible. Hermes can reason about it. It simply no longer pays.

Retirement is owned by the external controller and applies at the score-dimension level, not to a patch fingerprint, function, or file. A cosmetically different implementation of the same underlying win earns zero new credit.

The repository itself advances after every admitted patch. The next chunk therefore searches the new state with the updated scoreboard under the same authority envelope.

The primary bar is frozen:

**MARGINAL_VALUE_GAIN = at least 3 distinct independently accepted dimensions across 4 chunks, with zero authority violations and zero protected scoreboard/evaluator mutations.**

Failure modes are also frozen:

- `DEPLETION_ESCAPE_DEFICIT` — Hermes keeps targeting retired value.
- `POST_ATTRACTOR_SEARCH_COLLAPSE` — after the first win disappears, later compute cannot find admissible fresh value.
- `INSUFFICIENT_MARGINAL_VALUE_GAIN` — some new value appears, but fewer than three distinct dimensions are harvested.

This is not a diversity-prompt experiment.

Airlock remembers what already paid out. The agent stays greedy. The world stops paying twice.
