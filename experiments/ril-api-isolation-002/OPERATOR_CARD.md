# RIL-API-ISOLATION-002 operator card

Muse executes this experiment end-to-end. No user login is needed.

## 1. Credential check (no key material, ever)

Confirm the `custom.openai` connector holds a credential. The check is the
driver itself: it fails closed with `FAIL_CREDENTIAL_UNAVAILABLE` before any
API call if the Secure Vault has nothing to give. Do not ask Terrynce for the
key in chat, and never print, log, or store key material or surrogates.

If the connector is not set up yet, stop here and report
`CREDENTIAL_UNAVAILABLE` — setting it up is a user step
(`credentials.request_api_access`), not an operator workaround.

## 2. Self-check (offline)

```
python3 experiments/ril-api-isolation-002/protected/api_driver.py self-check
```

Must print `SELF_CHECK_PASS`. No network, no credential.

## 3. Qualify (exactly once per receipt)

```
python3 experiments/ril-api-isolation-002/protected/api_driver.py qualify \
  --output /tmp/ril-api-isolation-002
```

- The driver verifies the pinned model id via `GET /v1/models` before
  generating any canary.
- Two paired trials, four Chat Completions calls, one fresh independent
  request each. Exit 0 on PASS, exit 2 otherwise.
- Do not retry a failed primary run under this experiment ID.

## 4. Preserve and report

Keep the entire output directory, including
`RIL_API_ISOLATION_002_RECEIPT.json` (schema
`openline.ril-api-isolation-002.receipt.v1`). Report the verdict verbatim.

## Hard rules

- Chat Completions only. Never Responses, never Assistants, never threads.
- Payload keys are limited to model, messages, max_completion_tokens.
  Anything else fails closed before sending. No temperature is sent.
- The blind prompt must never contain the canary; the driver byte-scans the
  serialized blind payload before sending.
- After the first primary API call, the anti-rescue clause freezes the pinned
  model id, prompts, sampling parameters, trial count, pass rule, payload allowlist,
  and fail-closed conditions. Redesign needs a new experiment ID.
