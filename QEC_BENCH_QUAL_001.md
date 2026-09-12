# QEC-BENCH-QUAL-001

Status: **FROZEN — QUALIFICATION NOT EARNED**

This experiment asked whether one pinned software QEC-decoding baseline could
produce an objective accuracy + timing surface stable enough to justify a
bounded Airlock optimization experiment.

## Frozen inputs

- Airlock base: `3ef34fb0100516e458cb362a7448c78a72da097b`
- qec-lego-bench: `9c5b5c582d3733a2e406292c838dfbca6239e710`
- baseline: `rsc(d=3,p=0.01,rounds=3)` / `mwpf`
- Python: 3.11
- frozen cross-run timing ceiling: `1.50`

Two pre-measurement harness defects were repaired without changing the
benchmark pin, baseline, sample counts, timing budgets, or acceptance gates.

The first complete push/PR pair passed the preregistered cross-run gate and is
preserved in `FROZEN_CROSS_RUN_RECEIPT.json`.

The freeze commit then triggered the same unchanged qualification workflow again.
Both new runs individually returned `QEC_BENCH_QUAL_PASS`, but the new push/PR
pair failed the already-frozen cross-run timing criterion.

## Immediate recheck

Push run `34712001537`:

- within-run verdict: `QEC_BENCH_QUAL_PASS`
- median decoder time: `0.000964777413` s/shot
- logical errors: 1126 / 20000

Pull-request run `34712003749`:

- within-run verdict: `QEC_BENCH_QUAL_PASS`
- median decoder time: `0.000624716296` s/shot
- logical errors: 1132 / 20000

Cross-run recheck:

- same circuit SHA256: PASS
- accuracy |z|: `0.129989066` <= `4.0`: PASS
- timing median ratio: `1.544344880` > `1.50`: **FAIL**

## Terminal decision

`QEC-DECODER-001` is **not earned** on this measurement surface.

The reason is narrow: GitHub-hosted runner timing is not reproducible enough
under the frozen gate. A first pair barely passed at 1.4702; the immediate
unchanged recheck crossed the limit at 1.5443. Ignoring the second pair
would select the favorable measurement after seeing it.

The useful result is therefore negative. The benchmark can produce internally
stable within-run timing and stable logical-error measurements, but this setup
does not support the cross-run timing claim required for autonomous speed
optimization.

Do not repair or widen the threshold. Do not launch agent search on this
qualification. A future QEC experiment would need a different measurement
substrate, such as a controlled dedicated runner or a benchmark design whose
primary comparison is paired/interleaved and whose qualification rule is frozen
around that architecture before candidate search begins.

The workflow is sealed by `FROZEN_TERMINAL_RECEIPT.json`: future branch or main pushes verify the terminal negative receipt and do not rerun the external benchmark. This prevents later noise from reopening or cherry-picking the result.
