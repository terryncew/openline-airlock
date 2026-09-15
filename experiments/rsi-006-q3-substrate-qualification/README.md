# RSI-006-Q3 — Substrate Qualification (two-stage)

Successor to RSI-006-Q2, which froze
`INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE` when its single-shot
runner burned the one-run authorization on an environment defect (no
`pytest` on the host) before any mutant was generated or observed.

Q3 separates **recoverable environment engineering** from **irreversible
scientific contact**:

- **Stage 1** (`env_qualify.py --qualify-env`): repeatable until green.
  Verifies the interpreter, installs/freezes dependencies, clones and
  pins repositories, runs untouched baselines. Never generates mutants,
  never consumes the scientific authorization. When green, freezes an
  environment receipt.
- **Stage 2** (`run_rsi_006_q3.py --qualify --env-receipt PATH`):
  irreversible. Refuses to start unless the frozen receipt still matches
  the live environment exactly. The authorization is consumed only when
  the first mutant-observation process is actually started --
  mechanically: a receiver-owned contact gate fires only after
  `subprocess.Popen` returns on the mutant path, atomically, exactly
  once; receipt checks, guards, generation, executor creation, and
  failed submissions cannot consume it.

Same repositories, pins, operator set, seeds, thresholds, budgets,
fresh-nonce semantics, and scoring as Q2. `perturb.py` is byte-identical
to Q2's generator. `observe.py` keeps Q2's scoring and adds full launch
evidence (argv, interpreter, cwd, environment identity, exit status,
stdout, stderr, JUnit report, timestamps) as a sidecar to the unchanged
canonical record.

## Running

Self-check (non-executing; safe anywhere):

```
python run_rsi_006_q3.py --self-check
```

Stage 1 — environment qualification (repeatable; run until green):

```
python env_qualify.py --qualify-env --work-dir /tmp/rsi-006-q3-env
```

This clones the four pinned repositories, installs test dependencies if
needed, runs untouched baselines, and freezes
`/tmp/rsi-006-q3-env/environment-receipt.json`.

Stage 2 — scientific contact (ONLY when explicitly authorized, and only
with a frozen environment receipt):

```
python run_rsi_006_q3.py --qualify \
  --env-receipt /tmp/rsi-006-q3-env/environment-receipt.json \
  --work-dir /tmp/rsi-006-q3 --workers 2
```

The full Stage 2 run is never invoked in CI (asserted by the
`rsi-006-q3-gate.yml` workflow).

## Layout

- `RSI_006_Q3_SPEC.md` — frozen spec (authority)
- `perturb.py` — mutation generator, byte-identical to Q2
- `observe.py` — observation harness, Q2 scoring + launch observability
- `pool_config.py` — repository pool (environment facts shared by both stages)
- `receipt.py` — environment receipt freeze/verify
- `env_qualify.py` — Stage 1: repeatable environment qualification
- `run_rsi_006_q3.py` — Stage 2: irreversible scientific contact
- `contact.py` — receiver-owned contact gate: the single atomic
  authorization-consumption transition, fired only after the first
  mutant-observation subprocess actually starts
- `tests/test_rsi_006_q3_contract.py` — contract tests (frozen properties only)
- `tests/fixtures/` — tiny fixture packages for the contract tests
