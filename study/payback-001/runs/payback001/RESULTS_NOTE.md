# PAYBACK-001 — Results note (factual, frozen)

**Authorized SHA:** `225f64bd320a57bc0452281718224e42193154d7`
**Study ID:** `payback001`
**Branch:** `study/payback-001`
**Run directory:** `study/payback-001/runs/payback001/` (preserved unchanged; this note is additive)
**Terminal verdict: INCOMPLETE** — apparatus defect; no verdict earned on the payback question.

## What happened

The authorized run executed on 2026-09-16 16:25 PDT from the exact frozen SHA
(H=450, corpus SHA `f7879ba6…`, arm-order SHA `97558f01…`, all pre-contact
checks passed). It terminated in under 5 seconds.

All five invocations — preflight (`pb1-pre-00`), discovery ×3 (`pb1-d-00/01/02`),
proposal (`pb1-p`) — recorded `unresolved` with reason `transport_no_usage: `
(empty exception message). Zero provider data was obtained. Zero calls settled.

## Root cause (apparatus defect, discovered post-run from preserved code)

`study/payback-001/scripts/payback_run.py:188` instantiates the transport as:

```python
prov = worker.Provider()
```

`worker.Provider` is the **abstract base class**. Its `post()` (`study/econ-001/src/econ/worker.py:125-128`)
raises a bare `NotImplementedError` — no request bytes are ever constructed.
The live transport is `worker.RealProvider` (line 131), which the runner never
references.

Consequences, all mechanical and frozen:

1. Every `provider.post()` raised `NotImplementedError()` before dispatch.
   No request bytes existed, so the provider could not have been contacted.
   This is not a network/egress failure (contrast ECON-001-R2's sidecar
   ECONNREFUSED); it is a runner bug: the study never attempted contact.
2. The worker's `_is_infra_failure` did not classify `NotImplementedError`
   as demonstrably pre-dispatch infra failure, so no `InfrastructureHalt`
   was raised; each call was recorded `unresolved` and the runner continued.
3. The preflight gate in `paid()` checks only that `preflight()` returned a
   response object — not that it settled with usage. The preflight therefore
   did not verify the provider path, and the runner proceeded to issue 4
   scientific invocations after an unclean preflight, contrary to the
   authorization's preflight rule ("if preflight does not complete cleanly…
   issue no scientific calls afterward; stop").

## Why the verdict is INCOMPLETE, not NO_PAYBACK

The runner's mechanical output was `NO_PAYBACK` (`proposal_unresolved` →
no accepted successor → operating skipped → debt-only). That output is
preserved as-is in the ledger notes (seq 11–12) and is not altered.

It is not an earned scientific verdict. The frozen question — whether one
bounded improvement investment repays its acquisition cost over the frozen
horizon — received zero evidence: no proposal was obtained, no promotion ran,
no operating task ran. Reporting NO_PAYBACK ("the investment did not repay
within the horizon") would assert a negative economic result for a test that
was never administered. Precedent: ECON-001-R2, where a transport-broken run
was recorded as "NOT a valid confirmatory result… no verdict earned on the
economics question."

Per the frozen apparatus, infrastructure/apparatus failure preventing
completion → **INCOMPLETE**: never positive, never negative, never rescued.

## Terminal accounting (recomputed from preserved ledger evidence only)

- D (acquisition): settled **$0.000000** + retained **$0.44** (4 × $0.11:
  `pb1-d-00`, `pb1-d-01`, `pb1-d-02`, `pb1-p`, all unresolved).
- Preflight: **$0.01** retained, excluded from D (separate accounting, as preregistered).
- Total settled spend: **$0.00**. Total retained unresolved exposure: **$0.45**.
- No charge to the provider account was possible: no request bytes existed.

## Required fields

- Preflight result: **not clean** — `unresolved`, `transport_no_usage`, no usage, no provider data; provider path not verified.
- Acquisition spend D: **$0.44 retained / $0.00 settled**.
- Proposal/delta outcome: no proposal obtained (call never dispatched).
- Promotion parent/candidate results: not run. Accepted successor: none.
  Promotion cost ratio: n/a.
- Operating calls completed: **0 of 900**. Operating horizon: not run.
- Receiver-quality regressions: n/a. Break-even t: none. A(450): n/a.
- Frozen null margin ($0.26926): not applied — no horizon completed.
- Capture/apparatus limitations: as above — runner bug at
  `payback_run.py:188`; abstract-base Provider; zero provider contact;
  preflight gate insufficient (response-object check, not settled-usage check).
  Raw response directory is empty (nothing was returned to persist).
  Ledger, MANIFEST.json, RUN_STATUS.json preserved byte-identical.
- No rescue/rerun: **confirmed**. No code was repaired, no relaunch under
  study ID `payback001` was attempted, no threshold moved, no task
  substituted, no horizon extended, no evidence reconstructed. The no-rescue
  rule binds: any further attempt requires a new study identity and fresh
  authorization; that decision is not made here.

## Provenance

- Pre-contact verification (all passed): HEAD `225f64bd…`, branch
  `study/payback-001`, clean tracked tree, offline verification exit 0,
  18/18 offline tests, corpus/arm-order hashes, H=450, 225/225 CT/TC,
  NULL_MARGIN_99=$0.26926, K_MAX=1, $18.00 ceiling, 928-call inventory,
  no prior `runs/` directory, no STOP marker.
- Paid invocation: `payback_run.py --authorize-paid-contact --preflight`,
  exactly the frozen code. No edits before execution.
