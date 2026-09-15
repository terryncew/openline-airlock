# RSI-006-Q6 Preregistration: one-shot completion recorder

**Experiment ID:** `RSI-006-Q6`
**Experiment name:** completion-recorder
**Directory:** `experiments/rsi-006-q6-completion-recorder/`
**Status:** PREREGISTERED — no code, no scientific contact, no Q5/Q4/Q3 changes
**Base main (exact):** `da3cc7a6ba737fd6e46e01cff6c62f501106f845`
**Decision:** GO, frozen 2026-09-15, with the corrections in §1

---

## 1. Decision record and corrections applied

The Q6 GO/NO-GO decision gate was: *whether changing who owns completion
capture can recover the coordinator-death-with-surviving-recorder case
cheaply enough to justify one final substrate repair.* The decision is
frozen as **GO**, with these corrections to the original decision memo,
all frozen before any implementation:

1. **Q5 is immutable; Q6 is additive.** The memo proposed editing Q5's
   `q5_adapter.py` and `run_rsi_006_q5.py`. That is withdrawn. Q5 is
   historical evidence; its code and proof surface stay untouched. Q6
   lives entirely under `experiments/rsi-006-q6-completion-recorder/`
   and reuses Q4/Q5 code read-only. If the repair cannot be expressed
   as a small additive layer over frozen Q5 without duplicating or
   redesigning major Q5 machinery, the implementer must STOP and return
   NO-GO before implementation. This is part of the Q6 boundedness test.
2. **F1's kill point was too late.** Killing the coordinator after a
   completion record is already durable does not test the new gap — Q5
   already adopts durable completions. F1 is corrected in §9: the
   coordinator dies after the scientific child has genuinely started
   and contact has crossed, but **before completion becomes durable**.
3. **Normal runs stay normal commits.** An uninterrupted Q6 observation
   must journal a normal `commit_observation` with the exact sealed
   launch evidence — never an `observation_adopted` merely because a
   recorder was present. Only the crash/recovery path looks like
   adoption. F5 verifies the journal provenance shape, not just the
   scientific bytes.
4. **Q6 needs its own code/environment binding.** The frozen Q5 receipt
   does not authorize new recorder code. §8 specifies the Q6 manifest,
   Q6 code hashes, and Q6 environment receipt as a thin additive layer.

---

## 2. Lineage and immutable dependencies

- RSI-006-Q3 froze `EXECUTION FAILURE AFTER CONTACT`: terminal, no
  rerun/rescue/reconstruction/reinterpretation.
