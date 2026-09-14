# AUTORESEARCH-LIVE-003 — frozen confirmed live improvement

**Status: terminal and frozen.** The preregistered terminal verdict is `CONFIRMED_LIVE_IMPROVEMENT_PROMOTED`.

LIVE-003 began from fresh receiver baseline `effe44963da4d8b81ecc9be1ba3f115ac3ef2dab` at `val_bpb = 1.123087368232`. The same self-declared Prince / Muse Spark 1.3 researcher used two of the twelve authorized research calls.

Proposal 1 (`60a4ad14c8a8bcd2cba0091d94439ca079c465c5`) changed the MLP to a parameter-matched SwiGLU form. Receiver measurement was `1.127078192171`, so Airlock rejected it and restored the accepted baseline.

Proposal 2 (`20a0df6cc98778ffb53957d6b4fafccda3a4973e`) changed one training setting: `TOTAL_BATCH_SIZE` from `2**19` to `2**18`. Discovery measured `1.049689693833` and returned ACCEPT. Under the frozen protocol that was only an apparent win; accepted state did not move. Airlock then ran the exact untouched candidate again. Confirmation measured `1.049345578535`, returned ACCEPT, and the confirmation receipt authorized promotion of that exact commit.

All 15 protected files matched before and after every receiver measurement. The run used two researcher calls and four receiver measurements, observed 3009.316 seconds of pod wall time, and recorded estimated GPU spend of $1.337474 at $1.60/hour, all within preregistered ceilings.

## Preserved evidence

The off-pod archive is not vendored into this repository. Its SHA256 is:

`a66e354a5d46e1549484498593e01b2a7d43674c0985b739d4cc2df513cd05f1`

The archive contains the complete receiver evidence directory, all three decision receipts, the final result, protected snapshot, a complete git bundle, the promoted `train.py`, and the exact baseline-to-A patch.

The git bundle SHA256 is:

`46f688458039507d753ed8ef2421727ad10703dd52d116b80d17c6bd6893370e`

The uploaded archive was independently inspected before this freeze. `git bundle verify` reports complete history. The bundle materializes exact A, exact parent `effe44963da4d8b81ecc9be1ba3f115ac3ef2dab`, and a one-file `train.py` delta. The archived promoted `train.py` and patch match the bundle byte-for-byte by SHA256.

The receiver verification key itself was not included in the archive, so this repository does **not** claim an independent post-hoc re-verification of the receipt HMACs. It preserves the signed receipt bytes and their hashes. During the live run, promotion required the receiver gate to verify the confirmation receipt before advancing `openline/accepted`.

## Claim boundary

This result earns one confirmed live improvement A under the frozen **same-fixed-seed** protocol. It does not establish independent-seed statistical replication, repeatability across independent runs, statistical ML superiority, cumulative optimization, recursive improvement, or hostile-process isolation.

The next earned experiment may inherit exact A and search for a separately confirmed B. A → inherited A → confirmed B would establish **cumulative governed optimization**. A stronger recursive-improvement claim requires more: the inherited accepted change must improve the process that generates subsequent improvements, rather than merely improve the training code being optimized.
