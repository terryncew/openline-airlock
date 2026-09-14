# RIL-RANK-EXEC-001 — frozen result

RIL-RANK-EXEC-001 is frozen at the first primary run. It is not rerun or repaired after outcome observation.

## Result

- Verdict: `PASS_RIL_RANK_EXEC_001_EXECUTABLE_TRANSFER`
- Scientific standing: `CONTROLLED_EXECUTABLE_MICROTASK_TRANSFER`
- Level 4: **not earned**
- Live-agent advantage: **not tested**
- Primary: inherited evidence ranker 41/80 (51.25%), fixed baseline 22/80 (27.50%), history-shuffled 30/80 (37.50%)
- Advantage: +23.75 percentage points vs baseline; +13.75 points vs shuffled history
- Frozen minimum: +8 points against each control
- Downstream evaluation savings vs baseline: 58

The result supports executable transfer of the frozen ranking signal. It does not show that a live researcher benefits from that ordering, and it does not establish recursive improvement.

## Economics

The inherited ranker carries 768 calibration evaluations of learning cost. This 80-task holdout did not recover that cost. At the observed 0.725 evaluation saved per task, the projected break-even is 1,060 future tasks. That is a projection conditioned on the observed savings rate persisting, not an observed payback.

## Artifact verification

The original Actions artifact is bound by SHA-256 `7156a86b0831b23849ca0286e8f172cebbc0b27b76c2a06b7ee70a2b8730e064`. Its original `MANIFEST.sha256` is preserved byte-for-byte as `RIL_RANK_EXEC_001_ORIGINAL_MANIFEST.sha256` with SHA-256 `e6d3cb4e9b586beb84e5ae2ddef51ae5afc2736b7cab8af96a164ad1c53f9831`.

The manifest has a generation defect: it included itself while being written, so its self-entry records the empty-file SHA-256. It also records absolute runner paths. The historical manifest is not rewritten. A separate verification record confirms that all seven non-manifest payloads exactly match the hashes recorded for them in that original manifest. Therefore the defect is classified as manifest/archive hygiene with no observed effect on the seven evidence/result payload bytes.

Future runs must fix manifest generation rather than retroactively cleaning this artifact.

## Next boundary

The next experiment may test the exact frozen ranker in separately initialized matched live-agent runs. The same live researcher, same available history, same candidate pool, and same search budget go to both arms; only ordering differs. Confirmed improvements and all search costs are counted. Downstream efficiency is reported separately from total economics including the inherited 768-evaluation learning cost.

A frozen ranker helping a live researcher would earn a live transfer claim. A recursive claim remains unearned unless the ranking policy itself is generated, independently promoted, and inherited by the improvement loop.
