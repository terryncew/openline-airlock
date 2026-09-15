"""RSI-006-Q5 durable observation adapter (pre-contact).

Integrates three frozen pieces without modifying any of them:

- Q3's ``ContactGate`` (``contact.py``): the receiver-owned,
  race-safe, exactly-once first-contact authorization. Imported
  read-only; its O_CREAT|O_EXCL arbitration is preserved verbatim.
- Q4's ``ScientificTransaction`` (``stransaction.py``): the durable
  transaction journal. Used read-only as a library; never edited.
- The Q5 execution ledger (``execution_ledger.py``): prepared /
  started / spawn_failed / completion records around the real
  observation path, owned by the receiver.

Coordinator model (matches Q3: one coordinator dispatching concurrent
child observations):

- ONE coordinator process owns the live ``ScientificTransaction``
  instance for its whole lifetime.
- Worker threads may race at actual process-start / contact (the
  gate); they return execution/contact evidence to the coordinator.
- Workers NEVER mutate the Q4 journal. The coordinator serializes all
  journal mutations (contact journaling, commits, adoptions) through
  its single live instance, in its own thread.
- ``ScientificTransaction.open()`` is a crash/resume primitive: it
  appends a durable ``restart`` entry. The coordinator therefore calls
  it at most once per process lifetime (on startup, when resuming an
  existing journal), and never again during ordinary operation --
  calling it repeatedly under contention would mint false restart
  provenance even though the journal is intact.

Execution order for one observation (worker thread):

1. classify via the ledger: committed -> skip; uncertain -> fail
   closed; recoverable -> return evidence for adoption; fresh or
   retry_allowed -> continue;
2. ``ledger.record_prepared`` (atomic), BEFORE the spawn is attempted;
3. ``spawn(exec_nonce)``; on ``OSError`` (no child created):
   ``ledger.record_spawn_failed`` (atomic) and return -- zero contact,
   zero execution, a genuine first attempt remains allowed;
4. on success, immediately -- from Q3's post-``Popen`` position, after
   the child provably exists: ``ledger.record_started`` (atomic), then
   the contact boundary ``gate.note_process_started`` arbitrates the
   race (the winner is recorded for journaling by the coordinator);
5. wait for the subprocess; on timeout kill it and fail closed;
6. build canonical outcome bytes; ``ledger.write_outcome`` then
   ``ledger.record_completion`` (both atomic);
7. return the evidence to the coordinator. After the workers join,
   the coordinator reconciles the already-durable ContactGate marker
   into Q4 exactly once per chunk -- BEFORE any observation evidence
   from the chunk is committed or adopted, so the durable provenance
   always reads authorization-before-observation -- and only then
   commits, or adopts a recoverable orphan, in its serialized section.

Crash windows and their resume semantics:

- die after ``prepared`` but before a durable ``started`` record
  (including: died between the real spawn and the ``started`` write) ->
  prepared without definitive ``spawn_failed`` -> ``UncertainExecution``
  on resume: fail closed, never rerun. Absence of a ``started`` record
  is NOT proof the child never existed.
- die after ``started`` but before completion evidence ->
  ``UncertainExecution``: fail closed, never rerun;
- die after completion evidence but before the coordinator journals ->
  started + verified completion -> ``adopt_orphan_observation``: the
  exact first result, zero second execution;
- die after the gate win but before the journal contact entry ->
  ``reconcile_contact`` re-journals the winner's marker on next start,
  on the successor's single opened instance: exactly one contact event,
  never two, and exactly one ``restart`` entry for the real resume.

The inter-process lock (``fcntl.flock``) is a coordinator-exclusion
lock: the coordinator holds it for its whole lifetime. Acquisition is
non-blocking -- a second coordinator process started while one is
alive fails closed with ``CoordinatorExclusionError`` before it can
open or mutate the Q4 journal, write any ledger record, or touch
contact state (a blocking wait would hang instead of failing closed,
and the waiter would eventually mint a restart entry for a non-crash).
Worker threads of the one coordinator share the underlying file
description and never block on it, so the contact race across worker
threads stays genuine: the gate's atomic create -- not the lock --
decides the single winner. The OS releases the lock on real process
death, at which point a successor acquires it and resumes via a single
``open()``.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import execution_ledger as ledger
from execution_ledger import UncertainExecution  # noqa: F401  (public)

OUTCOME_SCHEMA = "airlock.rsi-006-q5.observation-outcome.v1"
LAUNCH_SCHEMA = "airlock.rsi-006-q5.observation-launch.v1"

#: Subprocess wait ceiling for fixture observations (seconds).
WAIT_TIMEOUT_S = 60.0


class CoordinatorExclusionError(Exception):
    """A second coordinator process tried to take an already-held journal.

    Raised at lock acquisition -- before the Q4 journal is opened or
    mutated, before any ledger record is written, and before any
    contact state is touched. The caller must fail closed.
    """


@contextmanager
def interprocess_lock(work_dir: Path):
    """Coordinator-exclusion lock: one coordinator per work directory.

    Acquisition is NON-BLOCKING: a second coordinator process that
    starts while one is alive raises ``CoordinatorExclusionError``
    instead of waiting. Waiting would be wrong -- the waiter would
    eventually proceed to ``open()`` and mint a restart entry for a
    non-crash, and would hang indefinitely instead of failing closed.

    The holder keeps the lock for its whole lifetime; the OS releases
    it on real process death, at which point a successor may acquire
    it and resume via a single ``open()``.
    """
    lock_path = Path(work_dir) / "q5-coordinator.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise CoordinatorExclusionError(
            f"coordinator lock for {work_dir} is held by another "
            f"coordinator process; refusing to start ({exc})") from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


class Coordinator:
    """Owns the live ScientificTransaction; workers report evidence.

    Construct with the single transaction instance for this process
    (begun fresh, or opened exactly once when resuming). All journal
    mutations go through this instance, in this process's thread only.
    """

    def __init__(self, *, work_dir: Path, tx, gate,
                 receipt_sha256: str, code_hashes: dict):
        self._work_dir = Path(work_dir)
        self._tx = tx
        self._gate = gate
        self._receipt_sha256 = receipt_sha256
        self._code_hashes = dict(code_hashes)
        if len(receipt_sha256) != 64:
            raise ValueError("receipt_sha256 must be a sha256 hex digest")
        # Guards the transaction reads workers perform during classify
        # while the coordinator thread may be committing other
        # observations. Journal mutations never take this lock: they run
        # only on the coordinator thread, which never holds it either.
        self._read_lock = threading.Lock()

    @property
    def tx(self):
        return self._tx

    def reconcile_contact(self) -> dict | None:
        """Re-journal a won-but-unjournaled contact after a crash.

        If the gate's marker exists (authorization was consumed by a real
        subprocess start) but the transaction journal has no contact
        entry (the process died between the two), append the winner's
        marker to the journal now, on this process's single opened
        instance. Exactly-once is preserved: the journal still ends up
        with a single contact event naming the winner, and no extra
        ``restart`` entry is minted -- this is the one genuine resume,
        not contention.
        """
        if self._tx.contact_event is not None:
            return None
        winner = self._gate.read()
        if winner is None:
            return None
        return self._tx.note_contact(
            mutant_id=winner["mutant_id"], child_pid=winner["child_pid"])

    # ------------------------------------------------------------------
    # worker side: runs in a worker thread, never touches the journal
    # ------------------------------------------------------------------

    def _classify(self, observation_id: str, phase: str):
        with self._read_lock:
            return ledger.classify(
                work_dir=self._work_dir, tx=self._tx,
                observation_id=observation_id, phase=phase,
                receipt_sha256=self._receipt_sha256,
                code_hashes=self._code_hashes)

    def _worker_run(self, *, observation_id: str, phase: str, spawn,
                    argv: list, barrier=None, _crash_hook=None) -> dict:
        """Execute one observation; return evidence to the coordinator."""
        bindings = dict(receipt_sha256=self._receipt_sha256,
                        code_hashes=self._code_hashes)
        status, payload = self._classify(observation_id, phase)
        base = {"observation_id": observation_id, "phase": phase}
        if status == "committed":
            return {**base, "result": "skipped_committed",
                    "digest": payload}
        if status == "recoverable":
            return {**base, "result": "recoverable",
                    "outcome_bytes": payload["outcome_bytes"],
                    "evidence": payload["evidence"]}
        # "fresh" or "retry_allowed": this is a genuine launch attempt.
        attempt = payload["attempt"]
        ledger.record_prepared(
            work_dir=self._work_dir, txid=self._tx.txid,
            observation_id=observation_id, phase=phase, attempt=attempt,
            pid=os.getpid(), **bindings)
        if _crash_hook is not None:
            _crash_hook("after_prepared")
        if barrier is not None:
            # Rendezvous before the spawn so simultaneous child starts
            # are genuinely simultaneous. A broken rendezvous fails
            # closed: the launch set is no longer the one authorized.
            try:
                barrier.wait(timeout=60)
            except threading.BrokenBarrierError as exc:
                raise UncertainExecution(
                    f"observation {observation_id}: spawn rendezvous "
                    f"broken ({exc}); refusing to launch alone")

        exec_nonce = os.urandom(16).hex()
        start_ts = time.time()
        try:
            proc = spawn(exec_nonce)
        except OSError as exc:
            # Q3 treats a Popen failure as zero scientific contact; the
            # ledger records the proof so a genuine first attempt remains
            # allowed. Nothing was executed, nothing was authorized.
            ledger.record_spawn_failed(
                work_dir=self._work_dir, txid=self._tx.txid,
                observation_id=observation_id, phase=phase,
                attempt=attempt,
                error=f"{type(exc).__name__}: {exc}", **bindings)
            return {**base, "result": "spawn_failed", "attempt": attempt,
                    "error": f"{type(exc).__name__}: {exc}"}
        if _crash_hook is not None:
            _crash_hook("after_spawn")
        # Post-Popen position (Q3's on_process_start): the child
        # provably exists. The started record names this specific
        # physical execution via child PID + exec_nonce.
        ledger.record_started(
            work_dir=self._work_dir, txid=self._tx.txid,
            observation_id=observation_id, phase=phase, attempt=attempt,
            child_pid=proc.pid, exec_nonce=exec_nonce, **bindings)
        # Contact boundary: the OS has actually spawned the observation
        # process. Q3's gate arbitrates the race; the coordinator
        # journals the winner's contact event below. (The
        # gate-win/journal-append crash window is closed by
        # reconcile_contact on the next start.)
        gate_result = self._gate.note_process_started(
            observation_id, self._receipt_sha256, proc.pid)
        if _crash_hook is not None:
            _crash_hook("after_started")
        try:
            stdout_b, stderr_b = proc.communicate(timeout=WAIT_TIMEOUT_S)
            exit_status = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_b, stderr_b = proc.communicate()
            raise UncertainExecution(
                f"observation {observation_id}: subprocess timed out and "
                f"was killed; completion unverifiable, refusing to rerun")
        end_ts = time.time()

        outcome = {
            "schema": OUTCOME_SCHEMA,
            "observation_id": observation_id,
            "phase": phase,
            "txid": self._tx.txid,
            "exec_nonce": exec_nonce,
            "child_pid": proc.pid,
            "argv": list(argv),
            "exit_status": exit_status,
            "stdout_b64": base64.b64encode(stdout_b).decode("ascii"),
            "stderr_b64": base64.b64encode(stderr_b).decode("ascii"),
            "duration_s": round(end_ts - start_ts, 3),
            "contact_created": gate_result["created"],
        }
        outcome_bytes = (json.dumps(outcome, sort_keys=True) + "\n") \
            .encode("utf-8")
        digest = ledger.write_outcome(
            work_dir=self._work_dir, observation_id=observation_id,
            outcome_bytes=outcome_bytes)
        ledger.record_completion(
            work_dir=self._work_dir, txid=self._tx.txid,
            observation_id=observation_id, phase=phase,
            outcome_digest=digest, **bindings)
        if _crash_hook is not None:
            _crash_hook("after_completion")

        launch = {
            "schema": LAUNCH_SCHEMA,
            "observation_id": observation_id,
            "phase": phase,
            "child_pid": proc.pid,
            "argv": list(argv),
            "exit_status": exit_status,
            "duration_s": round(end_ts - start_ts, 3),
            "exec_nonce": exec_nonce,
            "stdout_b64": base64.b64encode(stdout_b).decode("ascii"),
            "stderr_b64": base64.b64encode(stderr_b).decode("ascii"),
            "contact_created": gate_result["created"],
        }
        return {**base, "result": "completed",
                "outcome_bytes": outcome_bytes, "launch": launch,
                "gate_created": gate_result["created"],
                "child_pid": proc.pid, "exec_nonce": exec_nonce}

    # ------------------------------------------------------------------
    # coordinator side: serialized journal mutations, coordinator thread
    # ------------------------------------------------------------------

    def _apply(self, evidence: dict) -> dict:
        """Journal one worker's evidence. Coordinator thread only.

        Contact is never journaled here: after the workers join,
        ``run_all`` reconciles the already-durable ContactGate marker
        into Q4 exactly once per chunk, BEFORE any observation evidence
        is applied, so the durable provenance always reads
        authorization-before-observation.
        """
        result = evidence["result"]
        obs_id, phase = evidence["observation_id"], evidence["phase"]
        if result == "completed":
            digest = self._tx.commit_observation(
                mutant_id=obs_id, phase=phase,
                canonical=evidence["outcome_bytes"],
                launch=evidence["launch"])
            return {"observation_id": obs_id, "status": "committed",
                    "digest": digest,
                    "contact_created": evidence["gate_created"],
                    "exec_nonce": evidence["exec_nonce"]}
        if result == "recoverable":
            digest = self._tx.adopt_orphan_observation(
                mutant_id=obs_id, phase=phase,
                outcome_bytes=evidence["outcome_bytes"],
                evidence=evidence["evidence"])
            return {"observation_id": obs_id, "status": "adopted",
                    "digest": digest}
        # skipped_committed / spawn_failed: nothing is journaled.
        return {"observation_id": obs_id, "status": evidence["result"],
                **{k: v for k, v in evidence.items()
                   if k in ("digest", "attempt", "error")}}

    def run_all(self, *, observations: list, spawn, argv_for,
                spawn_for=None, crash_points: dict | None = None,
                sync_spawn: bool = False,
                max_workers: int = 1) -> list:
        """Run observations through worker threads; journal serially.

        ``observations``: list of ``(observation_id, phase)``. Workers
        race at spawn/contact and return evidence; the coordinator
        applies each result to the journal in dispatch order. An
        ``UncertainExecution`` from any worker fails the run closed:
        results before it stay journaled, nothing after it is applied.

        ``spawn`` is ``spawn(exec_nonce) -> Popen``; ``spawn_for``, when
        given, is ``spawn_for(observation_id) -> spawn`` and lets the
        caller vary the spawn per observation.
        """
        crash_points = crash_points or {}
        if sync_spawn and max_workers < len(observations):
            raise ValueError(
                "sync_spawn requires max_workers >= len(observations)")
        barrier = threading.Barrier(len(observations)) if sync_spawn \
            else None

        def die():
            # Test-only crash injection: kill the whole coordinator
            # process inside a worker's crash window.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)

        def target(obs_id: str, phase: str, results: dict,
                   failures: dict):
            want = crash_points.get(obs_id)

            def hook(where: str):
                if where == want:
                    die()

            obs_spawn = spawn_for(obs_id) if spawn_for is not None \
                else spawn
            try:
                results[obs_id] = self._worker_run(
                    observation_id=obs_id, phase=phase, spawn=obs_spawn,
                    argv=argv_for(obs_id), barrier=barrier,
                    _crash_hook=hook if want else None)
            except UncertainExecution as exc:
                failures[obs_id] = ("uncertain", exc)
            except Exception as exc:  # noqa: BLE001 -- reported, not hidden
                failures[obs_id] = ("error", exc)
            finally:
                if barrier is not None:
                    # A worker that died before the rendezvous must not
                    # wedge the others at the barrier.
                    try:
                        barrier.abort()
                    except threading.BrokenBarrierError:
                        pass

        # Dispatch in chunks of max_workers: with max_workers=1 the run
        # is fully sequential (each observation's evidence is journaled
        # before the next worker starts), which the crash tests need
        # for deterministic partial progress.
        applied = []
        for i in range(0, len(observations), max_workers):
            chunk = observations[i:i + max_workers]
            results: dict = {}
            failures: dict = {}
            threads = [threading.Thread(
                target=target, args=(o, p, results, failures),
                name=f"q5-worker-{o}") for o, p in chunk]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            # Durable contact ordering: the ContactGate marker is
            # already durable -- the winning worker wrote it at real
            # process start. Journal it into Q4 BEFORE any observation
            # evidence from this chunk is applied, so the transaction
            # provenance never reads observation-before-authorization.
            # No-op when no child started. A gate winner that later
            # failed (or proved uncertain) still made contact: the
            # event is journaled before that failure is handled below.
            self.reconcile_contact()
            for obs_id, _phase in chunk:
                if obs_id in failures:
                    kind, exc = failures[obs_id]
                    if kind == "uncertain":
                        raise UncertainExecution(str(exc))
                    raise exc
                applied.append(self._apply(results[obs_id]))
        return applied
