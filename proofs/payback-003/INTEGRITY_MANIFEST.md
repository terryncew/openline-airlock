# PAYBACK-003 — integrity manifest (terminal freeze)

Base: `study/payback-003` at terminal evidence commit
`73f011a09828eebae7e6330f5594c99d3064cfa3`.
This branch adds only this directory (`proofs/payback-003/`); the run
evidence is byte-identical to the base.

Run: `study/payback-003/runs/payback003/`
SHA-256 (files as committed):

- ledger.jsonl:      e005054a6c566966c2c452e95405642944d2a88f09bbc15d90a8410ef0e5664d
- TASKS.jsonl:       14bd06a6376ed7863a126ec64fed9f01fa1ca36b79c18b2ef983d93bd7498a80
- promotion.json:    103a71202c9ad0e83e6eaae45f3f86acd81100a06754706c63f8111ca165048
- candidate_method.txt: 6f28b65a89b283460ad04e4b6c13defa08c5906c280dc381fef7e2d507b2d6d4
- console.out:       e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
- console.err:       e28c6755aef2c544aeb67c407b7f6cd9c6a25668e70984ac3a027185976f89d1
- SUPERVISION.json:  0be744987055512e61da8b8d7576057f80f560b5cafc0e1e646a2ce423e21509
- HEARTBEAT.json:    0711c357c0e51ef30ec111141e04fe438def096b3c98499043cfc9a8406bdc55
- MANIFEST.json:     5769187b8f0536a9d225365ea4d8dd150446863239eb4763a015c3261def992a
- raw/ (311 files, preflight + discovery + proposal + promotion + 282 operating):
  combined sha256 of per-file digests: ba87abd99d56f38b

Verification (recompute from the checkout and compare):

    cd study/payback-003/runs/payback003
    sha256sum ledger.jsonl TASKS.jsonl promotion.json candidate_method.txt \
      console.out console.err SUPERVISION.json HEARTBEAT.json MANIFEST.json
    sha256sum raw/* | sha256sum

Frozen formulas applied read-only to the above:
`payback_acct.compute("study/payback-003/runs/payback003/ledger.jsonl",
tasks_path="study/payback-003/runs/payback003/TASKS.jsonl")`
→ D=0.353276, H_completed=141, A_H=-0.348196, breakeven_t=None,
verdict=INCOMPLETE (141 < 450).
