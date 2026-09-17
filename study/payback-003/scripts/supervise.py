"""PAYBACK-003 run supervisor: durable external evidence of process termination.

Apparatus repair (earned by PAYBACK-002): the runner cannot be the sole
authority for reporting its own death. PAYBACK-002's process died with no
RUN_STATUS.json, and the runtime's background session record was lost, so
stdout/stderr and the exit itself were unrecoverable.

This supervisor launches the runner as a subprocess and, from process start:
  - redirects the child's stdout/stderr to durable files (console.out,
    console.err) in the run directory;
  - persists SUPERVISION.json: study id, command, runner PID, start time;
  - writes HEARTBEAT.json every --heartbeat-s seconds (child liveness plus
    observable progress markers: ledger lines, TASKS rows). The heartbeat
    reports what exists on disk; it never invents scientific observations;
  - on child exit, persists the exit code or terminating signal and the
    end time.

Termination classification (infrastructure evidence only):
  - expected: exit code 0 AND the runner wrote RUN_STATUS.json itself.
  - unexpected: any other exit (nonzero code, fatal signal) OR exit 0 with
    no RUN_STATUS.json. The supervisor then writes INFRA_TERMINAL.json
    classifying the unexpected termination.

INFRA_TERMINAL.json is an infrastructure record, not a scientific verdict:
it never rewrites RUN_STATUS.json, TASKS.jsonl, ledger.jsonl, or
verdict.json, and it never fabricates a completed run. Finalization is
idempotent: a second finalize leaves existing records byte-identical.

Usage:
  python supervise.py --run-dir <dir> -- <runner command...>

Zero provider contact by itself; it only supervises the child process.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time

HEARTBEAT_DEFAULT_S = 30


def _write_json(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _count_lines(path: str) -> int | None:
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return None


def heartbeat(run_dir: str, pid: int) -> dict:
    """Observable progress marker. Reports only what exists on disk."""
    alive = True
    try:
        os.kill(pid, 0)
    except OSError:
        alive = False
    return {
        "t": time.time(),
        "child_pid": pid,
        "child_alive": alive,
        "ledger_lines": _count_lines(run_dir + "/ledger.jsonl"),
        "tasks_rows": _count_lines(run_dir + "/TASKS.jsonl"),
        "run_status_present": os.path.isfile(run_dir + "/RUN_STATUS.json"),
    }


def classify(run_dir: str, returncode: int | None) -> dict:
    """Classify the child termination. Infrastructure only."""
    status_present = os.path.isfile(run_dir + "/RUN_STATUS.json")
    if returncode == 0 and status_present:
        return {"termination": "expected",
                "detail": "exit 0 with runner-written RUN_STATUS.json"}
    if returncode is not None and returncode < 0:
        return {"termination": "unexpected",
                "detail": f"killed by signal {-returncode}; "
                          f"RUN_STATUS.json present: {status_present}"}
    return {"termination": "unexpected",
            "detail": f"exit code {returncode} with "
                      f"RUN_STATUS.json present: {status_present}; the runner "
                      f"did not reach a terminal state it recorded itself"}


def finalize(run_dir: str, record: dict) -> dict:
    """Idempotent finalization. Never rewrites existing records."""
    sup_path = run_dir + "/SUPERVISION.json"
    if os.path.isfile(sup_path):
        existing = json.load(open(sup_path))
        if existing.get("finalized"):
            return existing  # already finalized: leave bytes identical
    else:
        existing = {}
    existing.update(record)
    existing["finalized"] = True
    _write_json(sup_path, existing)
    cls = record.get("classification", {})
    if cls.get("termination") == "unexpected" and \
            not os.path.isfile(run_dir + "/INFRA_TERMINAL.json"):
        _write_json(run_dir + "/INFRA_TERMINAL.json", {
            "record": "infrastructure_terminal",
            "study_id": record.get("study_id"),
            "classification": cls,
            "exit": {k: record.get(k) for k in ("exit_code", "signal")},
            "runner_pid": record.get("runner_pid"),
            "started_at": record.get("started_at"),
            "ended_at": record.get("ended_at"),
            "note": "The runner exited without recording its own terminal "
                    "state. This is infrastructure evidence only: no "
                    "scientific observation is invented here, and no "
                    "scientific artifact (RUN_STATUS.json, TASKS.jsonl, "
                    "ledger.jsonl, verdict.json) is created or modified.",
        })
    return existing


def supervise(run_dir: str, cmd: list[str], study_id: str,
              heartbeat_s: int) -> dict:
    os.makedirs(run_dir, exist_ok=True)
    started_at = time.time()
    out = open(run_dir + "/console.out", "wb")
    err = open(run_dir + "/console.err", "wb")
    proc = subprocess.Popen(cmd, stdout=out, stderr=err,
                            start_new_session=True)
    record = {
        "study_id": study_id,
        "command": cmd,
        "runner_pid": proc.pid,
        "started_at": started_at,
        "heartbeat_s": heartbeat_s,
    }
    _write_json(run_dir + "/SUPERVISION.json", record)

    def _forward(signum, _frame):
        try:
            os.killpg(proc.pid, signum)
        except OSError:
            pass

    old_term = signal.signal(signal.SIGTERM, _forward)
    old_int = signal.signal(signal.SIGINT, _forward)
    try:
        while proc.poll() is None:
            _write_json(run_dir + "/HEARTBEAT.json",
                        heartbeat(run_dir, proc.pid))
            time.sleep(heartbeat_s)
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    returncode = proc.poll()
    out.close()
    err.close()
    ended_at = time.time()
    # Final heartbeat: liveness now reflects the reaped child.
    _write_json(run_dir + "/HEARTBEAT.json", heartbeat(run_dir, proc.pid))
    record["ended_at"] = ended_at
    if returncode is not None and returncode < 0:
        record["signal"] = -returncode
        record["exit_code"] = None
    else:
        record["signal"] = None
        record["exit_code"] = returncode
    record["classification"] = classify(run_dir, returncode)
    return finalize(run_dir, record)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--study-id", default="payback003")
    ap.add_argument("--heartbeat-s", type=int, default=HEARTBEAT_DEFAULT_S)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise SystemExit("refusing: no runner command given")
    # The documented launch form uses a bare "python"/"python3" argv[0].
    # Resolve it to this interpreter so the child launches even when no
    # python is on PATH. An absolute argv[0] is used verbatim.
    if os.path.basename(cmd[0]) in ("python", "python3"):
        cmd = [sys.executable] + cmd[1:]
    record = supervise(args.run_dir, cmd, args.study_id, args.heartbeat_s)
    print(json.dumps({"runner_pid": record.get("runner_pid"),
                      "exit_code": record.get("exit_code"),
                      "signal": record.get("signal"),
                      "termination": record.get("classification", {})
                      .get("termination")}, indent=1))


if __name__ == "__main__":
    main()
