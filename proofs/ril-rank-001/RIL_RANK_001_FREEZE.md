# RIL-RANK-001 — frozen result

**Verdict:** `PASS_RIL_RANK_001_HISTORY_RANKING_SIGNAL`

RIL-RANK-001 asked a deliberately smaller question after RIL-001D failed to show recursive productivity advantage: does correctly bound prior receiver evidence contain useful predictive information for ordering future candidate evaluations on unfamiliar task families?

The answer in this controlled synthetic calibration was **yes**.

Under a frozen budget of four evaluations per holdout task, the evidence-derived ordering found an acceptable improvement on **48/96 tasks (50.0%)**. The fixed baseline ordering found one on **36/96 (37.5%)** and the history-shuffled ordering on **28/96 (29.17%)**. The evidence arm therefore cleared the preregistered minimum advantage of eight percentage points against both controls: **+12.5 points vs baseline** and **+20.83 points vs shuffled history**.

The result also moved the secondary efficiency measurements in the same direction. Evidence ordering used **277 evaluations**, versus **317** for baseline and **347** for shuffled history. Among tasks where a win was found, mean evaluations to first win were **1.77**, versus **2.14** baseline and **2.68** shuffled. Mean regret was also lower for the evidence ordering.

## Why the shuffled control matters

All methods saw the same candidate pools and the same evaluation budget. The treatment difference was how prior evidence was bound into the ranking. A shuffled-history control preserved per-task outcome multisets while breaking the correct evidence association. Beating that control supports the narrow claim that **correctly bound prior evidence supplied useful predictive information under this protocol**, rather than merely showing that an arbitrary alternative ordering can beat the baseline.

This still does not isolate which failure reason, receipt field, or learned feature caused the advantage.

## Holdout boundary

Calibration and holdout task families were disjoint. Family identity was excluded from the learned rank model. The policy was sealed before holdout candidate generation, all holdout orderings were sealed before the receiver created the holdout-outcome nonce, and holdout outcomes were never returned to the ranker before scoring.

The family-level result was heterogeneous. Evidence ranking improved strongly on caching and modestly on pagination, barely changed retry, and underperformed the fixed baseline on schema migration. The aggregate pass is therefore **not** a claim of universal transfer across task families.

## Economics

The evidence ordering saved **40 downstream evaluations** versus baseline across the 96-task holdout, or about **0.417 evaluations per task**. But learning the ranker consumed **768 calibration evaluations**. Under the experiment's conservative accounting, the observed savings would require about **1,844 future tasks** to repay that calibration cost.

So the economic standing remains:

`LEARNING_COST_NOT_RECOVERED_WITHIN_HOLDOUT`

The experiment establishes predictive signal, not economic usefulness at the observed scale.

## Claim boundary

This result does **not** establish Level 4, recursive self-improvement, live-agent productivity advantage, repeatability across separately initialized runs, production value, hostile-process isolation, or causation by any particular receipt field.

The earned statement is narrower:

> In this controlled family-held-out calibration, correctly bound prior receiver evidence improved candidate ordering under a fixed evaluation budget, outperforming both a fixed baseline ordering and a shuffled-history control.

That gives the recursive program something concrete to test next. A successor may ask whether an inherited policy using this frozen ranking signal produces a real live-search productivity advantage. Both arms must still receive the same available history; only the treatment may inherit the promoted ranking policy.

## Frozen evidence

- Primary run: `34853993344`
- Primary head: `de276e3b476cc5738975158ea904e3ad04b0bb71`
- Preregistration merged to `main`: `5a569f40858ea4e9e973973d7eaf9e40a7ddcd76`
- Artifact: `RIL-RANK-001-primary-34853993344-1`
- Artifact SHA-256: `7e48a4495ade7ce1faacad4c38006e1fd73c24635fa4418c0b9005a10f232e85`
- Result JSON SHA-256: `752c862175d55346f7ab9feea6bc5a4d7683b4407e385f9a0c35c17c006e984c`
- Preregistration SHA-256: `95734688aa00fab79e893fb2a930c7e0b55985592b297ed6aac4810e2bbd86be`
