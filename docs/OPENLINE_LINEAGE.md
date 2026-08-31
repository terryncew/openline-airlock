# OpenLine lineage beneath Airlock

Airlock keeps the OpenLine research vocabulary out of the normal CLI, but the implementation deliberately preserves three ideas from the existing stack.

**Receiver-owned admission.** `sieve.py` and `receipt.py` carry forward the Receipt Gate / Transaction Airlock invariant: candidate capability is evidence, not authority. The parent receiver decides whether the exact candidate commit earned admission.

Reference implementation lineage: `terryncew/openline-receipt-gate`.

**Content-addressed evidence.** Proof receipts bind the exact base commit, candidate commit, protected surface, config hash, command exits, and command-output hashes. v0.1 uses a receiver-local HMAC key so tampering is detectable without pretending the key is a cross-system identity primitive.

**Flat reverse evidence index.** `index.py` uses the minimal reverse-hash pattern established by the OpenLine Lite / openline-impact work: evidence hash -> admitted proof paths. The point is cheap future reconsideration, not a graph database.

Reference implementation lineage: `terryncew/openline-lite`.

Airlock v0.1 is intentionally a standalone implementation rather than a runtime dependency on either research repository. That keeps installation small and prevents the product interface from inheriting experimental terminology or repository layout.
