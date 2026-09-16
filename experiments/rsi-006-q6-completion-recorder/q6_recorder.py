"""Q6 one-shot completion recorder: verify bindings, run child, seal
outcome -> q6_launch -> q6_seal -> completion LAST."""

import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q3_DIR = Q6_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(Q6_DIR), str(Q6_DIR / "tests"), str(Q5_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import execution_ledger as ledger  # noqa: E402
from contact import ContactGate  # noqa: E402

CONFIG_SCHEMA = "airlock.rsi-006-q6.recorder-config.v1"
LAUNCH_SCHEMA = "airlock.rsi-006-q6.launch-sidecar.v1"
SEAL_SCHEMA = "airlock.rsi-006-q6.recorder-seal.v1"
REQUIRED_CONFIG_KEYS = (
    "schema", "txid", "observation_id", "phase", "attempt",
    "receipt_sha256", "code_hashes", "child_argv", "run_dir", "work_dir",
    "env_overrides", "prepared_env_sha256", "timeout_s", "builder",
    "spawn_failure_builder", "builder_context", "repo_name", "mutant",
    "baseline", "python", "junit_path", "gate_marker_path",
)

class RecorderRefusal(Exception):
    pass  # a sealed binding failed: refuse with zero child spawn

def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def canonical_env_bytes(env: dict) -> bytes:
    return json.dumps(env, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")

def _ledger(work_dir, cfg, fn, **kw):
    return fn(work_dir=work_dir, txid=cfg["txid"],
              observation_id=cfg["observation_id"], phase=cfg["phase"],
              receipt_sha256=cfg["receipt_sha256"],
              code_hashes=cfg["code_hashes"], **kw)


def _atomic_write_json(path: Path, record: dict) -> None:
    data = (json.dumps(record, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dfd = os.open(str(path.parent), os.O_DIRECTORY)
    try: os.fsync(dfd)
    finally: os.close(dfd)


def _resolve_dotted(dotted: str):
    mod_name, _, attr = dotted.rpartition(".")
    if not mod_name or not attr:
        raise RecorderRefusal(f"not a dotted name: {dotted!r}")
    try: return getattr(importlib.import_module(mod_name), attr)
    except (ImportError, AttributeError) as e:
        raise RecorderRefusal(f"cannot resolve {dotted!r}: {e}")


def _verify_prepared(cfg):
    ldir = ledger.ledger_dir(cfg["work_dir"])
    name = f"{cfg['observation_id']}.prepared.json"
    try: prepared = json.loads((ldir / name).read_bytes())
    except (OSError, ValueError) as e:
        raise RecorderRefusal(f"prepared unreadable: {e}")
    if prepared.get("schema") != ledger.PREPARED_SCHEMA:
        raise RecorderRefusal("prepared schema mismatch")
    for k in ("txid", "observation_id", "phase", "attempt",
              "receipt_sha256", "code_hashes"):
        if prepared.get(k) != cfg[k]:
            raise RecorderRefusal(f"prepared mismatch: {k}")


def _load_config(config_path: str, expected_sha: str):
    try:
        raw = Path(config_path).read_bytes()
    except OSError as e:
        raise RecorderRefusal(f"cannot read recorder config: {e}")
    if _sha256(raw) != expected_sha:
        raise RecorderRefusal("config digest != argv digest")
    try: cfg = json.loads(raw.decode("utf-8"))
    except ValueError as e: raise RecorderRefusal(f"config is not JSON: {e}")
    if not isinstance(cfg, dict) or cfg.get("schema") != CONFIG_SCHEMA:
        raise RecorderRefusal("config schema mismatch")
    if [k for k in REQUIRED_CONFIG_KEYS if k not in cfg]:
        raise RecorderRefusal("config missing required bindings")
    env = dict(os.environ)
    env.update(cfg["env_overrides"])
    if _sha256(canonical_env_bytes(env)) != cfg["prepared_env_sha256"]:
        raise RecorderRefusal("prepared environment digest mismatch")
    _verify_prepared(cfg)
    return cfg, _sha256(raw), env


def _seal_and_finish(work_dir, obs_id, cfg, outcome_bytes, launch,
                     exec_nonce, child_pid, disposition, contact_created,
                     config_sha):
    outcome_digest = ledger.write_outcome(
        work_dir=work_dir, observation_id=obs_id, outcome_bytes=outcome_bytes)
    bind = {"txid": cfg["txid"], "observation_id": obs_id,
            "phase": cfg["phase"], "attempt": cfg["attempt"],
            "receipt_sha256": cfg["receipt_sha256"],
            "code_hashes": cfg["code_hashes"], "exec_nonce": exec_nonce}
    launch_path = ledger.ledger_dir(work_dir) / f"{obs_id}.q6_launch.json"
    _atomic_write_json(launch_path, {
        "schema": LAUNCH_SCHEMA, **bind, "launch": launch,
        "outcome_digest": outcome_digest, "config_digest": config_sha})
    seal = {"schema": SEAL_SCHEMA, **bind, "child_pid": child_pid,
            "outcome_sha256": outcome_digest, "disposition": disposition,
            "launch_sha256": _sha256(launch_path.read_bytes()),
            "config_sha256": config_sha, "contact_created": contact_created}
    _atomic_write_json(
        ledger.ledger_dir(work_dir) / f"{obs_id}.q6_seal.json", seal)
    if cfg.get("fixture", {}).get("halt_after_seal"):  # F2 fixture halt
        os._exit(1)
    _ledger(work_dir, cfg, ledger.record_completion,
            outcome_digest=outcome_digest)


def main(argv) -> int:
    if len(argv) != 3:
        sys.exit("usage: q6_recorder.py <config_path> <config_sha256>")
    try:
        cfg, config_sha, env = _load_config(argv[1], argv[2])
        work_dir, obs_id = cfg["work_dir"], cfg["observation_id"]
        if (ledger.ledger_dir(work_dir) / f"{obs_id}.complete.json").exists():
            raise RecorderRefusal("completion exists: no 2nd execution")
        bkw = {"repo_name": cfg["repo_name"], "mutant": cfg["mutant"],
               "argv": list(cfg["child_argv"]), "python": cfg["python"],
               "run_dir": Path(cfg["run_dir"]), "env": env,
               "env_overrides": cfg["env_overrides"], **cfg["builder_context"]}
        exec_nonce, start_ts = os.urandom(16).hex(), time.time()
        try:
            proc = subprocess.Popen(
                cfg["child_argv"], cwd=cfg["run_dir"], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            mk = _resolve_dotted(cfg["spawn_failure_builder"])
            outcome_bytes, launch = mk(start_ts=start_ts,
                end_ts=time.time(), error=e, **bkw)
            _ledger(work_dir, cfg, ledger.record_spawn_failed,
                    attempt=cfg["attempt"],
                    error=f"{type(e).__name__}: {e}")
            _seal_and_finish(work_dir, obs_id, cfg, outcome_bytes, launch,
                             None, None, "spawn-failure", False, config_sha)
            return 0
        _ledger(work_dir, cfg, ledger.record_started,
                attempt=cfg["attempt"], child_pid=proc.pid,
                exec_nonce=exec_nonce)
        gate_created = ContactGate(
            cfg["gate_marker_path"]).note_process_started(
                obs_id, cfg["receipt_sha256"], proc.pid)["created"]
        t0 = time.monotonic()
        try:
            out, err = proc.communicate(timeout=cfg["timeout_s"])
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()  # exactly once, then reap
            out, err = proc.communicate()
        evidence = {
            "exec_nonce": exec_nonce, "child_pid": proc.pid,
            "argv": list(cfg["child_argv"]), "exit_status": proc.returncode,
            "timeout": timed_out, "stdout": out, "stderr": err,
            "duration_s": time.monotonic() - t0, "started_utc": start_ts,
            "ended_utc": time.time(), "started_monotonic": t0,
            "ended_monotonic": time.monotonic(),
            "contact_created": bool(gate_created)}
        outcome_bytes, launch = _resolve_dotted(cfg["builder"])(
            baseline=cfg["baseline"], junit_path=Path(cfg["junit_path"]),
            evidence=evidence, **bkw)
        _seal_and_finish(work_dir, obs_id, cfg, outcome_bytes, launch,
            exec_nonce, proc.pid, "timeout" if timed_out else "normal",
            bool(gate_created), config_sha)
        return 0
    except RecorderRefusal as e:
        print(f"q6_recorder: refusing: {e}", file=sys.stderr)
        return 3
    except Exception as e:  # fail closed, never half-sealed
        print(f"q6_recorder: unexpected {type(e).__name__}: {e}",
              file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv))
