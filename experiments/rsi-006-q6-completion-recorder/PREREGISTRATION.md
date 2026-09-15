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
   already adopts durable completions. F1 is corrected in §10: the
   coordinator dies after the scientific child has genuinely started
   and contact has crossed, but **before completion becomes durable**.
3. **Normal runs stay normal commits.** An uninterrupted Q6 observation
   must journal a normal `commit_observation` with the exact sealed
   launch evidence — never an `observation_adopted` merely because a
   recorder was present. Only the crash/recovery path looks like
   adoption. F5 verifies the journal provenance shape, not just the
   scientific bytes.
4. **Q6 needs its own code/environment binding.** The frozen Q5 receipt
   does not authorize new recorder code. §9 specifies the Q6 manifest,
   Q6 code hashes, and Q6 environment receipt as a thin additive layer.

### Fixup round 2 (2026-09-15)

A second review found four more contract problems, all frozen here
before implementation: (a) the Q6 coordinator was not wired into the
frozen runner — §5 now freezes a runtime dependency-injection seam
(a `qa` proxy resolving `Coordinator` to `Q6Coordinator` for the
duration of the frozen `Stage2Runner.run()`); (b) the Q6 launch
sidecar was not bound to recovery — §5 now freezes recovery-side
verification that attaches the verified exact launch to the adoption
evidence Q4 already consumes; (c) the launch sidecar was not
cryptographically sealed — §5 now freezes a Q6 recorder-seal artifact
with exact write order and digest equations; (d) F5's "byte-level
journal parity" was invalid — §10 now freezes byte-exact canonical
bytes plus semantic/structural journal parity under preregistered
normalization. Class names corrected to the frozen `Stage2Runner`
throughout.

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
- `q6_runner.py` — required but small: `Q6Stage2Runner`
  (`Stage2Runner` subclass overriding only `_spawn_for` for the
  `q6_prep` attachment) plus the Q6 entrypoint that installs the
  `qa` proxy for the duration of the frozen parent `run()`
  (target: ≤80 lines).
- `q6_receipt.py` — the Q6 code/environment binding layer per §9
  (target: ≤150 lines).
- `execution_manifest.json` — the Q6 execution manifest per §9.
- `tests/` — F1–F5 falsifier tests per §10, plus unit tests for the
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
- `build_q3_completion` / `build_q3_spawn_failure` — the existing
  canonical scientific builders from `run_rsi_006_q5.py`, resolved by
  the recorder via frozen dotted names
  (`run_rsi_006_q5.build_q3_completion`,
  `run_rsi_006_q5.build_q3_spawn_failure`) after importing the runner
  module read-only. The runner module is import-safe (`if __name__ ==
  "__main__"` guard at line 1014) and both builders are module-level
  pure functions taking explicit keyword arguments — verified, not
  assumed. If either check fails at implementation time, STOP and
  return NO-GO rather than copy a builder.
- Q4 `ScientificTransaction` — untouched; commit/adopt/journal
  semantics unchanged.

### The one structural change, precisely

