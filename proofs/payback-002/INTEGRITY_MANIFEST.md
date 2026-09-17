# PAYBACK-002 — Integrity Manifest

Pinned identifiers for the frozen terminal evidence. All values recomputed
2026-09-16 from the git objects; nothing reconstructed.

## Commits

- Preregistration (frozen before contact):
  `1e5c5a1fd698b0f9eb94d3adfcb25ea53e766173`
- Base (PAYBACK-001 failure evidence, preserved):
  `acdc0b4ccb637aaa2782996018c370628b6b44a0`
- Terminal evidence (run directory as the dead process left it):
  `b295e12ad3cbf3ffc89d128c5f7fa2285fcffbc4`

## Run directory

`study/payback-002/runs/payback002/` at the evidence commit —
tree `df902c71e0ae7cba9af2906237a5e65c7672705e`:

| file | sha256 |
|---|---|
| RESULTS_NOTE.md (operator record) | dbd645bcafc70c2db66f3635814d0365146a1f2872b0de94f7c26ab974fefff7 |
| candidate_method.txt (accepted successor bytes) | 6f28b65a89b283460ad04e4b6c13defa08c5906c280dc381fef7e2d507b2d6d4 |
| MANIFEST.json | 4124dcd957199ed558ac5e65846c77809cc253655a7c7ee1c7ec72d7ba0edcad |
| promotion.json | d2dbcddd1d3c1fe1caf0ee5deca48a11b3491a242746351a9a444aa672162736 |

- ledger.jsonl: 746 lines (370 provider invocations recorded)
- TASKS.jsonl: 171 rows (operating tasks 0–170)
- raw/: 370 files (provider request/response bytes)

## Frozen figures (from the operator record)

- Preflight: 1 post, ok, 12/18 tokens, settled $0.000408
- D = $0.372212 settled / $0.00 retained
- Promotion: 12/12 vs 12/12, 0 regressions, ratio 1.0175 → ACCEPTED
- Operating: 171/450 tasks, 341 calls settled, 0 regressions
- A(0) = −$0.371712; A(171) = −$0.381312; no break-even; no A(450)
- Settled $4.861228 of $18.00; retained $0.22 unresolved (2 × $0.11)
- Terminal verdict: INCOMPLETE
