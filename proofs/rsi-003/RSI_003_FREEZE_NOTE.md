# RSI-003 freeze note

Terminal freeze of the RSI-003 experiment result.
No experiment code or historical evidence was changed to produce this package.

## Question

When gen1's receiver evidence is reopened, does questioned standing propagate
to gen2, which inherited from gen1's installed policy — or does the system
keep building on a questioned foundation?

## Provenance

- Experiment: `openline.rsi-003` (implementation entered main via PR #149)
- Main at merge: `a4dc96fc0766cf8e88d69bce90718a46080b0309`
- Airlock base main pinned in the experiment: `d4da44a1abbabc35672d9a39f2e6c75f5adfdf49`
- Preregistration: `experiments/rsi-003/RSI_003_PREREGISTRATION.json`
  (sha256 `e2dacf20b6c0b7a22c56fae84be31151a68057079d1188a26aecb7d595a2a145`)
- Pushed-run receipt: `proofs/rsi-003/RSI_003_RECEIPT.json`
  (sha256 `81fae997106c825e3d5ed38f1c20a507eb7961bee50025577b3e4af12ae963ae`)
- Projector: `terryncew/openline-verified-memory@454c5a3b28f2b7da673f6acf0007fc1d7b6f4d8e`
  (`evidence.py` sha256 `1eae4f6c1b33f218a27dfcfca0a98b6d1bb6ead85be539e07501b988bfb18e71`),
  exercised unchanged — no lineage input, no transitive walk, no repair
- Credential surface: deterministic fixture Hermes through the real Nightshift
  path; no paid live-Hermes claim, no key material in receipt
- Anti-rescue: in effect from the first pushed RSI-003 run. The receipt below
  is preserved exactly as the pushed CI run produced it. No rerun, no repair,
  no tuning, no lineage handling under this experiment ID.

## Result (as recorded in the receipt)

- Formal verdict: `FAIL_RSI_003_QUESTIONED_ANCESTRY_NOT_PROPAGATED`
- Pre-REOPEN: both generations `inherited`; established set holds gen1 and gen2
- Valid receiver-signed REOPEN(gen1) after gen1's support witness went missing
- Post-reprojection: gen1 `questioned`, gen2 `inherited`; established set holds
  only gen2 — the questioned standing did not propagate through the inherited
  ancestry
- Gen3 admission probe: `ADMIT` (recorded, not executed)
- Installed refs byte-identical across install, pre-REOPEN, post-REOPEN, final
- Forged REOPEN rejected; wrong-commit installs rejected for both generations
- Zero lineage records passed to either projector invocation

## Integrity

See `RSI_003_INTEGRITY_MANIFEST.json` for the full binding of the receipt and
every frozen input hash to this main commit.

This note states the recorded result only. It does not reinterpret it, and it
does not repair the projector. The finding frozen here: recursive inheritance
exists, but the current verified-memory projector does not propagate
questioned standing through inherited ancestry. The successor repair is
designed under a new experiment ID.
