"""RSI-006-Q5 receiver-owned durable execution ledger (pre-contact).

The ledger sits *around* the real observation path and answers one
question on resume: for a given observation ID, did the work stay
reserved, did it provably cross the process-start boundary, and if so,
did it verifiably complete?

The pre-spawn ``start`` record of the first Q5 draft conflated reserved
work with work that actually crossed the process-start boundary. Q3
correctly treats a ``Popen`` failure as zero scientific contact, so Q5
must preserve that distinction. The execution state is therefore:

    prepared -> started | spawn_failed

- ``record_prepared`` -- atomically persisted BEFORE the spawn is
  attempted. Reservation only: it proves nothing about whether a child
  process was ever created.
- ``record_started`` -- atomically persisted ONLY from Q3's existing
  post-``Popen`` callback, after the child process actually exists. It
  binds the child PID and the exec_nonce, i.e. this specific physical
  execution.
- ``record_spawn_failed`` -- atomically persisted when ``Popen`` raises
  and no child was created. Proof of zero execution: in the generic
  path a genuine first attempt remains allowed afterwards; in the
  scientific path the spawn failure is Q3's completed observation
  (``launch_spawn_failed``), persisted with its canonical outcome and
  completion and committed normally.
- ``write_outcome`` -- the canonical outcome bytes, atomically persisted
  after the subprocess completes. This is the ledger's independent copy;
  the transaction journal keeps its own.
- ``record_completion`` -- atomically persisted only after the outcome
  bytes are durable. Binds the outcome digest.
- ``commit``/``adopt`` into the ScientificTransaction happens only after
  ``record_completion``.

Resume classification (``classify``):

- already in the transaction journal -> ``committed``: skip, never
  re-execute;
- no prepared record -> ``fresh``: the work may run (attempt 1);
- prepared + a matching definitive ``spawn_failed`` (same attempt) ->
  generic path: ``retry_allowed`` -- no child was provably created, so
  a genuine first attempt remains allowed. Scientific path:
  ``spawn_failed`` + verified completion -> ``recoverable`` (adopt the
  exact first result); ``spawn_failed`` without verified completion ->
  ``UncertainExecution`` (the spawn failure is already Q3's scored
  observation; it is never retried);
- started + verified completion -> ``recoverable``: adopt the exact
  first result via ``ScientificTransaction.adopt_orphan_observation``;
- started without verified completion -> ``UncertainExecution``: fail
  closed, never rerun;
- prepared without a definitive ``spawn_failed`` -> ``UncertainExecution``:
  fail closed. Absence of a ``started`` record is NOT proof that the
  child never existed: the coordinator may have died between the real
  spawn and the durable ``started`` write.

The ledger is receiver-owned: only the adapter (the receiver side)
writes it. The worker subprocess never touches it. All writes are
atomic (tmp + fsync + rename + directory fsync), so a crash can only
leave a record fully present or fully absent -- never torn.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

LEDGER_DIRNAME = "execution_ledger"
PREPARED_SCHEMA = "airlock.rsi-006-q5.execution-prepared.v1"
STARTED_SCHEMA = "airlock.rsi-006-q5.execution-started.v1"
SPAWN_FAILED_SCHEMA = "airlock.rsi-006-q5.spawn-failed.v1"
COMPLETION_SCHEMA = "airlock.rsi-006-q5.execution-completion.v1"
ADOPT_EVIDENCE_SCHEMA = "airlock.rsi-006-q5.adopted-execution.v1"

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class UncertainExecution(Exception):
    """Raised when an observation's execution state cannot be verified.

    Fail closed: the observation must not be rerun and the run must not
    continue past it. A rerun after an uncertain first execution would be
    a second physical execution, not a retry.
    """


def _check_id(observation_id: str) -> str:
    if not isinstance(observation_id, str) \
            or _ID_RE.fullmatch(observation_id) is None:
        raise ValueError(f"unsafe observation id: {observation_id!r}")
    return observation_id


def ledger_dir(work_dir: Path) -> Path:
    return Path(work_dir) / "artifacts" / LEDGER_DIRNAME


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write bytes: tmp + fsync + rename + directory fsync."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _atomic_write_json(path: Path, record: dict) -> None:
    blob = (json.dumps(record, indent=1, sort_keys=True) + "\n") \
        .encode("utf-8")
    _atomic_write_bytes(path, blob)


def _prepared_path(work_dir: Path, observation_id: str) -> Path:
    return ledger_dir(work_dir) / f"{_check_id(observation_id)}.prepared.json"


def _started_path(work_dir: Path, observation_id: str) -> Path:
    return ledger_dir(work_dir) / f"{_check_id(observation_id)}.started.json"


def _spawn_failed_path(work_dir: Path, observation_id: str) -> Path:
    return ledger_dir(work_dir) / f"{_check_id(observation_id)}.spawn_failed.json"


def _outcome_path(work_dir: Path, observation_id: str) -> Path:
    return ledger_dir(work_dir) / f"{_check_id(observation_id)}.outcome.json"


def _completion_path(work_dir: Path, observation_id: str) -> Path:
    return ledger_dir(work_dir) / f"{_check_id(observation_id)}.complete.json"


def _read_record(path: Path) -> dict:
    try:
        record = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise UncertainExecution(
            f"unreadable ledger record {path.name}: {exc}") from exc
    if not isinstance(record, dict):
        raise UncertainExecution(
            f"ledger record {path.name} is not a JSON object")
    return record


def _bindings(*, txid: str, observation_id: str, phase: str,
              receipt_sha256: str, code_hashes: dict) -> dict:
    return {
        "txid": txid,
        "observation_id": observation_id,
        "phase": phase,
        "receipt_sha256": receipt_sha256,
        "code_hashes": dict(code_hashes),
    }


def _check_bindings(record: dict, *, path: Path, **bindings) -> None:
    for key, want in bindings.items():
        if record.get(key) != want:
            raise UncertainExecution(
                f"ledger record {path.name} binding mismatch on {key}: "
                f"record is not bound to this transaction/phase/receipt")


def record_prepared(*, work_dir: Path, txid: str, observation_id: str,
                    phase: str, attempt: int, receipt_sha256: str,
                    code_hashes: dict, pid: int) -> dict:
    """Persist the prepared record, atomically, BEFORE attempting spawn.

    Reservation only: it proves the observation was reserved for launch,
    not that a child process was ever created. ``attempt`` counts launch
    attempts so a ``spawn_failed`` record can be paired with the prepared
    record it answers.
    """
    _check_id(observation_id)
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive int")
    record = {
        "schema": PREPARED_SCHEMA,
        "attempt": attempt,
        "pid": pid,
        "ts": time.time(),
        **_bindings(txid=txid, observation_id=observation_id, phase=phase,
                    receipt_sha256=receipt_sha256, code_hashes=code_hashes),
    }
    _atomic_write_json(_prepared_path(work_dir, observation_id), record)
    return record


def record_started(*, work_dir: Path, txid: str, observation_id: str,
                   phase: str, attempt: int, child_pid: int,
                   exec_nonce: str, receipt_sha256: str,
                   code_hashes: dict) -> dict:
    """Persist the started record, atomically, AFTER the child exists.

    Must be called only from Q3's post-``Popen`` callback, i.e. after
    ``spawn`` has returned a live child process. It binds the child PID
    and the exec_nonce, naming this specific physical execution.
    """
    _check_id(observation_id)
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive int")
    if not isinstance(child_pid, int) or child_pid <= 0:
        raise ValueError("child_pid must be a positive int")
    if not isinstance(exec_nonce, str) or not exec_nonce:
        raise ValueError("exec_nonce must be a non-empty string")
    record = {
        "schema": STARTED_SCHEMA,
        "attempt": attempt,
        "child_pid": child_pid,
        "exec_nonce": exec_nonce,
        "ts": time.time(),
        **_bindings(txid=txid, observation_id=observation_id, phase=phase,
                    receipt_sha256=receipt_sha256, code_hashes=code_hashes),
    }
    _atomic_write_json(_started_path(work_dir, observation_id), record)
    return record


def record_spawn_failed(*, work_dir: Path, txid: str, observation_id: str,
                        phase: str, attempt: int, error: str,
                        receipt_sha256: str, code_hashes: dict) -> dict:
    """Persist the spawn-failed record, atomically.

    Must be called only when ``Popen`` raised and no child was created.
    Proof of zero execution: a genuine first attempt remains allowed.
    """
    _check_id(observation_id)
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive int")
    record = {
        "schema": SPAWN_FAILED_SCHEMA,
        "attempt": attempt,
        "error": str(error),
        "ts": time.time(),
        **_bindings(txid=txid, observation_id=observation_id, phase=phase,
                    receipt_sha256=receipt_sha256, code_hashes=code_hashes),
    }
    _atomic_write_json(_spawn_failed_path(work_dir, observation_id), record)
    return record


def write_outcome(*, work_dir: Path, observation_id: str,
                  outcome_bytes: bytes) -> str:
    """Persist the canonical outcome bytes, atomically. Returns digest."""
    _check_id(observation_id)
    if not isinstance(outcome_bytes, (bytes, bytearray)) \
            or not outcome_bytes:
        raise ValueError("outcome_bytes must be non-empty bytes")
    _atomic_write_bytes(_outcome_path(work_dir, observation_id),
                        bytes(outcome_bytes))
    return hashlib.sha256(bytes(outcome_bytes)).hexdigest()


def record_completion(*, work_dir: Path, txid: str, observation_id: str,
                      phase: str, outcome_digest: str,
                      receipt_sha256: str, code_hashes: dict) -> dict:
    """Persist the completion record, atomically, after outcome bytes.

    Must only be called once ``write_outcome`` has returned: the digest
    bound here must name bytes already durable on disk.
    """
    _check_id(observation_id)
    if not isinstance(outcome_digest, str) or len(outcome_digest) != 64:
        raise ValueError("outcome_digest must be a sha256 hex digest")
    record = {
        "schema": COMPLETION_SCHEMA,
        "outcome_digest": outcome_digest,
        "ts": time.time(),
        **_bindings(txid=txid, observation_id=observation_id, phase=phase,
                    receipt_sha256=receipt_sha256, code_hashes=code_hashes),
    }
    _atomic_write_json(_completion_path(work_dir, observation_id), record)
    return record


def _check_record(path: Path, schema: str, **bindings) -> dict:
    record = _read_record(path)
    if record.get("schema") != schema:
        raise UncertainExecution(
            f"ledger record {path.name} has wrong schema "
            f"(want {schema}, got {record.get('schema')!r})")
    _check_bindings(record, path=path, **bindings)
    return record


def classify(*, work_dir: Path, tx, observation_id: str, phase: str,
             receipt_sha256: str, code_hashes: dict,
             scientific: bool = False):
    """Classify one observation for resume.

    Returns one of:

    - ``("committed", digest)`` -- already in the transaction journal:
      skip, never re-execute;
    - ``("fresh", {"attempt": 1})`` -- no prepared record: may run;
    - ``("retry_allowed", {"attempt": n})`` -- prepared, and a matching
      definitive ``spawn_failed`` for the same attempt: no child was
      created, so a genuine first attempt remains allowed. This is the
      generic (non-scientific) path only;
    - ``("recoverable", {"outcome_bytes": bytes, "evidence": dict})`` --
      started with verified completion, or (scientific path) a
      ``spawn_failed`` with verified completion: adopt the exact first
      result.

    Raises ``UncertainExecution`` when the state cannot be verified --
    fail closed, never rerun. In particular:

    - started without verified completion -> fail closed;
    - prepared without a definitive ``spawn_failed`` -> fail closed,
      because absence of a ``started`` record is not proof that the
      child never existed;
    - scientific path: ``spawn_failed`` without verified completion ->
      fail closed. The spawn failure is already Q3's scored
      observation (``launch_spawn_failed``); it is never retried.
    """
    _check_id(observation_id)
    bindings = _bindings(txid=tx.txid, observation_id=observation_id,
                         phase=phase, receipt_sha256=receipt_sha256,
                         code_hashes=code_hashes)
    if observation_id in tx.observations:
        return ("committed", tx.observations[observation_id])

    prepared_path = _prepared_path(work_dir, observation_id)
    if not prepared_path.exists():
        return ("fresh", {"attempt": 1})
    prepared = _check_record(prepared_path, PREPARED_SCHEMA, **bindings)

    started_path = _started_path(work_dir, observation_id)
    if started_path.exists():
        started = _check_record(started_path, STARTED_SCHEMA, **bindings)
        completion_path = _completion_path(work_dir, observation_id)
        if not completion_path.exists():
            # Started, but no verified completion: the child may have run,
            # may still be running, or may have died mid-flight. Rerunning
            # risks a second physical execution. Fail closed.
            raise UncertainExecution(
                f"observation {observation_id}: started record present "
                f"(child pid {started.get('child_pid')}) without verified "
                f"completion; refusing to rerun")
        completion = _check_record(completion_path, COMPLETION_SCHEMA,
                                   **bindings)
        outcome_path = _outcome_path(work_dir, observation_id)
        if not outcome_path.exists():
            raise UncertainExecution(
                f"observation {observation_id}: completion record present "
                f"but outcome bytes missing")
        outcome_bytes = outcome_path.read_bytes()
        digest = hashlib.sha256(outcome_bytes).hexdigest()
        if digest != completion["outcome_digest"]:
            raise UncertainExecution(
                f"observation {observation_id}: outcome bytes do not match "
                f"the completion digest")
        evidence = {
            "schema": ADOPT_EVIDENCE_SCHEMA,
            "txid": tx.txid,
            "observation_id": observation_id,
            "phase": phase,
            "receipt_sha256": receipt_sha256,
            "code_hashes": dict(code_hashes),
            "outcome_digest": digest,
            "ledger_prepared": prepared,
            "ledger_started": started,
            "ledger_completion": completion,
        }
        return ("recoverable", {"outcome_bytes": outcome_bytes,
                                "evidence": evidence})

    # Prepared but never provably started. The only safe retry is one
    # where the same attempt ended in a definitive spawn failure --
    # proof that no child was created.
    failed_path = _spawn_failed_path(work_dir, observation_id)
    if failed_path.exists():
        failed = _check_record(failed_path, SPAWN_FAILED_SCHEMA, **bindings)
        if failed.get("attempt") == prepared.get("attempt"):
            if scientific:
                # Scientific path: the spawn failure IS Q3's completed
                # observation (launch_spawn_failed), not a retryable
                # launch miss. With a verified completion it is
                # adoptable exactly like a started one; without a
                # verified completion the Q3-scored outcome was never
                # durably formed, and retrying would re-launch what Q3
                # already scored -- fail closed.
                completion_path = _completion_path(work_dir,
                                                   observation_id)
                if not completion_path.exists():
                    raise UncertainExecution(
                        f"observation {observation_id}: scientific spawn "
                        f"failure without verified completion; refusing "
                        f"to retry a Q3-scored observation")
                completion = _check_record(completion_path,
                                           COMPLETION_SCHEMA, **bindings)
                outcome_path = _outcome_path(work_dir, observation_id)
                if not outcome_path.exists():
                    raise UncertainExecution(
                        f"observation {observation_id}: spawn-failure "
                        f"completion present but outcome bytes missing")
                outcome_bytes = outcome_path.read_bytes()
                digest = hashlib.sha256(outcome_bytes).hexdigest()
                if digest != completion["outcome_digest"]:
                    raise UncertainExecution(
                        f"observation {observation_id}: spawn-failure "
                        f"outcome bytes do not match the completion "
                        f"digest")
                evidence = {
                    "schema": ADOPT_EVIDENCE_SCHEMA,
                    "txid": tx.txid,
                    "observation_id": observation_id,
                    "phase": phase,
                    "receipt_sha256": receipt_sha256,
                    "code_hashes": dict(code_hashes),
                    "outcome_digest": digest,
                    "ledger_prepared": prepared,
                    "ledger_spawn_failed": failed,
                    "ledger_completion": completion,
                }
                return ("recoverable", {"outcome_bytes": outcome_bytes,
                                        "evidence": evidence})
            return ("retry_allowed",
                    {"attempt": prepared["attempt"] + 1})
    # Either no spawn_failed record, or it answers an older attempt: the
    # latest attempt may have crossed the spawn boundary before the
    # coordinator died. Fail closed.
    raise UncertainExecution(
        f"observation {observation_id}: prepared record present without a "
        f"definitive spawn_failed for attempt {prepared.get('attempt')}; "
        f"cannot prove the child never existed, refusing to rerun")
