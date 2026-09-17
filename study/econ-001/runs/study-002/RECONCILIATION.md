# ECON-001-R2 reconciliation — 2026-09-16

Run status: **infrastructure-incomplete. No economic verdict.**
Ordered by Terrynce 2026-09-16 13:37 PDT. The mechanical `"completed"` status in
`study.json` describes the runner loop, not the science: reps 2–3 produced zero
provider observations.

## What happened

At 11:24:43 PDT, 23 minutes into the run, the VM-local egress sidecar
(`hatch-egress-proxy`, 198.19.0.1:3128 — the proxy `urlopen` uses for
`https://api.openai.com`) began refusing TCP connections. Every subsequent
invocation failed at `connect()` with errno 111 before a single request byte
was transmitted. The frozen protocol's rule for transport failures
(record-unresolved-and-continue) then converted a local outage into 301
retained reservations. The sidecar recovered later the same day (verified
accepting connections ~13:35 PDT).

## Invocation census (all 364 reserves, each with exactly one outcome)

| class | count | dollars | disposition |
|---|---|---|---|
| settled (provider usage returned) | 62 | $1.4642 actual | stays settled |
| proven not dispatched | 301 | $33.11 | **released** (see evidence) |
| possibly dispatched | 1 | $0.11 | retained |

- Gross envelope reservations (strategy risk): **$39.9400**
- Physical provider-settled spend: **$1.4642** (against $6.72 reserved for
  those 62 calls; $5.26 of reservation headroom unspent)
- Released: **$33.11** — 301 × $0.11
- Retained ambiguous exposure: **$0.11** — `rep1_g2_C_r2-eva-conf-0038`
  (`Remote end closed connection without response`: connect succeeded, so the
  request may have been transmitted)

### Release evidence (the 301)

"Likely zero" was not accepted as a basis. Release rests on this chain,
all from existing records:

1. The ledger reason string carries urllib's `<urlopen error>` wrapper, so the
   exception was raised by `urllib.request.urlopen` — *after*
   `add_surrogate_to_request` had already obtained the authd surrogate. An
   authd-socket failure would have raised `DynamicCredentialError` (or a bare
   `OSError`) with no such wrapper.
2. The launch environment sets `https_proxy=hatch-egress-proxy:3128`, which
   urllib honors for `https://api.openai.com`; `hatch-egress-proxy` resolves
   to 198.19.0.1, the VM-local egress sidecar.
3. POSIX `ECONNREFUSED` is returned by `connect()` before any byte is
   transmitted. For an HTTPS-via-proxy request, no CONNECT, no TLS handshake,
   and no request bytes could have been sent — the provider could not have
   received these requests.
4. All 301 share the identical reason string inside one outage window
   (first failure 11:24:43, thirteen seconds after the last successful settle
   at 11:24:30).

### The 24 "missing" calls

Design maximum was 388 invocations (3 × (108 measurement + 20 acquisition-max)
+ 4 calibration). Actual reserves: 364. The 24 never issued are not lost:
rep2/rep3 G1/G2 acquisitions each short-circuited per the frozen protocol when
their proposal call returned `unresolved` (`proposal_unresolved` — no candidate
delta, so the 6 promotion calls each were skipped by design). 4 acquisitions ×
6 skipped = 24. Every issued invocation is accounted for above.

## Files

- `ledger.jsonl` — original, byte-identical (sha256
  `cc4bc0598e9bbeaf0725805e0ea00c91c2e421b920ce869371522e705cfe640b`)
- `reconciliation.json` — per-invocation classification, machine-readable
- `ledger_releases.jsonl` — 301 append-only release records (one per released
  reservation, citing this evidence)
- `reconcile_r2.py` — the script that produced this record (zero network)
- `RUN_STATUS.md` — this file
