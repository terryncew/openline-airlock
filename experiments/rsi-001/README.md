# RSI-001 — earned inheritance

RSI-001 asks one narrow question: **can an improving system inherit only what receiver evidence shows it actually earned?**

The experiment runs a deterministic fake Hermes executable through the real Airlock Nightshift path. Nightshift may vary one ordinary source file; the generator executable and harness are frozen. A unique signed generation selection earns only `candidate`. The selection process then ends before receiver installation.

A separate process reconstructs the state from disk, installs the exact selected commit into an isolated receiver-owned Git ref, observes that ref, and signs an `airlock.improvement.promotion.v1` receipt. Only then may the pinned `openline-verified-memory` projector derive `inherited`. A validly signed wrong-commit promotion is the negative control and must fail.

Finally, the fixture deliberately removes a support witness. A later receiver-signed `REOPEN` must change memory standing to `questioned`, remove it from the next generation's established-memory set, and leave the installed Git ref untouched.

Pinned inputs:

- Airlock main inspected for this experiment: `74f24d6a094053b7304b2660c6c8a8b47710fa18`
- Verified Memory: `454c5a3b28f2b7da673f6acf0007fc1d7b6f4d8e`

Run from the repository root after installing the pinned dependency:

```bash
python -m pip install .
python -m pip install "git+https://github.com/terryncew/openline-verified-memory.git@454c5a3b28f2b7da673f6acf0007fc1d7b6f4d8e"
python experiments/rsi-001/run_rsi_001.py --output /tmp/RSI_001_RESULT.json
```

Passing verdict: `PASS_RSI_001_EARNED_INHERITANCE`.

## Claim boundary

This is not a sandbox or hostile-process-isolation proof. It does not use paid live Hermes. The installation target is an isolated synthetic Git ref, not production deployment. The support-loss arm is a controlled missing-witness falsifier, not a claim that Airlock can detect arbitrary real-world evidence loss. RSI-001 does not allow the generator to rewrite how search works; that remains RSI-002.
