"""Q6Coordinator(q5_adapter.Coordinator): overrides ONLY _worker_run.

Generic path delegates to frozen Q5. Scientific path keeps inherited
classify/_apply/completion/reconcile/run_all/journal/Q4 and adds the Q6
chain: fresh -> sealed recorder config + one-shot recorder, verify,
ordinary completed; recoverable -> verify sealed chain, attach nested
Q3 launch for inherited adopt. Bad evidence fails closed."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q3_DIR = Q6_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(Q6_DIR), str(Q6_DIR / "tests"), str(Q5_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import q5_adapter  # noqa: E402
import execution_ledger as ledger  # noqa: E402
from execution_ledger import UncertainExecution  # noqa: E402
from q6_recorder import (CONFIG_SCHEMA, LAUNCH_SCHEMA, SEAL_SCHEMA,
                         canonical_env_bytes)  # noqa: E402

RECORDER = str(Q6_DIR / "q6_recorder.py")
DISPOSITIONS = ("normal", "timeout", "spawn-failure")
# Q6-frozen bindings absent from frozen _prep (production Q3 timeout
# and frozen Q3 builder names).
Q6_TIMEOUT_S = 120.0
Q6_BUILDER = "run_rsi_006_q5.build_q3_completion"
Q6_SPAWN_FAILURE_BUILDER = "run_rsi_006_q5.build_q3_spawn_failure"


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_recorder_config(*, work_dir, tx, receipt_sha256, code_hashes,
                          observation_id, phase, attempt, prep,
                          marker_path) -> tuple[bytes, str]:
    env = dict(prep["env"])  # exact Q5 prep env; digest only
    config = {
        "schema": CONFIG_SCHEMA, "txid": tx.txid,
        "observation_id": observation_id, "phase": phase, "attempt": attempt,
        "receipt_sha256": receipt_sha256, "code_hashes": dict(code_hashes),
        "child_argv": list(prep["argv"]), "run_dir": str(prep["run_dir"]),
        "env_overrides": prep["env_overrides"], "work_dir": str(work_dir),
        "prepared_env_sha256": _sha256(canonical_env_bytes(env)),
        "timeout_s": prep.get("timeout_s", Q6_TIMEOUT_S),
        "builder": prep.get("builder", Q6_BUILDER),
        "spawn_failure_builder": prep.get(
            "spawn_failure_builder", Q6_SPAWN_FAILURE_BUILDER),
        "builder_context": dict(prep.get("builder_context", {})),
        "repo_name": prep["repo_name"], "mutant": dict(prep["mutant"]),
        "baseline": dict(prep["baseline"]), "python": prep["python"],
        "junit_path": str(prep["junit_path"]),
        "gate_marker_path": str(marker_path),
        "fixture": dict(prep.get("q6_fixture", {})),
    }
    raw = json.dumps(config, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return raw, _sha256(raw)


def write_recorder_config(work_dir, observation_id, config_bytes) -> Path:
    path = ledger.ledger_dir(work_dir) / f"{observation_id}.q6_config.json"
    if path.exists():
        raise UncertainExecution("q6: recorder config already exists")
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(config_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return path


class Q6Coordinator(q5_adapter.Coordinator):
    def _worker_run(self, *, observation_id, phase, spawn, argv,
                    barrier=None, _crash_hook=None, completion_builder=None,
                    spawn_failure_builder=None):
        prep = getattr(spawn, "q6_prep", None)
        if spawn_failure_builder is None or prep is None:
            return super()._worker_run(
                observation_id=observation_id, phase=phase, spawn=spawn,
                argv=argv, barrier=barrier, _crash_hook=_crash_hook,
                completion_builder=completion_builder,
                spawn_failure_builder=spawn_failure_builder)
        return self._q6_scientific_run(observation_id, phase, prep)

    def _q6_scientific_run(self, observation_id, phase, prep):
        tx, work_dir = self._tx, self._work_dir
        receipt, codes = self._receipt_sha256, self._code_hashes
        status, payload = self._classify(
            observation_id, phase, scientific=True)
        if status == "recoverable":
            # Attempt from the durable prepared record; adopt evidence
            # passes through for inherited _apply, Q6 launch attached.
            attempt = payload["evidence"]["ledger_prepared"]["attempt"]
            base = {"observation_id": observation_id, "phase": phase,
                    "attempt": attempt, "scientific": True}
            outcome_bytes, launch, _ = self._q6_verify(observation_id, phase)
            adopt_evidence = dict(payload["evidence"])
            adopt_evidence["launch"] = launch
            return {**base, "result": "recoverable",
                    "evidence": adopt_evidence,
                    "outcome_bytes": outcome_bytes, "launch": launch}
        base = {"observation_id": observation_id, "phase": phase,
                "attempt": payload["attempt"], "scientific": True}
        if status == "committed":
            return {**base, "result": "skipped_committed", "digest": payload}
        attempt = payload["attempt"]
        ledger.record_prepared(
            work_dir=work_dir, txid=tx.txid, observation_id=observation_id,
            phase=phase, attempt=attempt, receipt_sha256=receipt,
            code_hashes=codes, pid=os.getpid())
        config_bytes, config_sha = build_recorder_config(
            work_dir=work_dir, tx=tx, receipt_sha256=receipt,
            code_hashes=codes, observation_id=observation_id, phase=phase,
            attempt=attempt, prep=prep, marker_path=self._gate.marker_path)
        config_path = write_recorder_config(
            work_dir, observation_id, config_bytes)
        proc = subprocess.Popen(
            [sys.executable, RECORDER, str(config_path), config_sha])
        if proc.wait() != 0: raise UncertainExecution("q6: recorder failed")
        outcome_bytes, launch, seal = self._q6_verify(observation_id, phase)
        return {**base, "result": "completed", "outcome_bytes": outcome_bytes,
                "launch": launch, "gate_created": seal["contact_created"],
                "child_pid": seal["child_pid"],
                "exec_nonce": seal["exec_nonce"]}

    def _q6_verify(self, observation_id, phase):
        expect = {"txid": self._tx.txid, "observation_id": observation_id,
                  "phase": phase, "receipt_sha256": self._receipt_sha256,
                  "code_hashes": self._code_hashes}
        ldir = ledger.ledger_dir(self._work_dir)

        def _load(name, what, schema=None):
            try:
                raw = (ldir / f"{observation_id}.{name}.json").read_bytes()
                rec = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError) as e:
                raise UncertainExecution(f"q6: bad {what}: {e}")
            if not isinstance(rec, dict) or (
                    schema and rec.get("schema") != schema):
                raise UncertainExecution(f"q6: {what} malformed")
            for k, v in expect.items():
                if rec.get(k) != v:
                    raise UncertainExecution(f"q6: {what} misbound: {k}")
            return raw, rec

        def _eq(got, want, what):
            if got != want:
                raise UncertainExecution(f"q6: {what} mismatch")

        _, completion = _load("complete", "completion")
        digest = completion["outcome_digest"]
        op = ldir / f"{observation_id}.outcome.json"
        if not op.exists():
            raise UncertainExecution("q6: outcome bytes missing")
        outcome_bytes = op.read_bytes()
        _eq(_sha256(outcome_bytes), digest, "outcome digest")
        _, seal = _load("q6_seal", "seal", SEAL_SCHEMA)
        _eq(seal.get("outcome_sha256"), digest, "seal outcome digest")
        if seal.get("disposition") not in DISPOSITIONS:
            raise UncertainExecution("q6: unknown seal disposition")
        sidecar_raw, sidecar = _load("q6_launch", "sidecar", LAUNCH_SCHEMA)
        _eq(_sha256(sidecar_raw), seal.get("launch_sha256"),
            "sidecar digest")
        _eq(sidecar.get("outcome_digest"), digest, "sidecar outcome digest")
        config_raw, config = _load("q6_config", "config", CONFIG_SCHEMA)
        _eq(_sha256(config_raw), seal.get("config_sha256"),
            "seal config digest")
        _eq(_sha256(config_raw), sidecar.get("config_digest"),
            "sidecar config digest")
        _eq(config.get("attempt"), seal.get("attempt"), "config/seal attempt")
        _, prepared = _load("prepared", "prepared")
        _eq(prepared.get("attempt"), seal.get("attempt"),
            "prepared/seal attempt")
        if seal["disposition"] == "spawn-failure":
            _eq(seal.get("exec_nonce"), None, "spawn-failure nonce")
            _eq(seal.get("child_pid"), None, "spawn-failure pid")
            if (ldir / f"{observation_id}.started.json").exists():
                raise UncertainExecution("q6: spawn-failure has started")
            _, failed = _load("spawn_failed", "spawn_failed")
            _eq(failed.get("attempt"), seal.get("attempt"), "spawn_failed")
        else:
            _eq(seal.get("exec_nonce") is None, False, "seal exec nonce")
            _, started = _load("started", "started")
            _eq(started.get("attempt"), seal.get("attempt"), "started")
            _eq(started.get("child_pid"), seal.get("child_pid"), "child_pid")
            _eq(started.get("exec_nonce"), seal.get("exec_nonce"), "nonce")
        launch = sidecar.get("launch")
        if not isinstance(launch, dict):
            raise UncertainExecution("q6: nested launch is not a record")
        return outcome_bytes, launch, seal
