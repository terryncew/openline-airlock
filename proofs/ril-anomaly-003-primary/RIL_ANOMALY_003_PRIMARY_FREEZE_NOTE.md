# RIL-ANOMALY-003 primary freeze note

Terminal freeze of the RIL-ANOMALY-003 primary experiment result.
No experiment code or historical evidence was changed to produce this package.

## Provenance

- Experiment: `openline.ril-anomaly-003` (sealed package entered main via PR #147)
- Main at primary run: `3e7a794461c982f15d27100b675704b9884408db`
- Preregistration: `experiments/ril-anomaly-003/RIL_ANOMALY_003_PREREGISTRATION.json`
  (sha256 `53177e7b21fca49f0634bda74046c54212302c4786cd4da0e0efd3f1899ead1a`)
- Spend authorization: $8 total ($4/arm, $1/call), human-authorized 2026-09-14
- Credential surface: Sentinel-managed `custom.openai` only; no key material in receipt
- Anti-rescue: in effect from the first primary API request. The receipt below
  is preserved exactly as the driver produced it. No rerun, no repair, no tuning
  under this experiment ID.

## Result (as recorded in the receipt)

- Formal verdict: `NO_OBSERVED_RIL_ANOMALY_003_ADVANTAGE`
- anomaly_interview: 1 promotion, 3 rejections, 0 quarantines,
  final receiver-confirmed task successes: 2, spend $0.5499
- ordinary_search: 2 promotions, 2 rejections, 0 quarantines,
  final receiver-confirmed task successes: 4, spend $0.43917
- Promotion difference (anomaly − ordinary): -1 (|diff| < 2, hence the verdict)
- Total API spend: $0.98907 (within the $8 authorization)
- All 8 primary calls returned provider model `gpt-6-astra`, HTTP 200
- Receipt: `proofs/ril-anomaly-003-primary/RIL_ANOMALY_003_RECEIPT.json`
  (sha256 `2457a112d22f28728352a2b8ae7b76986e91839fc8a3d60b98ef9eecac37435b`)

## Integrity

See `RIL_ANOMALY_003_PRIMARY_INTEGRITY_MANIFEST.json` for the full binding of
the receipt and every frozen input hash to this main commit.

This note states the recorded result only. It does not reinterpret it.
