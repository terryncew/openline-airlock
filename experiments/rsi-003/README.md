# RSI-003 — recursive standing propagation across two generations

**Question.** When gen1's receiver evidence is reopened, does questioned
standing propagate to gen2, which inherited from gen1's installed policy —
or does the system keep building on a questioned foundation?

**Design.** Two real generations through Nightshift with a deterministic fake
Hermes. Gen1 improves the generator policy (`src/policy.py` STEP 1→2) and is
installed at `refs/heads/rsi-003/installed-gen1`. Gen2's generator is bound
to the exact installed gen1 policy bytes (hash-verified before its
Nightshift run) and earns its own promotion at
`refs/heads/rsi-003/installed-gen2`. Then gen1's support witness is removed,
a valid receiver-signed REOPEN(gen1) is issued, and both generations are
reprojected **through the pinned projector exercised unchanged** — no
lineage input, no transitive walk, no repair.

**Predicted result.** The pinned `openline-verified-memory` projector
derives standing per generation from that generation's own records only, so
gen2 retains `inherited` standing after gen1 is questioned:

`FAIL_RSI_003_QUESTIONED_ANCESTRY_NOT_PROPAGATED`

That clean negative receipt freezes the architectural fact: the existing
projector is generation-local and cannot yet support consequence-bearing
recursive lineage. Patching it requires a new experiment ID.

## Run

```bash
python -m pip install .
python -m pip install "git+https://github.com/terryncew/openline-verified-memory.git@454c5a3b28f2b7da673f6acf0007fc1d7b6f4d8e"
python experiments/rsi-003/run_rsi_003.py --self-check   # verify prereg bindings first
python experiments/rsi-003/run_rsi_003.py --output RSI_003_RESULT.json
```

The runner self-checks before executing and refuses to run if any
preregistered binding is ambiguous. Each phase (select/install per
generation, reopen) runs in its own process; only persisted receiver
evidence crosses the boundaries.

## Verdicts

- `PASS_RSI_003_RECURSIVE_STANDING_PROPAGATION` — questioned standing
  propagated to gen2; neither generation remains established; installed
  refs byte-identical throughout.
- `FAIL_RSI_003_QUESTIONED_ANCESTRY_NOT_PROPAGATED` — gen2 keeps clean
  standing after gen1 is questioned (predicted; the finding).
- `FAIL_RSI_003_INSTALLED_REF_MUTATION` — separate invariant failure:
  any installed-ref byte mutation. REOPEN changes standing, not history.
- `INCONCLUSIVE_RSI_003_PRECONDITION_FAILURE` — the propagation question
  could not be put to the mechanism.

Preregistration: `RSI_003_PREREGISTRATION.json` (11 bindings).
Anti-rescue: after the first pushed run, nothing under the RSI-003
identifier changes — generation count, unchanged-projector rule, REOPEN
semantics, lineage binding rule, verdicts, falsifiers.
