# RIL-ANOMALY-003 operator card

## Status

Package rebuilt 2026-09-14 on the sealed receiver truth table. No API research
call has been made; anti-rescue has not begun. The `run` subcommand is a live
implementation behind a `--spend` gate — it is NOT a stub.

Muse executes end-to-end when authorized. Work only in `openline-airlock`.
Do not create or publish `openline-rsi`.

## Steps (when authorized)

1. `python3 protected/anomaly_driver.py self-check` — offline contract check.
   Must print `self-check: PASS`. No network, no credential.
1b. `python3 protected/anomaly_driver.py preflight` — fail-closed gate for
   primary contact: isolation receipt hash + provider-returned model lineage
   (`gpt-6-astra` x4), sealed truth/schedule hashes, exactly 192 truth
   evaluations, identical starting state for both arms, no existing primary
   receipt, frozen spend ceilings. Must print `preflight: PASS`. Offline.
2. `python3 protected/anomaly_driver.py prepare --output <DIR>` — writes all 8
   round packets + full prompt texts for inspection. No network, no API.
3. Execution phase (requires explicit user authorization AND the `--spend`
   flag): `python3 protected/anomaly_driver.py run --spend --output <DIR>`
   performs the 8 fresh independent Chat Completions calls (4 rounds x 2 arms)
   via the `custom.openai` connector (Sentinel surrogate; key material never
   printed or persisted). It validates each JSON response against the response
   contract, scores the proposed rule against the sealed truth table with the
   original LIVE-002 acceptance semantics, applies the no-regression promotion
   rule, and advances only that arm's head on PROMOTE. Anti-rescue begins with
   the first primary API request of this run; the driver re-verifies every
   frozen input before each call and refuses on drift.
4. Receipt: `<DIR>/RIL_ANOMALY_003_RECEIPT.json` records per-call model binding
   (provider-returned `model` must equal `gpt-6-astra`), usage, computed cost,
   per-round verdicts, and the formal verdict:
   - anomaly − ordinary ≥ 2 → `PASS_RIL_ANOMALY_003_EARNED_RESEARCH_RATCHET`
   - ordinary − anomaly ≥ 2 → `REVERSE_RIL_ANOMALY_003_ORDINARY_SEARCH_ADVANTAGE`
   - |diff| < 2 → `NO_OBSERVED_RIL_ANOMALY_003_ADVANTAGE`

## Hard rules

- Chat Completions only. Payload keys limited to model, messages,
  max_completion_tokens. No temperature, no threads, no previous-response IDs,
  no stored history.
- The model is `gpt-6-astra` for every call, bound from the provider-returned
  identifier in the frozen RIL-API-ISOLATION-002 receipt
  (`37b636a1d515d4b8c4b539327d8392c0859211e48d1edd7cd7c85d0a25aa27dd`).
  Do not rename or upgrade it.
- Every request carries only that arm's explicitly serialized accepted history.
  Treatment history must never enter control and vice versa.
- Budgets: $4 per arm, $8 total, $1 hard ceiling per call, inside the $104.98
  hard balance ceiling. No auto-reload, no credit purchase. Record returned
  usage and computed dollars per call and per arm at the pinned pricing
  ($10/1M input, $50/1M output).
- Anti-rescue begins at the first primary API request. After that, no changes
  to the seed failure, protocols, round count, ceilings, promotion rule,
  researcher substrate, evaluator (sealed truth table), schedule, or scoring
  under this ID. Redesign needs a new experiment ID.
- REJECT and QUARANTINE leave the head unmoved and their lessons are never
  inherited. Only a receiver-confirmed PROMOTE advances the head.
- No proxy metric may trigger promotion. The sealed truth table (192 local
  receiver evaluations, done once before primary contact) is the only
  evaluator GPT's proposals are scored against, and GPT never sees it.
