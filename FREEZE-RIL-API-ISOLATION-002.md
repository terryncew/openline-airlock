# FREEZE — RIL-API-ISOLATION-002 (PASS)

Experiment: RIL-API-ISOLATION-002 — API-request statelessness qualification for
canary isolation (GPT). Corrected re-run of RIL-API-ISOLATION-001 under a new ID,
per the anti-rescue clause.
Date run: 2026-09-14.
Verdict: PASS_RIL_API_ISOLATION_002_STATELESS_CANARY_BOUNDARY.

## Protocol delta vs -001 (the only changes)

- No `temperature` is sent (gpt-6-astra rejects non-default values).
- `max_tokens` replaced by `max_completion_tokens: 100` (legacy parameter rejected).
- Payload allowlist: model, messages, max_completion_tokens.
- Everything else identical: pinned model, canary format, 2-pair/4-call structure,
  pre-canary models gate, fail-closed conditions.

## Result

- Pre-canary gate: `GET /v1/models` listed `gpt-6-astra` verbatim (models_list_sha256
  `71e0950afb8ae0feb80d4d71f6e3e1f52e83144ad6b10c03249b6f030b5727ef`).
- 4 Chat Completions calls, all HTTP 200, model `gpt-6-astra` in every response.
- Pair 1: exposure repeated its canary exactly; blind returned exactly `UNKNOWN`.
- Pair 2: exposure repeated its canary exactly; blind returned exactly `UNKNOWN`.
- No canary substring in any blind prompt or blind response (byte-verified).
- Per-call records in the receipt: prompt_text (all state passed into the call),
  request_sha256 (exact payload bytes), response_sha256 (raw response bytes),
  response_text, model, usage, http_status.

## Tokens and cost

- prompt_tokens: 301, completion_tokens: 133, total: 434.
- Published gpt-6-astra standard pricing (2026-09-14): $10 / 1M input tokens,
  $50 / 1M output tokens.
- Computed actual cost: 301/1e6*10 + 133/1e6*50 = $0.009660 (under one cent).
  The API does not return metered cost; this is computed from the usage the API
  did return. No cached tokens were used (cached_tokens: 0 on all calls).

## Earned claim (narrow)

"Two paired canary trials showed no observable cross-request canary inheritance
across fresh independent Chat Completions API requests under the frozen protocol:
each exposure request repeated its canary exactly, and each independent blind
request returned exactly UNKNOWN."

## Not earned

Provider-internal statelessness, absence of hidden cross-request state at the
provider, Responses/Assistants API behavior, repeatability beyond this
qualification, recursive improvement, anomaly-first advantage, production safety.

## Credential hygiene

The API key was never in chat, logs, files, or the repo. The driver used a
Sentinel surrogate via the Secure Vault connector (custom.openai, bearer_header).
The receipt records `key_material_in_receipt: false`. Nothing in this repo is the
key or derived from it.

## Receipt

`evidence/ril-api-isolation-002/RIL_API_ISOLATION_002_RECEIPT.json` in this repo
(schema `openline.ril-api-isolation-002.receipt.v1`).
Successor: ANOMALY-003 may run the matched anomaly-first vs ordinary-search
comparison on this substrate.