In Q5, the coordinator's `_worker_run` owns: `Popen → record_started
→ ContactGate → communicate/wait → canonical build → write_outcome →
record_completion`. In Q6, the subclass's `_worker_run` keeps
`_classify` and `record_prepared` in the coordinator, then launches
the one-shot recorder subprocess with a sealed, digest-bound
configuration (§7). The recorder owns the post-spawn sequence and
nothing else. The coordinator never sees the raw child result except
through the recorder's durable artifacts.

When no scientific builder is active (generic path), the override
delegates to `super()._worker_run(...)` — exact Q5 behavior, zero
duplication. The recorder path applies only when a completion builder
is active.

### Additive seam proof (frozen)

Inspected against exact base main
`da3cc7a6ba737fd6e46e01cff6c62f501106f845`. No closure introspection,
no callable serialization, no Q5 edits, no `run_all` override.

- **Exact Q5 method constructing `spawn`:** `run_rsi_006_q5.py`,
  `Stage2Runner._spawn_for` (line 465) returns the closure at
  line 468. The closure's complete inputs are three fields of the
  runner's prep dict: `prep["argv"]`, `prep["run_dir"]`,
  `prep["env"]` — the child is `subprocess.Popen(argv, cwd=run_dir,
  env=env, stdout=PIPE, stderr=PIPE)`. Nothing else is captured.
- **Exact Q5 method constructing builder context:**
  `Stage2Runner._prepare_observation` (line 415) fills
  `self._prep[observation_id]` with `repo_name`, `mutant`,
  `baseline`, `run_dir`, `junit_path`, `python`, `argv`, `env`,
  `env_overrides`, `overlay_root`; `_builder` (line 475) delegates to
  the module-level pure function `build_q3_completion` (line 116),
  which takes all of these as explicit keyword arguments. The spawn-
  failure builder (line 485) likewise delegates to module-level
  `build_q3_spawn_failure`.
- **Exact Q5 method constructing the gate:**
  `ContactGate(self._stage2_dir / "contact_marker.json")`
  (`run_rsi_006_q5.py` line 916); the gate exposes its path via the
  `marker_path` property (`contact.py`), so the recorder needs no new
  plumbing to find it.
- **Exact data the recorder needs:** txid, observation ID, phase,
  attempt, receipt SHA, code hashes, exec_nonce, exact child `argv`,
  `run_dir` (cwd identity), `env_overrides` (only), `python`,
  `repo_name`, `mutant`, `baseline`, `junit_path`, wait timeout
  (Q3's frozen `RUN_TIMEOUT_S`, asserted `== 120` at runner import),
  canonical builder dotted name, gate marker path. The full ambient
  `env` is NOT serialized: the recorder inherits the coordinator's
  environment through `Popen` and applies the sealed `env_overrides`
  (`PYTHONDONTWRITEBYTECODE`, `PYTHONPATH`), reproducing Q5's exact
  child env without moving secrets through the config. The recorder
  must not sanitize its own environment before spawning the
  scientific child — frozen invariant.
- **Exact Q6 seam:** `Q6Stage2Runner` (a `Stage2Runner` subclass)
  overrides `_spawn_for` (5 lines): call
  `super()._spawn_for(observation_id)`, attach the prep dict as an
  attribute on the returned closure
  (`spawn.q6_prep = self._prep[observation_id]`), return it. This is
  attribute attachment, not closure introspection — the closure's
  internals are never read. The Q6 `_worker_run` override (on
  `Q6Coordinator`, not the runner) reads `getattr(spawn, "q6_prep",
  None)`; when absent it delegates to `super()._worker_run(...)`.
  Wiring the Q6 coordinator into the frozen runner is handled by the
  **Coordinator injection** seam below — `_spawn_for` alone is not
  sufficient, and this prereg does not claim otherwise. The
  canonical builder is resolved by the recorder importing
  `run_rsi_006_q5` read-only and looking up `build_q3_completion` by
  its frozen dotted name (`run_rsi_006_q5.build_q3_completion`); the
  spawn-failure builder likewise
  (`run_rsi_006_q5.build_q3_spawn_failure`), invoked by the recorder
  itself on `Popen` `OSError` with no child, no `started` record,
  and no gate call — mirroring Q5 exactly.
- **Parent methods remaining inherited untouched:**
  `Coordinator.run_all`, `Coordinator._apply`,
  `Coordinator._classify`, `Coordinator._generic_completion`,
  `Coordinator.reconcile_contact`, `interprocess_lock`; all
  `ledger.*` functions; `ContactGate`; Q4 `ScientificTransaction`;
  the runner's `_prepare_observation`, `_cleanup_prep`, `_run_phase`,
  mutant generation, and verdict machinery.

If the implementation discovers this seam is insufficient, the
prereg must NOT be quietly relaxed: either show a still-small
additive wrapper seam that changes no scientific semantics and stays
inside the §5 complexity bar, or return NO-GO.

### Sealed recorder artifacts and exact write order (frozen)

Q5 persists outcome bytes and the completion record, but the launch
sidecar exists only in coordinator memory until journal commit — and
the Q5 completion record binds only the outcome digest, not any
launch sidecar. Q6 therefore adds two small artifacts, all writes
atomic (tmp + fsync + rename + directory fsync), in this exact order:

1. exact outcome bytes (`<id>.outcome.json`, existing ledger path);
2. exact Q6 launch sidecar (`<id>.q6_launch.json`), schema
   `airlock.rsi-006-q6.launch-sidecar.v1`, containing:
   - Q6 bindings: txid, observation ID, phase, attempt, receipt SHA,
     code hashes, exec_nonce;
   - the exact frozen-Q3 `launch` record as a nested object;
   - outcome digest (SHA-256 of artifact 1);
   - recorder-config digest (SHA-256 of the §7 config bytes);
3. exact Q6 recorder seal (`<id>.q6_seal.json`), schema
   `airlock.rsi-006-q6.recorder-seal.v1`, binding at least:
   - txid, observation ID, phase, attempt, receipt SHA, code hashes;
   - exec_nonce for a real started child, or null for the canonical
     spawn-failure disposition;
   - outcome SHA-256;
   - Q6 launch-sidecar SHA-256 (over the exact bytes of artifact 2);
   - recorder-config SHA-256;
   - exact scientific child PID where applicable;
   - terminal recorder disposition, sufficient to distinguish
     normal / timeout / spawn-failure;
4. existing Q5 `record_completion` LAST (`<id>.complete.json`).

The frozen Q5 completion schema is NOT altered; frozen Q4 adoption is
NOT altered. This is additive evidence only.

The completion boundary now means: if `<id>.complete.json` exists on
a Q6 execution, then Q6 outcome + launch sidecar + Q6 seal were
already durable.

On both the live commit path and the crash-recovery path, Q6
verifies:

- Q5 completion `outcome_digest` == Q6 seal `outcome_sha256` ==
  SHA-256(exact outcome bytes);
- Q6 seal `launch_sha256` == SHA-256(exact `<id>.q6_launch.json`
  bytes);
- Q6 seal `config_sha256` == SHA-256(exact recorder-config bytes);
- all txid / observation / phase / attempt / receipt / code-hash /
  config / exec-nonce / child-PID bindings agree with the durable
  prepared + started records (for the spawn-failure disposition:
  exec_nonce null, no started record, disposition
  `spawn-failure` — verified instead).

Tamper with outcome, sidecar, seal, or any binding → fail closed.
No adoption, no replay.

### Coordinator injection (frozen)

Frozen `Stage2Runner.run()` constructs `qa.Coordinator(...)`
directly (line 917), where `qa` is `import q5_adapter as qa` (line
57). Overriding `_spawn_for` alone therefore cannot install the Q6
coordinator — the `_worker_run` override would never run. The
additive seam is runtime dependency injection, not a file edit:

- Q6 defines `Q6Coordinator(q5_adapter.Coordinator)`, overriding
  **only** `_worker_run` as specified in this section.
- Q6 defines `Q6Stage2Runner(run_rsi_006_q5.Stage2Runner)`,
  overriding **only** `_spawn_for` for the `q6_prep` attachment.
- The Q6 entrypoint wraps `super().run(...)` so that, for its
  duration only, `run_rsi_006_q5.qa` resolves `Coordinator` to
  `Q6Coordinator` while every other attribute (`interprocess_lock`,
  `_Crash`, and any future `qa.*`) delegates unchanged to the frozen
  `q5_adapter` module via `__getattr__`. The runner module uses
  exactly three `qa.*` attributes (`Coordinator` ×5,
  `interprocess_lock` ×1, `_Crash` ×1 — verified against exact base
  main), so the proxy surface is fully enumerated.
- The original module alias is restored in `finally`, even on
  exception. Q5 is never modified on disk and never left
  monkeypatched globally: after Q6 returns or raises,
  `run_rsi_006_q5.qa` is byte-identically the frozen module.
- The frozen parent `run`, `_run_phase`, `run_all`, `_apply`, and
  journal logic remain byte-identical; only the dynamic
  `qa.Coordinator` lookup resolves differently inside the Q6
  invocation.

This is preferred over mutating `q5_adapter.Coordinator` globally,
which would leak Q6 behavior into any direct frozen-Q5 invocation in
the same process.

### Recovery-side verification (frozen)

Frozen `execution_ledger.classify()` verifies prepared / started /
completion / outcome digest and returns recovery evidence containing
`ledger_prepared`, `ledger_started`, `ledger_completion`,
`outcome_digest`, and the tx/phase/receipt/code bindings — but it
knows nothing of `<id>.q6_launch.json`. Frozen Q4
`adopt_orphan_observation()` then does `launch =
evidence.get("launch", {})`. Inheriting Q5 classification unchanged
would therefore ignore the Q6 launch sidecar during crash recovery,
breaking F3 and the exact-provenance claim. Q5 `_classify` stays
untouched; Q6 adds verification around the recoverable result:

On `status == "recoverable"` inside the Q6 `_worker_run` override:

- start from the inherited `self._classify(...)` (frozen Q5);
- require the Q6 launch artifact and Q6 seal; verify the digest
  equations and all bindings from the sealed-artifacts section
  above, cross-checked against the durable prepared + started
  records (or, for the spawn-failure disposition, against the
  `spawn_failed` record with exec_nonce null);
- extract the exact frozen-Q3 launch dict nested in the verified
  sidecar;
- attach it to the adoption evidence:
  `payload["evidence"]["launch"] = verified_exact_launch`;
- return the ordinary inherited recoverable shape
  (`result: "recoverable"`, `outcome_bytes`, `evidence`).

The inherited `_apply` is untouched; it calls frozen Q4
`adopt_orphan_observation`, which persists/binds the verified launch
under the existing adopted-observation path.

If Q5 says `recoverable` but the Q6 launch/seal evidence is missing,
corrupt, misbound, or does not match the exact started execution:
FAIL CLOSED. No adoption. No replay.

For the uninterrupted path: the recorder seals the artifacts; the
live Q6 worker reads and verifies the same exact Q6 launch/seal
evidence, then returns `result: "completed"` with the verified exact
launch dict; the inherited `_apply` performs the ordinary
`commit_observation`. One recorder evidence chain supports both the
normal commit and the verified adoption — no second provenance path.

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
  (Q3's frozen RUN_TIMEOUT_S, from the sealed config)
→ if the scientific Popen raises OSError: recorder invokes the
  existing canonical spawn-failure builder itself — no child, no
  started record, no gate call — then seals outcome → launch sidecar
  → Q6 recorder seal (exec_nonce null, disposition spawn-failure) →
  Q5 completion LAST
→ recorder invokes the existing canonical scientific builder
→ recorder durably writes exact outcome
→ recorder durably writes exact Q6 launch sidecar
→ recorder durably writes the exact Q6 recorder seal
→ recorder writes the existing Q5 completion record LAST
→ recorder exits
```

