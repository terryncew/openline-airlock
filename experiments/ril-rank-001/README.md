# RIL-RANK-001 — Failure-History Ranking Calibration

RIL-RANK-001 is a cheap calibration study motivated by the frozen RIL-001D primary result. RIL-001D showed that inherited generator policy could change search behavior, but that changed behavior did not improve productivity: both terminal arms solved 30/30 and the recursive arm cost more. RIL-RANK-001 does **not** rerun RIL-001D and does not claim recursive improvement.

It asks one narrower question:

> Does receiver-observed prior evidence help us spend fewer evaluations finding an acceptable improvement on unfamiliar task families?

The experiment is intentionally controlled and synthetic. It exists to falsify a proposed mechanism cheaply before funding another live-agent recursive trial.

## Three orderings

Every holdout task receives the same candidate pool and the same fixed evaluation budget.

1. **Baseline** — a frozen history-independent ordering.
2. **Evidence ranker** — the preregistered ranking rule learned only from receiver-observed calibration outcomes.
3. **History-shuffled control** — the exact same ranking rule trained on the exact same calibration rows after the outcome tuples have been shuffled within each calibration task. The shuffle preserves task difficulty and outcome counts while breaking the candidate-feature/outcome pairing.

The baseline and both rankers have access to the same candidate descriptors. The evidence ranker does not receive task-family identity. The only treatment difference between the two learned orderings is whether calibration history remains correctly bound to the candidate features that produced it.

## Family split and hidden holdout

Calibration and holdout use disjoint task families. Candidate feature vocabularies are shared, but family names are not inputs to the learned ranker.

After calibration evidence is sealed, the evidence and shuffled rankers are frozen. Only then does the receiver generate the holdout candidate pools. All three orderings are sealed for every holdout task **before** the receiver draws the holdout-outcome nonce and creates any holdout outcomes.

This prevents the ranking rule from seeing holdout success, gain, or failure reason before ranking.

## Primary metric

There is one primary metric:

**fraction of holdout tasks on which an acceptable improvement is found within the fixed four-evaluation budget.**

A positive result requires the evidence ranker to exceed both the baseline and the history-shuffled control by at least 0.08 on that metric. No significance claim is made from task-level pseudoreplication.

Evaluations-to-first-win are reported alongside the primary metric. A miss is preserved as `null` and consumes all four evaluations; a censored summary also reports misses as budget + 1 so tasks where nobody finds a win remain visible.

Gain, best-seen gain, and regret against the best candidate in the bounded pool are secondary diagnostics only.

## Economics

Calibration-evaluation cost, ranker CPU time, and experimental control overhead are reported separately. Downstream evaluation savings are measured as the difference in evaluations actually consumed before success or budget exhaustion.

The conservative break-even calculation charges **all calibration evaluations** to learning. If the evidence ranker saves evaluations downstream, the receipt reports the number of future tasks required to recover that learning cost at the observed mean savings rate. If it saves none, break-even is undefined.

A predictive result is therefore not silently relabeled economic. The result reports predictive standing and economic standing separately.

## What a pass means

A pass means that, in this controlled family-held-out calibration, correctly bound prior receiver evidence produced a ranking that found acceptable candidates within budget more often than both a fixed ordering and the same ranker trained on shuffled history.

That would establish a mechanism worth testing live. It would **not** establish Level 4, recursive self-improvement, causal isolation of any one receipt field, repeatability across independent runs, production value, or hostile-process isolation.

A failure is equally useful: it says there is not enough transferable predictive signal here to justify scaling this mechanism into a larger recursive trial.

## Local structural checks

```bash
python -m unittest discover -s experiments/ril-rank-001/tests -p 'test_*.py' -v
python experiments/ril-rank-001/run_ril_rank_001.py --self-check
```

The first completed primary run is terminal for RIL-RANK-001. After any holdout outcome exists, changing the family split, outcome generator, candidate generator, ranking rule, shuffle rule, budget, metric, or verdict threshold requires a new experiment ID.
