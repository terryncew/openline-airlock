# QEC-BENCH-QUAL-001

Status: **FROZEN — QEC_BENCH_QUAL_PASS**

This qualification gate asked whether one pinned software QEC-decoding baseline
could produce an objective accuracy + timing surface stable enough to justify a
bounded Airlock optimization experiment.

## Frozen inputs

- Airlock base: `3ef34fb0100516e458cb362a7448c78a72da097b`
- qec-lego-bench: `9c5b5c582d3733a2e406292c838dfbca6239e710`
- baseline: `rsc(d=3,p=0.01,rounds=3)` / `mwpf`
- Python: 3.11
- circuit SHA256: `156938c69ea77a0053ce60d953a75718fe72eddfb652794b5b2249143203bee2`

Two pre-measurement setup defects were frozen before this terminal run:
an undeclared `IPython` import dependency and a direct-call adapter mismatch.
Neither changed the external benchmark commit, baseline, shot counts, timing
budgets, or scientific acceptance thresholds.

## Terminal receipts

Push run `34711749033`:

- verdict: `QEC_BENCH_QUAL_PASS`
- logical errors: 1143 / 20000 shots (0.057150)
- median decoder time: 0.000603041117 s/shot
- within-run timing MAD/median: 0.054831
- timing max/min: 1.496394

Pull-request run `34711750375`:

- verdict: `QEC_BENCH_QUAL_PASS`
- logical errors: 1179 / 20000 shots (0.058950)
- median decoder time: 0.000886603444 s/shot
- within-run timing MAD/median: 0.091751
- timing max/min: 1.297977

## Cross-run gate

- same generated circuit: PASS
- timing median ratio: `1.470220554` <= `1.50`: PASS
- accuracy |z| between runs: `0.769763772` <= `4.0`: PASS

Terminal qualification:

`BENCHMARK_QUALIFIED_FOR_BOUNDED_PAIRED_OPTIMIZATION`

The timing result is usable but not generous: independent GitHub-hosted runs
differed by roughly 47% in median decoder time. Therefore `QEC-DECODER-001`
must compare candidate and baseline in paired/interleaved measurements inside
the same run. It must not claim a small speedup by comparing independent CI
runs.

## Earned scope

We earned permission to run one bounded software-only optimization experiment
against this exact external baseline with frozen correctness constraints.

We did **not** earn a hardware-latency claim, a production-decoder claim,
cross-hardware reproducibility, or any claim about solving quantum scaling.