Recorder environment invariant (frozen): the recorder inherits the
coordinator's ambient environment through its own `Popen` and applies
only the sealed `env_overrides` when spawning the scientific child —
reproducing Q5's exact child `Popen(argv, cwd=run_dir, env=env)`
without serializing ambient secrets. The recorder must not sanitize
or alter its inherited environment before the scientific spawn.
Before the scientific child `Popen`, the recorder reconstructs
`env = dict(os.environ); env.update(sealed_env_overrides)`, computes
the canonical digest exactly as the coordinator did, and requires it
to equal the sealed `prepared_env_sha256`. Mismatch → zero
scientific child spawn, fail closed. The recorder uses the
reconstructed and verified `env` both for the scientific child
`Popen` and when invoking the frozen `build_q3_completion` /
spawn-failure builder. This binds the exact prepared launch
environment without exposing ambient secrets; it does not claim
protection from a malicious OS/root.

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

## 7. Binding the recorder to the exact attempt (digest-bound config)

The frozen Q5 `prepared` schema contains no Q6 config hash, and Q5 is
not changed. The binding is therefore established additively:

- The coordinator constructs canonical Q6 recorder-config bytes:
  `json.dumps(config, sort_keys=True).encode("utf-8")` where the
  config binds at least: txid, observation ID, phase, attempt, receipt
  SHA, code hashes, exact child `argv`, `run_dir` (cwd identity),
  required `env_overrides` only (never the full ambient environment
  or secrets), wait timeout, canonical builder dotted name,
  serialized builder context (`repo_name`, `mutant`, `baseline`,
  `python`, `junit_path`), and the gate marker path.
