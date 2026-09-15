# RSI-006-Q5 freeze note: fail-closed uncertain execution after contact

Frozen 2026-09-15. Airlock HEAD `c82f0242e6556bbc8d920291f444090b526adeee`.

This is a proof-only freeze. Runtime evidence was copied and hashed; nothing
in the durable root was modified. `freeze-record.json` carries the
machine-readable bindings; `INTEGRITY_MANIFEST.md` lists every file with its
SHA-256; `verify_freeze.py` re-verifies the whole freeze.

## What happened

1. Stage 1 qualified the environment (receipt
   `d696b239d31893d9a67570a700ffdc14e335ca1fee9e159d8adff4f0c7392923`).
2. Stage 2 began transaction `2e9b38f6…06245` at 14:06:38 PDT and made
   exactly one scientific contact at 14:07:00 PDT on `more-itertools-A-0002`.
3. The original process crashed during discovery. Its last durable journal
   write was 14:47:02 PDT. 192 observations were durably committed; no
   verdict was reached.
4. A single authorized same-transaction resume (byte-identical command)
   used `open()`, appended exactly one `restart` entry, skipped all 192
   committed observations with zero re-execution, and adopted one
   independently verified orphan observation (`cachetools-A-0048`).
5. The resume then met `cachetools-A-0049`: a durable `started` record
   (child pid 34170, ts 14:47:02 PDT) with no verified durable completion.
   The execution ledger raised `UncertainExecution` and refused to rerun
   it. The process exited 1 after 13 seconds.

## The three things this freeze distinguishes

### 1. Safety behavior: EARNED

The real recovery path preserved the original authorization/transaction
lineage across a real process crash: one `tx_begin`, one contact, one
`restart`, no replay of 192 committed observations, one verified orphan
adoption with zero second physical execution, refusal to replay an
ambiguous started execution, and a continuous durable journal/hash chain
(196 entries, 0 breaks). This is the behavior the frozen Q5 specification
prescribes for exactly this crash location.

### 2. Scientific verdict: NOT EARNED

The run never reached discovery seals, confirmation, report, or terminal
verdict. No scientific verdict exists and none is claimed. The descriptive
execution outcome `FAIL_CLOSED_UNCERTAIN_EXECUTION_AFTER_CONTACT` is this
freeze record's label for the terminal state; it is explicitly NOT a
runner-produced scientific verdict, and the frozen protocol assigns no
PASS/FAIL/QUALIFIED/NOT_QUALIFIED label to this state.

### 3. Substrate qualification: NOT EARNED

Q5 did not establish the terminal substrate qualification needed to
authorize RSI-006 productivity work. Do not begin RSI-006.

Safe failure is not successful qualification.

## Why this is a result, not a malfunction to rescue

The frozen spec's resume classification is explicit: "started without
verified completion: fail closed with `UncertainExecution` -- never
rerun" (RSI_006_Q5_SPEC.md lines 78-79), and claim 15: "a crash after a
real child start but before its completion is durable fails closed on
resume (`UncertainExecution`): no rerun, no verdict" (lines 464-466).
See `evidence/spec-excerpts.md` for the verbatim language.

The runner did what the specification requires. The transaction is
stopped permanently at that boundary: no further resume, no
reconstruction of `cachetools-A-0049`, no rerun, no replacement mutant,
no new transaction, no reinterpretation as a verdict.