- RSI-006-Q4 (PR #161) added the durable receiver-owned scientific
  transaction journal.
- RSI-006-Q5 (PR #165, merged 2026-09-15) integrated Q3's frozen
  scientific machinery in Q4's transaction layer with a durable
  execution ledger. Its terminal descriptive state is
  `FAIL_CLOSED_UNCERTAIN_EXECUTION_AFTER_CONTACT`: safety behavior
  earned, scientific verdict not earned, substrate qualification not
  earned. Q5 is now immutable.

Q6 imports the following files **read-only** (byte-identical to exact
base main, SHA-256 recomputed from `git show <base>:<path>`):

| file | sha256 |
|---|---|
| `experiments/rsi-006-q4-durable-transaction/stransaction.py` | `d7a54c1b4a658d7e566464d6ed5ebaf194ab868a70544c2155053a9a90797b04` |
| `experiments/rsi-006-q5-durable-substrate-qualification/execution_ledger.py` | `54faba957fadc2e4bb2d7bab587c064dc4e437f5c04e1dadb4540c1a6c74167f` |
| `experiments/rsi-006-q5-durable-substrate-qualification/q5_adapter.py` | `b425f393f192e50a22090ad4d433ff82c9949f111b3fc5551e3b5a70a796e7ff` |
| `experiments/rsi-006-q5-durable-substrate-qualification/run_rsi_006_q5.py` | `0d9063676cd983bec3a480206b8edccdb9ae1e74e7f99ecf42c92a5e75a374c1` |
| `experiments/rsi-006-q5-durable-substrate-qualification/environment_receipt.py` | `bc2a7476d7906df5bcb3d4ba4812d2ce356c37beb6dc2ca7c9103f2f423d4086` |
| `experiments/rsi-006-q5-durable-substrate-qualification/stage1/env_qualify.py` | `e0f4725bc675f34f7f38502ec81a0981ad764a2ef0335650685c9329476b8988` |
| `experiments/rsi-006-q3-substrate-qualification/contact.py` | `5b2ad96067fd7a399988f9439e091511cef56bc6cab2135eeddffb10c2030197` |
| `proofs/rsi-006-q3/environment-receipt.json` | `d89327dcceb1536d7f66c5d1257a15f9b0de3b9f4c19ef75549eadaa7515acaa` |

Any Q6 implementation must verify these hashes at build time and fail
closed on mismatch. No Q6 artifact may modify, move, or reinterpret
these files. The frozen Q5 execution manifest
(`experiments/rsi-006-q5-durable-substrate-qualification/execution_manifest.json`)
and any frozen Q5 environment receipt are never touched.

---

## 3. Frozen failure model

Q5's progress-loss window, confirmed against exact main
`da3cc7a6ba737fd6e46e01cff6c62f501106f845`:

```
prepared
→ scientific child Popen
→ started
→ ContactGate
→ communicate()
→ build canonical result in coordinator memory
→ write outcome
→ record completion
→ coordinator journal commit
```

If the coordinator dies after the child has produced its result but
before `write_outcome` / `record_completion`, the only copy of the
completed result exists in coordinator memory. Resume sees `started`
without verified completion and correctly raises `UncertainExecution`.
That behavior is correct and stays.

**Covered by Q6:** coordinator-process failure **after** a scientific
child has genuinely started, where the one-shot completion recorder
process **and** the durable root survive long enough for the recorder
to durably seal that child's exact completion.

**Not covered (out of scope, fail closed as Q5 does today):**

- recorder dies before the seal (→ `UncertainExecution`, zero replay);
- coordinator and recorder co-die;
- host loss, durable-storage loss, or external destruction of the
  process group;
- recovery requiring a supervisor, daemon, queue, broker, pool,
  distributed coordination, consensus, or cross-host recovery;
- arbitrary successor-restart timing — see §7.

New precise assumption (frozen):

> The coordinator may fail, but the recorder process and durable root
> must survive until the recorder's atomic completion seal.

---

## 4. Frozen claim

The strongest claim Q6 may earn, and no stronger:

> "Under coordinator-process failure after a scientific child has
> started, if the one-shot completion recorder and durable root
> survive long enough to seal that child's exact completion, a
> successor can recover the completed observation into the same
> transaction without a second scientific execution."

Q6 must NOT claim: general crash tolerance, host-failure recovery,
recorder-failure recovery, arbitrary restart timing, distributed
durability, progress under simultaneous failure, or substrate
qualification merely from mechanism tests.

## 5. Additive-only architecture

Q6 is a thin layer over frozen Q5. New files (all under
`experiments/rsi-006-q6-completion-recorder/`, planned — not yet
written):

- `q6_recorder.py` — the one-shot completion-recorder process
  (target: ≤200 lines).
- `q6_adapter.py` — a `Coordinator` subclass overriding **only**
  `_worker_run` to delegate the post-spawn sequence to the recorder
  (target: ≤200 lines). Everything else (`_classify`, `_apply`,
  `_generic_completion`, `reconcile_contact`, `run_all`,
  `interprocess_lock`) is inherited unchanged.
- `q6_runner.py` — only if the scientific runner needs a Q6 entry
  point; it must import `run_rsi_006_q5` read-only and change nothing
  in it. To be created only if the wrapper cannot be avoided.
- `q6_receipt.py` — the Q6 code/environment binding layer per §8
  (target: ≤150 lines).
- `execution_manifest.json` — the Q6 execution manifest per §8.
- `tests/` — F1–F5 falsifier tests per §9, plus unit tests for the
  recorder. Fixture-only; no scientific contact.

Reused read-only (never copied, never forked):

- `ledger.record_prepared / record_started / record_spawn_failed /
  write_outcome / record_completion / classify` and the atomic-write
  primitives — imported from frozen `execution_ledger.py`.
- `Coordinator._classify`, `Coordinator._apply`,
  `Coordinator._generic_completion` — inherited from frozen
  `q5_adapter.py`. `_apply` is what keeps the uninterrupted path a
  normal `commit_observation`: the Q6 worker returns
  `result: "completed"` evidence and the inherited `_apply` journals
  it exactly as Q5 does.
- `ContactGate` — imported from frozen Q3 `contact.py`, instantiated
  on the same gate path, called at the same boundary (immediately
  after the scientific child's successful `Popen`).
- `build_q3_completion` — the existing canonical scientific builder
  from `run_rsi_006_q5.py`, imported read-only and invoked inside the
  recorder. Pre-implementation check: the runner module is import-safe
  (`if __name__ == "__main__"` guard) and the builder is a module-level
  pure function; if either check fails, the implementation must STOP
  and return NO-GO rather than copy the builder.
- Q4 `ScientificTransaction` — untouched; commit/adopt/journal
  semantics unchanged.

### The one structural change, precisely

In Q5, the coordinator's `_worker_run` owns: `Popen → record_started
→ ContactGate → communicate/wait → canonical build → write_outcome →
record_completion`. In Q6, the subclass's `_worker_run` keeps
`_classify` and `record_prepared` in the coordinator, then launches
the one-shot recorder subprocess with a sealed, create-once
configuration. The recorder owns the post-spawn sequence and nothing
else. The coordinator never sees the raw child result except through
the recorder's durable artifacts.

### New durable artifact (frozen)

Q5 persists outcome bytes and the completion record, but the launch
sidecar exists only in coordinator memory until journal commit. Q6
requires the seal to carry everything either a live coordinator or a
later successor needs, so the recorder persists, in this exact order,
all atomic (tmp + fsync + rename + directory fsync):

1. exact outcome bytes (`<id>.outcome.json`, existing ledger path);
2. exact launch/result sidecar (`<id>.q6_launch.json`, new schema
   `airlock.rsi-006-q6.launch-sidecar.v1`, binding txid, observation
   ID, phase, attempt, exec_nonce, receipt SHA, code hashes, and the
   outcome digest);
3. completion record LAST (`<id>.complete.json`, existing
   `record_completion`).

The completion seal therefore means: all inputs required for either a
normal commit or a later verified recovery are already durable. The
live coordinator reads the sealed launch sidecar and passes it to the
inherited `_apply` → `commit_observation` unchanged — a normal commit
with normal journal/provenance semantics.

**Complexity stop (frozen):** if this layer cannot be expressed within
the file/line targets above without duplicating ledger, journal, or
builder logic — i.e. without forking any frozen module — the
implementer must STOP and return NO-GO before any scientific contact.
A NO-GO here is a result, not a failure to try harder.

---

## 6. Recorder responsibility (allow/deny, frozen)

The recorder owns only completion capture around one observation:

```
prepared exists
→ coordinator launches one-shot recorder
→ recorder verifies its transaction/observation bindings against the
  durable prepared record (byte-exact; fail closed on mismatch)
→ recorder launches the scientific child (exact argv from the sealed
  config — never reconstructed from guesses)
→ recorder writes started (existing ledger.record_started: exact child
  PID + exec_nonce + same attempt)
→ recorder calls ContactGate immediately after successful
  scientific-child Popen
→ recorder waits / applies the already-frozen timeout behavior
→ recorder invokes the existing canonical scientific builder
→ recorder durably writes exact outcome
→ recorder durably writes exact launch/result sidecar
→ recorder writes completion seal LAST
→ recorder exits
```

The recorder must NOT: own the Q4 journal; acquire the coordinator
lock; commit or adopt observations; generate scientific seeds; choose
mutants; alter scoring, acceptance, or contact semantics; or rerun
uncertain work. It is a one-shot durability boundary, not a daemon,
service, pool, queue, broker, database, or second machine.

Launch mechanics (frozen): the coordinator worker spawns the recorder
with `start_new_session=True` so a coordinator SIGKILL does not take
the recorder with it; orphan survival after coordinator death is the
same property Q5's crash tests already rely on empirically. The
recorder performs no coordinator-lock acquisition and no
`ScientificTransaction.open()`.

---

## 7. Binding the recorder to the exact attempt

Before launching the scientific child, the recorder verifies the
durable prepared record matches, byte-exact: txid, observation ID,
phase, attempt, receipt SHA, code hashes. The scientific `started`
record continues to bind the exact scientific child PID and
exec_nonce under the same attempt.

- The recorder configuration is immutable/create-once: written
  atomically by the coordinator before recorder launch, verified by
  the recorder before spawn, and any replacement or tampering after
  preparation fails closed (no new physical execution from a
  stale/misbound config).
- A stale or misbound recorder config must never create a new
  physical execution: on any binding mismatch the recorder exits
  without spawning.
- Do not serialize the full ambient environment or secrets. Pass or
  inherit only what is needed to recreate Q5's exact child invocation
  (argv, wait timeout, builder dotted name + serialized builder
  context).
- The recorder aborts without spawning if a completion record already
  exists for the observation+attempt (first seal wins; see F4).

---

## 8. Successor timing is part of the claim boundary (frozen)

> "Successor recovery is evaluated after recorder completion has
> either become durable or the recorder has failed to produce a seal."

There is no supervisor, queue, or liveness service coordinating
immediate restart with a still-running recorder. If the recorder never
produces a seal, existing Q5 fail-closed behavior
(`UncertainExecution`, zero replay) remains authoritative. "Wait for
the recorder" must not become a new distributed liveness protocol.

---

## 9. Q6 code and environment binding (without changing Q5)

The frozen Q5 execution manifest explicitly binds Q5's complete code
surface and states that changes invalidate its environment receipt.
The Q5 production receipt therefore never authorizes Q6 recorder code.

Q6 obtains its own binding as a thin additive layer:

- `experiments/rsi-006-q6-completion-recorder/execution_manifest.json`,
  schema `airlock.rsi-006-q6.execution-manifest.v1`. Its `code_files`
  enumerates the Q6 execution surface (the Q6 files in §5) **plus** the
  frozen Q5/Q4 files they import read-only, so their hashes are bound
  into the Q6 receipt too. It pins the frozen Q3 receipt by the same
  path and SHA-256 (`d89327dc…7515acaa`) as Q5's manifest.
- `q6_receipt.py` mints schema `airlock.rsi-006-q6.env-receipt.v1`
  (stage `q6-environment-qualification`). It reuses Q5's pure,
  read-only helpers (`sha256_file`, manifest hashing logic,
  storage-witness/boot-identity/qualifier helpers, atomic-write
  pattern) without modifying them, and adds Q6-scoped schema constants
  plus a qualifier binding over the Q6 code hashes. The frozen Q5
  receipt module, the frozen Q5 manifest, and the frozen Q5 receipt
  (if any ever exists) are never written to.
- Stage 1 machinery (`stage1/env_qualify.py`) is reused read-only
  where its manifest-path parameters accept the Q6 manifest cleanly;
  where Q5 schema constants are hardcoded, the Q6 wrapper performs its
  own constant check and then delegates to the pure helpers. No
  qualifier redesign.
- Frozen Q3 receipt, pins, pool, seeds, budgets, operators, and
  thresholds are reused exactly (§12). No scientific contact occurs
  during environment qualification.

**Complexity stop (frozen):** if establishing this binding requires a
large new qualification framework rather than the thin wrapper above
(≤150 lines), STOP and return NO-GO. Do not claim any Q5 Stage 1
authorization covers Q6 code.

---

## 10. Falsifiers F1–F5 (frozen procedures and outcomes)

F1–F5 are mechanism tests. They run against fixtures with real
`Popen`, the real ContactGate, the real ledger, and the frozen Q3
canonical builder active (the scientific path) — **zero real
repositories, zero real mutants, zero scientific contact.** A full
scientific-context claim remains out of scope for Q6.

### F1 — COORDINATOR DIES BEFORE COMPLETION, RECORDER SURVIVES
(primary earned case)

Required state at coordinator kill — all asserted by the test driver:

- scientific `started` durable for the exact child/exec_nonce;
- ContactGate crossed exactly once;
- **completion NOT durable** (`<id>.complete.json` absent). If
  completion is already durable at kill time, the test is invalid —
  Q5 already adopts durable completions, and killing then would not
  test the new gap.

Sequence:

1. begin transaction; recorder launched with sealed config;
2. recorder `Popen`s the actual scientific (fixture) child;
3. durable `started` exists for that exact child/exec_nonce;
4. ContactGate crossed exactly once;
5. assert NO durable completion exists yet;
6. kill the coordinator process (SIGKILL, external driver);
7. assert coordinator dead; recorder + scientific child remain alive;
8. child finishes; orphaned recorder writes exact outcome, then exact
   launch sidecar, then completion seal LAST;
9. only AFTER the seal exists, start the successor on the same
   durable root;
10. successor opens the same transaction, classifies as recoverable,
    verifies, and adopts the exact completion;
11. zero second scientific `Popen`;
12. same txid/contact/attempt/exec_nonce; journal verifies; terminal
    scientific canonical bytes equal the uninterrupted control run.

Expected: `adopt_orphan_observation` in the journal (crash path only),
exactly one contact event, no replay.

### F2 — RECORDER DOES NOT SEAL

- child started; coordinator dies; recorder dies / is killed before a
  durable completion seal;
- successor runs after recorder failure is established.

Expected: `UncertainExecution`, zero replay, no fabricated result, no
verdict. Q6 must not weaken Q5.

### F3 — FORGED / MISBOUND RECORDER EVIDENCE

Independently test at least: wrong txid; wrong observation ID; wrong
phase; wrong attempt; wrong receipt SHA; wrong code hashes; wrong
exec_nonce / scientific execution identity; changed outcome bytes;
changed outcome digest; changed or mismatched launch sidecar/seal.

Expected: fail closed — zero adoption, zero rerun. (The ledger's
existing binding checks plus the Q6 launch-sidecar digest binding do
this work; F3 proves it.)

### F4 — DUPLICATE / LATE SEAL

After a valid result is committed/adopted, attempt a second recorder
result for the same observation+attempt.

Expected: first seal wins — no overwrite, no second commit/adoption,
ambiguity never silently resolved. The coordinator never launches a
recorder for a non-fresh classification, and the recorder aborts
without spawning if a completion record already exists.

### F5 — UNINTERRUPTED PARITY

Run the same fixture through A. frozen Q5 behavior and B. Q6 recorder
behavior with no crash. Require:

- same scientific canonical outcome bytes;
- same timeout/kill/collection-error semantics;
- same contact position;
- same scientific child invocation;
- normal commit remains normal commit: the journal shows
  `commit_observation` with the exact sealed launch, and **no**
  `observation_adopted` entry merely because the Q6 recorder was
  present;
- no scientific scoring or verdict difference.

Only explicitly preregistered provenance differences inherent to the
new recorder role are allowed — none are preregistered at this time,
so F5 requires byte-level journal-shape parity modulo the new
`<id>.q6_launch.json` artifact's existence.

## 11. Standing rules inherited (frozen)

- **No-rescue rule:** no rerun, no rescue, no replacement mutant, no
  threshold movement, no fresh transaction. If the process dies, only
  the existing same-transaction resume/reconciliation path is allowed.
- **No tuning after contact:** seeds, budgets, operators, pins,
  thresholds, fixture parameters for F1–F5, timeouts, and builder
  selection are frozen by this preregistration. None change after
  first Q6 scientific contact.
- **Unchanged Q3 scientific constants:** seeds
  `RSI-006-Q-discovery-A` / `RSI-006-Q-discovery-B`; budgets
  more-itertools (72, 72, 10, 20), cachetools (102, 102, 20, 60),
  boltons (70, 70, 20, 60), pluggy (51, 51, 20, 60); operators
  CMP_SWAP, ARITH_SWAP, BOOL_FLIP, NUM_DELTA, LOGIC_SWAP, NOT_DROP;
  pins more-itertools `b2f3aff7633057d234ec9186c18a53f4df306d08`,
  cachetools `4500e3d04288738d25acbb4973eb3c3e1bf41db9`, boltons
  `961dcff3f42e73b245aef65e377fe82763b257bb`, pluggy
  `0a4974175aa2d873f401345b151297af2e74c851`; thresholds Q-DET 1.0,
  Q-SIG [0.05, 0.95], Q-STAB per-operator ≤0.25 / Spearman ≥0.7 / ≥3
  operators with ≥10 observations per half, Q-FRESH per-operator
  ≤0.30 / overall ≤0.15, collection-error rate <0.10, Q-INTACT
  unchanged.

---

## 12. Contact and repeatability boundaries (frozen)

- **First irreversible Q6 scientific contact** is defined as the first
  real (non-fixture) observation subprocess spawned under a frozen Q6
  environment receipt after the terminal substrate-qualification
  decision authorizes RSI-006 productivity. F1–F5 mechanism tests are
  not scientific contact.
- **What may be repeated pre-contact:** Stage 1 arming/qualification
  attempts (each preserving its attempt evidence byte-identical),
  fixture mechanism tests, recorder unit tests, self-checks, and
  receipt re-verification. None of these creates scientific contact.
- **What cannot change after first contact:** the Q6 execution
  manifest and every file it binds, the Q6 environment receipt, Q3
  pins/constants/thresholds, the scientific pool, and this
  preregistration's falsifier definitions. Any change invalidates the
  Q6 receipt exactly as manifest changes invalidate Q5's.

---

## 13. No-Q7 rule (frozen, exact language)

Q6 is the last substrate repair.

If Q6 passes, the next step is the terminal substrate-qualification
decision required to authorize RSI-006 productivity — not another
repair.

If Q6 fails because the recorder and coordinator co-die, the host
disappears, storage disappears, the process group is externally
destroyed, recovery requires a queue / supervisor / daemon,
cross-host coordination is needed, or major Q4/Q5 redesign is needed,
we STOP. Those are execution-environment limitations.

There is no Q7 durability ladder.

---

## 14. Terminal verdict vocabulary (frozen)

- Per falsifier: **HOLDS** or **VIOLATED**.
- Q6 overall: **Q6-PASS** (F1–F5 all HOLD, no Q5 invariant weakened,
  F5 parity byte-exact) or **Q6-FAIL(<reason>)**.
- **Q6-FAIL → STOP.** No rescue, no reinterpretation, no Q7. The
  negative result goes to the terminal substrate-qualification
  decision as evidence.
- Q6 mechanism tests never produce a scientific verdict. Never label
  Q6 PASS/FAIL/QUALIFIED/NOT_QUALIFIED in the scientific sense, and
  never claim substrate qualification from mechanism tests alone.
- The unrepaired case keeps Q5's frozen description:
  `FAIL_CLOSED_UNCERTAIN_EXECUTION_AFTER_CONTACT` — safety behavior
  earned, scientific verdict not earned, substrate qualification not
  earned.

---

## 15. Pre-implementation checklist (must all hold before code)

1. Branch is `prereg/rsi-006-q6` at exact base main
   `da3cc7a6ba737fd6e46e01cff6c62f501106f845`; this document is the
   only addition; no frozen file changed (verified by diff).
2. `run_rsi_006_q5` is import-safe and `build_q3_completion` is a
   module-level pure function resolvable by dotted name — else NO-GO.
3. The `_worker_run` override can be expressed by subclassing with the
   reuse list in §5 intact — else NO-GO.
4. The Q6 binding wrapper fits the ≤150-line target without qualifier
   redesign — else NO-GO.
5. F1–F5 procedures above are implementable against fixtures with the
   corrected kill point (completion NOT durable at coordinator death)
   — else the falsifier, not the bar, is at fault: return to review.

Implementation, Q6 Stage 1, and any scientific contact each require
separate explicit authorization. This preregistration authorizes none
of them.