- The coordinator additionally computes `prepared_env_sha256`: the
  SHA-256 over a canonical representation of the exact Q5
  `prep["env"]` mapping — `"\n".join(f"{k}={v}" for k, v in
  sorted(env.items()))` encoded UTF-8 — bound into the config. The
  mapping itself is NOT serialized into the config.
- The coordinator computes SHA-256 over those exact bytes.
- The config file is written atomically, create-once (a second write
  for the same observation+attempt fails closed).
- The recorder is launched with BOTH the config path AND the expected
  config SHA-256 passed directly in the recorder's `argv` (not read
  from any file).
- Before any scientific child `Popen`, the recorder: reads the config
  bytes, recomputes SHA-256, compares it to the expected digest from
  its launch argv, and verifies the config bindings against the
  durable prepared record (txid, observation ID, phase, attempt,
  receipt SHA, code hashes — byte-exact).
- Any mismatch — digest mismatch, binding mismatch, tampered bytes,
  replaced config file, changed child argv, changed builder context —
  makes the recorder exit **before** any scientific child spawn. Zero
  child spawn on any config failure.

This closes the "replace config after preparation" hole without
modifying Q5. Threat boundary (frozen): this binds the
receiver-owned execution against stale, replaced, or misbound
configuration inside the defined process model. It does not claim
resistance to a malicious OS or root attacker.

