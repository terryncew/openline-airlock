# RIL-RELAY-002 operator card

Muse owns all terminal and host-provisioning work.

1. Verify the repo and self-check.
2. On a candidate Linux host, launch Chrome with localhost CDP and run the unauthenticated `preflight` command. Do not log into Google yet.
3. If preflight FAILS, preserve its receipt and try another Muse-available candidate host. This is allowed because no Gemini trial prompt and no credential material has been used.
4. Once a host PASSes preflight, freeze that host for the primary qualification. Do not move the primary qualification to another host under this experiment ID.
5. Only then request one unavoidable human action if needed: `LOGIN_REQUIRED`. The user authenticates the browser directly. Never request, copy, export, or store password, cookies, tokens, recovery codes, or 2FA secrets.
6. Run `qualify` exactly once against the PASS preflight receipt.
7. Do not retry any failed primary qualification contact. Preserve the entire output directory and report the terminal verdict.

Commands:
- `python experiments/ril-relay-002/verify_repo.py`
- `python experiments/ril-relay-002/protected/relay_driver.py self-check`
- `python experiments/ril-relay-002/protected/relay_driver.py preflight --output /tmp/ril-relay-002`
- after PASS + direct human login if required:
  `python experiments/ril-relay-002/protected/relay_driver.py qualify --preflight /tmp/ril-relay-002/RIL_RELAY_002_EGRESS_PREFLIGHT.json --output /tmp/ril-relay-002`
