# RSI-004 — Lineage-Aware Inheritance (Airlock experiment package)

**Status: UNRUN. The primary sequence is encoded but not executed. Default
invocation runs only the self-check. Do not pass `--execute-primary` without
Terrynce's explicit authorization.**

RSI-004 is the lineage-aware successor to RSI-003. RSI-003 (frozen,
`FAIL_RSI_003_QUESTIONED_ANCESTRY_NOT_PROPAGATED`) proved the pinned
projector was generation-local: questioning gen1's evidence did not propagate
to gen2. RSI-004 asks whether the repaired projector — which takes explicit
single-required-parent lineage records — propagates a valid REOPEN(gen1)
down the inheritance chain (gen1 questioned, gen2 questioned through gen1,
gen3 questioned through gen2) while an unrelated root (rootU) stays inherited
and a gen4 admission probe is denied.

RSI-004 proves **only** single-required-parent lineage propagation. Arbitrary
multi-parent dependency DAGs are outside this experiment's claim. RSI-004
does not earn the final RSI claim: a later test still needs an inherited
method mutation to beat its unchanged parent on fresh verified results per
dollar.

## Frozen pins

| Binding | Value |
|---|---|
| Airlock base (main) | `db9fb27aa154a240eed16c1ac7bf99401011f198` |
| Verified Memory (pinned) | `36e3d0e0dab6a121abc1c14accbaa7310b5c2186` |
| Verified Memory `evidence.py` SHA-256 | `ba02bc78c999120b31ea68fcb4f4fd2d12967c705e380204d0ee093b1d874ec9` |
| Preregistration SHA-256 | `5750248e5236c506270fd5506bd695f62468dbc3114305cc2284e40d7a544d9c` |

The preregistration (`RSI_004_PREREGISTRATION.json`) is copied byte-for-byte
from the frozen design file and must not be regenerated or rewritten.

## The encoded primary sequence (not invoked)

1. Establish unrelated rootU (its own bonus policy).
2. Establish gen1 under the base policy.
3. Run gen2 from gen1's exact installed policy; earn and install it at
   `refs/airlock/rsi/gen2`.
4. Run gen3 from gen2's exact installed policy; earn and install it at
   `refs/airlock/rsi/gen3`.
5. Mint receiver-signed ROOT/REQUIRED lineage records from the actual
   promotion receipts and actual installed-policy bytes.
6. Verify rootU/gen1/gen2/gen3 all inherited before REOPEN; freeze every
   historical receipt hash and installed ref/policy byte hash.
7. Issue a valid receiver-signed `REOPEN(gen1)` (a forged REOPEN is rejected
   as a negative control).
8. Terminate the projection process; reproject persisted evidence in a fresh
   process (the restart boundary).
9. Require gen1 questioned locally, gen2 questioned through gen1, gen3
   questioned through gen2, rootU inherited.
10. Compute the gen4-through-gen3 admission probe. **gen4 is never executed:
    there is no gen4 selection phase, install ref, or Nightshift path.**
11. Require all historical receipts and installed refs/policies byte-identical.
12. Emit exactly one formal verdict and one cause code.

Formal verdicts: `PASS_RSI_004_LINEAGE_AWARE_INHERITANCE`,
`FAIL_RSI_004_REQUIRED_ANCESTRY_NOT_ENFORCED`,
`INCONCLUSIVE_RSI_004_PRECONDITION_FAILURE`. All diagnostics travel through
`cause_code` only.

PASS only if the complete contract holds and gen4 is denied. Scientific FAIL
only if the experiment is otherwise valid but questioned ancestry fails to
prevent inheritance (gen2/gen3 staying inherited, or gen4 admitted). Harness
and integrity failures are INCONCLUSIVE with the precise cause code, except
where the frozen verdict precedence maps immutable-history/determinism
failures to FAIL.

## Gates

- Default: `python run_rsi_004.py` → self-check only. Zero Nightshift
  generations, zero candidate executions, zero REOPEN mutations, zero primary
  contact.
- `--self-check` → same, explicit.
- `--execute-primary` → the future authorized run. **Do not pass without
  explicit authorization.**
- Anti-rescue begins at the first actual primary Nightshift contact: the
  runner writes `.rsi-004-primary-contact` immediately before it, and the
  self-check refuses to run if that marker exists.

## Layout

- `RSI_004_PREREGISTRATION.json` — frozen preregistration (do not regenerate).
- `run_rsi_004.py` — runner: real Nightshift + receiver-evidence machinery,
  gated, encoded-not-invoked primary.
- `tests/test_rsi_004_contract.py` — contract tests: gating, verdict
  precedence, receipt bindings, zero-contact proof.
- `../../.github/workflows/rsi-004-gate.yml` — CI: self-check + tests only.
  Contains no primary execution command.

## Authorized future command (do not run without approval)

```
python run_rsi_004.py --execute-primary --output result.json
```

Running it writes `.rsi-004-primary-contact` and executes the full primary
sequence. Until then, this package is a non-executing build: CI runs only
the self-check and the contract tests, and asserts zero primary contact.
