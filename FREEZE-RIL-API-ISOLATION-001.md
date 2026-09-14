# FREEZE — RIL-API-ISOLATION-001 (terminal, protocol failure)

Experiment: RIL-API-ISOLATION-001 — API-request statelessness qualification for
canary isolation (GPT).
Date frozen: 2026-09-14.
Verdict: PROTOCOL_FAILURE_UNCLASSIFIED — frozen terminal. No retry under this ID.

## What happened, exactly as it happened

1. Package built from the frozen 7-point spec (fresh Chat Completions request per
   invocation; no threads, previous-response IDs, or stored history; receiver-built
   prompts; paired canary trials; full hash/usage receipts; fail closed).
2. Model pinned: `gpt-6-astra`, verified listed by the pre-canary
   `GET /v1/models` gate (models_list_sha256
   `71e0950afb8ae0feb80d4d71f6e3e1f52e83144ad6b10c03249b6f030b5727ef`).
3. First primary Chat Completions call returned HTTP 400. Zero trial calls
   completed.
4. Diagnostic verification the same day (exact API error bodies):
   - `"Unsupported value: 'temperature' does not support 0 with this model. Only
     the default (1) value is supported."` (code `unsupported_value`, param
     `temperature`)
   - `"Unsupported parameter: 'max_tokens' is not supported with this model. Use
     'max_completion_tokens' instead."` (code `unsupported_parameter`, param
     `max_tokens`)
   The frozen protocol pinned `temperature: 0` and `max_tokens: 100`; the pinned
   model rejects both. The protocol was unexecutable as written.

## Why it was not patched in place

The preregistration's anti-rescue clause: "After the first primary API call under
RIL-API-ISOLATION-001, do not change the pinned model id, prompts, temperature,
max_tokens, trial count, pass rule, payload allowlist, or fail-closed conditions.
Redesign requires a new experiment ID." The first primary call had been made, so
the fix went to RIL-API-ISOLATION-002 instead. This package is preserved
unchanged, failure included.

## Receipt

`evidence/ril-api-isolation-001/RIL_API_ISOLATION_001_RECEIPT.json` in this repo
(schema `openline.ril-api-isolation-001.receipt.v1`): verdict
`PROTOCOL_FAILURE_UNCLASSIFIED`, `failure_detail: "chat completions -> HTTP 400"`,
model-selection record, zero completed calls, `key_material_in_receipt: false`.