The scientific `started` record continues to bind the exact
scientific child PID and exec_nonce under the same attempt. The
recorder aborts without spawning if a completion record already
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
  thresholds are reused exactly (§11). No scientific contact occurs
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

### Injection hygiene tests (frozen)

Before F1–F5, and runnable without any scientific child:

- direct frozen-Q5 invocation still constructs the frozen Q5
  `Coordinator`;
- Q6 invocation constructs `Q6Coordinator`;
- after Q6 returns or raises, `run_rsi_006_q5.qa` is restored
  exactly (identity with the frozen module);
- no Q5 module/file state remains altered after a Q6 invocation;
- the frozen parent `run`, `_run_phase`, `run_all`, `_apply`, and
  journal logic are byte-identical (verified against exact base
  main).

If any hygiene test fails, the seam is not additive → NO-GO.

### F1 — COORDINATOR DIES BEFORE COMPLETION, RECORDER SURVIVES
(primary earned case)

The kill point is deterministic, not a poll race. The fixture
scientific child cooperates through a **fixture-only**
synchronization primitive (a ready-file plus a release-file); this
mechanism is absent from production code.

Required state at coordinator kill — all asserted by the test driver:

- scientific `started` durable for the exact child/exec_nonce;
- ContactGate crossed exactly once;
- **completion NOT durable** (`<id>.complete.json` absent). If
  completion is somehow already durable at kill time, F1 is invalid
  and must not count — Q5 already adopts durable completions, and
  killing then would not test the new gap.

Sequence:

1. begin transaction; coordinator writes the digest-bound recorder
   config and launches the recorder;
2. recorder verifies config digest + prepared bindings, then `Popen`s
   the fixture scientific child;
3. recorder writes `started`; calls ContactGate exactly once;
4. fixture child signals "started/ready" through the fixture sync
   file, then **blocks before completing**;
5. driver confirms: Q5 `started` record durable for the exact
   child/exec_nonce, ContactGate crossed exactly once, completion
   absent;
6. driver SIGKILLs the coordinator process (external driver, not a
   crash hook);
7. driver asserts the coordinator is dead; recorder + scientific
   child remain alive;
8. driver releases the child; the child completes;
9. the orphaned recorder writes exact outcome, then exact Q6 launch
   sidecar, then the Q6 recorder seal, then the existing Q5
   completion record LAST;
10. only AFTER the Q5 completion record exists (the LAST write in
    the sealed order), the successor starts on the same durable
    root;
11. successor opens the same transaction, classifies as recoverable,
    verifies, and adopts the exact completion;
12. zero second scientific `Popen`;
13. same txid/contact/attempt/exec_nonce; journal verifies; terminal
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
changed outcome digest; changed or mismatched launch sidecar/seal;
recorder config byte tamper; recorder config file replacement;
correct tx/observation bindings but changed child `argv`; changed
builder context; wrong expected config digest passed in recorder
argv; ambient/inherited environment drift causing a
`prepared_env_sha256` mismatch.

