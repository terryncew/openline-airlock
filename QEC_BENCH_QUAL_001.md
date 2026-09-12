# QEC-BENCH-QUAL-001

Status: **preregistered qualification only — no autonomous decoder search is authorized**.

Pinned Airlock base:

`3ef34fb0100516e458cb362a7448c78a72da097b`

Pinned external benchmark:

`yuewuo/qec-lego-bench@9c5b5c582d3733a2e406292c838dfbca6239e710`

## Question

Is the pinned `qec-lego-bench` software surface stable enough on one controlled GitHub-hosted CPU environment to support a later Airlock optimization experiment without mistaking benchmark noise for decoder improvement?

This experiment does **not** ask an agent to improve a decoder. It qualifies the measuring instrument first.

That distinction is necessary because the benchmark's own README labels the project "very early development and may not be ready for use," while its decoding-speed implementation explicitly warns that OS scheduling interference affects timing measurements.

## Frozen baseline

One deliberately small software-only case:

```text
code:     rsc(d=3,p=0.01,rounds=3)
decoder:  mwpf
runtime:  Python 3.11 / GitHub ubuntu-latest
```

The harness first installs the benchmark from the exact pinned commit and records the resolved Python dependency environment.

It then hashes the generated Stim circuit, discards one timing warm-up, measures five independent decoder-speed replicates, and measures four independent logical-error replicates of 5,000 shots each.

No GPU, FPGA, hardware decoder, model call, or autonomous search is involved.

## Within-run qualification gate

The timing surface qualifies only if:

```text
median absolute deviation / median <= 0.20
max replicate / min replicate       <= 1.75
```

The accuracy surface qualifies only if:

```text
pooled logical errors >= 25
max absolute replicate z-score from pooled binomial rate <= 4.0
```

A low logical-error count is `INCONCLUSIVE_ACCURACY_SIGNAL_TOO_WEAK`, not a fabricated pass.

Excess timing or logical-error variability is a benchmark-qualification failure, not evidence about Airlock or any decoder candidate.

## Cross-run gate

One green receipt is not enough to authorize `QEC-DECODER-001`.

Both the push-triggered and pull-request-triggered receipts must independently return `QEC_BENCH_QUAL_PASS`. After both exist, the final qualification freeze additionally requires:

```text
same generated circuit SHA256
push/PR timing median ratio <= 1.50
push/PR logical-error estimates compatible within |z| <= 4.0
```

Only then is this measurement surface qualified for a bounded search experiment.

## Why this comes before optimization

A later decoder search would be allowed to change implementation, scheduling, batching, windowing, or other preregistered candidate dimensions. It would not be allowed to weaken logical correctness to buy speed.

That experiment is only meaningful if the baseline instrument can first distinguish a real improvement from GitHub-runner noise and stochastic logical-error variation.

## Terminal outcomes

```text
QEC_BENCH_QUAL_PASS
INCONCLUSIVE_QEC_INSTALL
INCONCLUSIVE_QEC_RUNTIME
INCONCLUSIVE_ACCURACY_SIGNAL_TOO_WEAK
BENCHMARK_UNSTABLE_ACCURACY
BENCHMARK_UNSTABLE_TIMING
```

A valid non-PASS receipt is still useful. If the external substrate is too unstable, we freeze that result and do not launch autonomous search against it.
