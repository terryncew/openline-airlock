# RIL-API-ISOLATION-001 — API-request statelessness qualification for canary isolation

## Lineage

- **RIL-ISOLATION-002** qualified the observable Temporary Chat boundary manually:
  two paired trials, exact same-chat canary recall, fresh chats returned `UNKNOWN`,
  exposure chats absent from Recent and Gemini Apps Activity.
- **RIL-RELAY-001/002** tried to automate that browser transport. Both failed at
  egress before any primary contact (`ERR_EMPTY_RESPONSE` at gemini.google.com/app).
  Frozen 2026-09-14: available VM failed preflight, no primary contact, no
  credentials touched, no retry. The relay was operator convenience, and the
  anomaly program was told not to wait for it.
- **This experiment** moves the isolation question to the API level. The researcher
  substrate is no longer a browser session — it is a stateless HTTP request.
  GPT (OpenAI Chat Completions API) is the researcher. Every invocation is a fresh
  independent request; the receiver constructs the complete prompt each time; no
  thread id, previous-response id, conversation continuation, or stored message
  history is ever supplied or used.
- **If it passes**, `ANOMALY-003` runs the matched anomaly-first vs ordinary
  search on this substrate: GPT for both arms, a brand-new API request every round,
  the only memory being the arm-local history the receiver deliberately puts into
  that request. Treatment can never leak into control through a shared
  conversation substrate, because there is no shared conversation substrate.
- **Then Claude** becomes the second run: same frozen protocol, different provider.
  If anomaly-first wins on GPT and repeats on Claude, that is much stronger than
  mixing providers inside one comparison.

## What PASS earns

Two paired canary trials showed no observable cross-request canary inheritance
across fresh independent Chat Completions requests under the frozen protocol:
each exposure request repeated its canary exactly, each independent blind request
returned exactly `UNKNOWN`.

## What PASS does NOT earn

- provider-internal statelessness (we observe the boundary; we do not see inside)
- absence of hidden cross-request state at the provider
- anything about the Responses/Assistants APIs (explicitly excluded)
- repeatability beyond this qualification
- recursive improvement, anomaly-first advantage, or production safety

## Model pinning

Pinned model id: **`gpt-6-astra`**.

Verified 2026-09-14 against the official catalog,
[Models — OpenAI API](https://platform.openai.com/docs/models): "GPT-6 Astra ...
Model ID `gpt-6-astra`", described as "our flagship model for complex reasoning
and coding". GPT-6 Astra was released 2026-09-03/04, succeeding the GPT-5.6
family (Sol/Terra/Luna).

The driver re-verifies at run start: `GET /v1/models` must list the pinned id
before any canary is generated, and the receipt records the verbatim listed id,
the model identifier from each response, and a hash of the full model list.
If the pinned id is not listed, the run fails closed — it never substitutes
another model.

## Credential

The OpenAI API key lives in the Secure Vault as connector `custom.openai`
(bearer_header placement, `api.openai.com` allowlist). The driver obtains it
only as a Sentinel-managed surrogate through the bundled `dynamic_credentials`
helper; the surrogate is replaced with the real key on approved egress and this
process never sees key material. The key is never pasted into chat, never
written to files, env vars, or the repo. If the connector holds no credential,
the driver fails closed with `FAIL_CREDENTIAL_UNAVAILABLE` before any API call.

## Cost

Four Chat Completions calls plus one `GET /v1/models`, temperature 0,
max_tokens 100. Expected spend is a fraction of a cent; the frozen ceiling is
$0.50.