Expected: fail closed — zero adoption, zero rerun. Every config-
binding case (including the env-digest case) must additionally
produce **zero scientific child spawn**: the recorder exits before
`Popen`. (The ledger's existing binding checks plus the Q6
launch-sidecar/seal digest binding and the §7 config-digest check do
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
behavior with no crash. Two separate Q5 and Q6 runs cannot have
byte-identical journals, so F5 freezes a narrower target:

**Byte-exact:**
- canonical scientific observation bytes/digest identical for the
  same deterministic fixture;
- where the frozen builder produces deterministic spawn-failure
  canonical bytes, those are also identical.

**Semantic / structural:**
- same scientific child argv;
- exact prepared-environment digest parity;
- same cwd identity;
- same timeout / collection-error / kill disposition;
- contact remains after the real child `Popen` and before
  observation commit;
- uninterrupted Q6 produces ordinary `observation`, NOT
  `observation_adopted`;
- same observation ID / phase / scientific digest;
- same relevant journal event ordering;
- no added scientific decision or scoring event;
- no verdict difference.

**Explicitly normalized / ignored (expected volatile/provenance
fields only):** txid / transaction nonce; timestamps; child PID;
exec nonce; duration/timing values; receipt/code hashes that
necessarily differ because Q6 has its own bound execution surface;
the new recorder artifacts and their provenance.

No other semantic difference is allowed. The mechanism-level
criterion is therefore: "F5 canonical scientific bytes byte-exact
and journal semantic/structural parity under the preregistered
normalization" — NOT "F5 parity byte-exact".

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

## 12. Contact, qualification, and repeatability (frozen)

The corrected sequence — RSI-006 productivity cannot be authorized
until the substrate is qualified:

1. Q6 mechanism implementation (additive only, §5);
2. F1–F5 fixture mechanism tests (§10);
3. Q6 Stage 1 environment qualification → frozen Q6 environment
   receipt (§9);
4. exactly one authorized Q6 terminal substrate-qualification
   execution using the same frozen Q3 scientific workload and
   constants (§11);
5. terminal substrate verdict (§14);
6. ONLY `QUALIFIED_RSI_006_Q6_SUBSTRATE` may authorize RSI-006
   productivity — and that authorization is a separate decision, not
   granted by this preregistration.

- **First irreversible Q6 scientific contact** is therefore the first
  real (non-fixture) observation subprocess spawned during the
  authorized Q6 terminal substrate-qualification execution under the
  frozen Q6 environment receipt. It is NOT after productivity
  authorization. F1–F5 mechanism tests are not scientific contact.
- **What may be repeated pre-contact:** Stage 1 arming/qualification
  attempts (each preserving its attempt evidence byte-identical under
  the existing pre-contact evidence-preservation rules), fixture
  mechanism tests, recorder unit tests, self-checks, and receipt
  re-verification. None of these creates scientific contact. The
  static feasibility guard remains pre-contact.
- **What cannot change after first contact:** the Q6 execution
  manifest and every file it binds, the Q6 environment receipt, Q3
  pins/constants/thresholds, the scientific pool, and this
  preregistration's falsifier definitions. Any change invalidates the
  Q6 receipt exactly as manifest changes invalidate Q5's. No
  tuning, no rescue, no additional repair after contact.

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

## 14. Verdict vocabulary (frozen)

Mechanism level (F1–F5; deliberately unconfusable with scientific
verdicts):

- Per falsifier: **HOLDS** or **VIOLATED**.
- Mechanism overall: **Q6_MECHANISM_HOLDS** (F1–F5 all HOLD, no Q5
  invariant weakened, F5 canonical scientific bytes byte-exact and
  journal semantic/structural parity under the preregistered
  normalization) or **Q6_MECHANISM_VIOLATED(\<reason\>)**.
- **Q6_MECHANISM_VIOLATED → STOP.** No rescue, no reinterpretation,
  no Q7. The negative result is preserved as evidence; RSI-006
  productivity remains unauthorized.

Production stage (frozen now, used only after §12 step 4):

- Pre-contact only: **INCONCLUSIVE_RSI_006_Q6_PRECONDITION_FAILURE**
  (the static feasibility guard failed: no transaction, no contact,
  no verdict — same boundary as Q5's pre-contact report).
- Terminal scientific verdicts:
  **QUALIFIED_RSI_006_Q6_SUBSTRATE** /
  **NOT_QUALIFIED_RSI_006_Q6_SUBSTRATE**.
- If execution fails after scientific contact before a scientific
  verdict: freeze the exact descriptive execution failure (in the
  style of Q5's `FAIL_CLOSED_UNCERTAIN_EXECUTION_AFTER_CONTACT`);
  scientific verdict NOT EARNED; substrate qualification NOT EARNED;
  no rerun, no rescue; no Q7; RSI-006 productivity remains
  unauthorized.

Q6 mechanism tests never produce a scientific verdict. Bare
`Q6-PASS`/`Q6-FAIL` are retired — they risk being read later as the
substrate verdict. Never claim substrate qualification from mechanism
tests alone.

The unrepaired case keeps Q5's frozen description:
`FAIL_CLOSED_UNCERTAIN_EXECUTION_AFTER_CONTACT` — safety behavior
earned, scientific verdict not earned, substrate qualification not
earned.

---

## 15. Terminal Q6 path (frozen)

One complete path, no branches around it:

PRE-CONTACT:

- implement the additive mechanism (§5);
- run F1–F5 fixture mechanism tests (§10);
- if **Q6_MECHANISM_VIOLATED** → STOP, no Q7;
- if **Q6_MECHANISM_HOLDS** → freeze the implementation;
- run Q6 Stage 1 qualification against the final exact execution
  surface; Stage 1 may be repeated only under the existing
  pre-contact evidence-preservation rules;
- freeze the Q6 environment receipt (§9);
- the static feasibility guard remains pre-contact; its failure is
  `INCONCLUSIVE_RSI_006_Q6_PRECONDITION_FAILURE` — no transaction,
  no contact, no verdict.

CONTACT:

- exactly one authorized Q6 terminal substrate-qualification
  execution (§12 step 4);
- the first real scientific child `Popen` consumes
  authorization/contact exactly as frozen;
- no tuning, no rescue, no additional repair after this point.

TERMINAL:

- `QUALIFIED_RSI_006_Q6_SUBSTRATE` → the substrate prerequisite is
  finally earned; RSI-006 productivity may be *separately* authorized
  (this preregistration does not authorize it);
- `NOT_QUALIFIED_RSI_006_Q6_SUBSTRATE` → stop; RSI-006 productivity
  unauthorized;
- post-contact execution failure before verdict → freeze the exact
  descriptive failure; scientific verdict NOT EARNED; substrate
  qualification NOT EARNED; stop; no Q7; productivity unauthorized.

There is no additional Q6 repair after contact.

## 16. Pre-implementation checklist (must all hold before code)

1. Branch is `prereg/rsi-006-q6` at exact base main
   `da3cc7a6ba737fd6e46e01cff6c62f501106f845`; compared with exact
   base main, the branch adds exactly one preregistration file and
   modifies zero pre-existing tracked files — no Q5, Q4, Q3, or
   `proofs/` file changed (verified by diff).
2. The additive seam proof (§5) holds as written: `run_rsi_006_q5`
   import-safe, builders resolvable by dotted name, `_spawn_for`
   attribute seam sufficient, coordinator injection via the `qa`
   proxy with exact `finally` restoration and all injection hygiene
   tests green — else NO-GO.
3. The `_worker_run` override can be expressed by subclassing with the
   reuse list in §5 intact — else NO-GO.
4. The Q6 binding wrapper fits the ≤150-line target without qualifier
   redesign — else NO-GO.
5. F1–F5 procedures above are implementable against fixtures with the
   deterministic barrier and the corrected kill point (completion NOT
   durable at coordinator death) — else the falsifier, not the bar,
   is at fault: return to review.

Implementation, Q6 Stage 1, and any scientific contact each require
separate explicit authorization. This preregistration authorizes none
of them.
