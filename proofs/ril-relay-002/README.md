# RIL-RELAY-002 terminal freeze

Formal verdict: `TERMINAL_RIL_RELAY_002_NO_QUALIFIED_HOST`.

The frozen egress-preflight contract ran cleanly (repo verified, self-check
passed, Chrome 152 over localhost CDP), but the only available execution host
failed the formal unauthenticated Gemini egress preflight: exit code 2,
`Page.goto: net::ERR_EMPTY_RESPONSE at https://gemini.google.com/app`. No host
passed preflight, so no host was frozen for the primary run. No Gemini trial
prompt was ever submitted, `RIL_RELAY_002_RESULT.json` was never created, no
primary retry occurred, and no credential material was supplied, requested, or
touched.

## Evidence note — read before citing

The original `/tmp/ril-relay-002` working evidence (host inventory, preflight
receipt JSON, screenshot, stdout/stderr logs) was lost when the VM's `/tmp`
was cleaned after the session, before this freeze was written. This freeze
does **not** pretend those raw files survived. `MUSE_TERMINAL_REPORT.txt` is
the contemporaneous terminal record reconstructed verbatim from the 2026-09-14
session log, and `RIL_RELAY_002_FREEZE.json` records the loss explicitly. The
experiment package (`experiments/ril-relay-002/`) is unchanged from the
already-committed merge at `0533da1`.

This freezes a network-path/transport failure only. It does not establish a
provider-wide Gemini failure, a defect in the Temporary Chat isolation result,
or that another host would fail.

## Why paused (user decision, 2026-09-14)

Scientific, not financial: RIL-API-ISOLATION-002 had already qualified the
observable Temporary Chat boundary manually, and RELAY-002 tested only
browser-automation transport (operator convenience). Paying for another host to
prove the courier works would not advance the anomaly-first vs ordinary-search
question. Do not provision, buy, or repurpose infrastructure for this
experiment ID without a new explicit authorization.
