"""RSI-006-Q5 fixture driver: real-subprocess observation runs.

Runs observations through the single-writer ``Coordinator`` using a
fixture "mutant" subprocess (a trivial ``python -c`` program, NOT a
real repository): it sleeps briefly, writes one marker file named by
its exec_nonce (fsync'd), and echoes the nonce on stdout. Each physical
execution is therefore distinguishable by its marker.

The driver is the coordinator: it holds the coordinator-exclusion lock
for its whole lifetime, begins (or opens, exactly once, when resuming)
the transaction, reconciles contact, then dispatches worker threads
that race at real process-start/contact and return evidence for the
coordinator to journal serially.

Flags:
  --observations  csv of observation ids (default obs-A,obs-B)
  --workers       worker thread count (default 1)
  --sync-spawn    rendezvous all workers on a barrier after prepare,
                  before spawn: simultaneous child starts
  --fail-spawn-for <id>
                  the spawn callable performs a real Popen against a
                  nonexistent executable for this observation: a
                  deterministic Popen failure with zero child created
  --crash-point <point>:<id>
                  os._exit(1) inside the worker's crash window:
                    after_prepared  -- prepared written, before spawn
                    after_spawn     -- child spawned, before the
                                       post-Popen started record
                    after_started   -- started written, before the wait
                    after_completion -- completion durable, before the
                                        coordinator journals

Exit codes: 0 = all observations committed/adopted/skipped/spawn_failed;
2 = fail-closed (UncertainExecution); 1 = unexpected error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DRIVER_DIR = Path(__file__).resolve().parent
EXP_DIR = DRIVER_DIR.parent
Q4_DIR = EXP_DIR.parent / "rsi-006-q4-durable-transaction"
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"

for _d in (str(EXP_DIR), str(Q4_DIR), str(Q3_DIR)):
    sys.path.insert(0, _d)

import stransaction as st
import q5_adapter as qa
from contact import ContactGate

# Fixture-only receipt. Deterministic, valid hex, and obviously not the
# Q3 scientific receipt (which must never be reused for Q5).
FIXTURE_RECEIPT_SHA256 = hashlib.sha256(
    b"rsi-006-q5-fixture-receipt").hexdigest()

CHILD_SCRIPT = (
    "import json, os, sys, time; "
    "nonce = sys.argv[1]; mdir = sys.argv[2]; "
    "time.sleep(0.3); "
    "rec = {'exec_nonce': nonce, 'pid': os.getpid(), 'ts': time.time()}; "
    "p = os.path.join(mdir, nonce + '.json'); "
    "fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY); "
    "os.write(fd, (json.dumps(rec) + chr(10)).encode('utf-8')); "
    "os.fsync(fd); os.close(fd); "
    "dfd = os.open(mdir, os.O_DIRECTORY); os.fsync(dfd); os.close(dfd); "
    "sys.stdout.write('fixture-ok:' + nonce + chr(10)); "
    "sys.stdout.flush()"
)


def make_spawn(marker_dir: Path):
    marker_dir = Path(marker_dir)
    marker_dir.mkdir(parents=True, exist_ok=True)

    def spawn(exec_nonce: str):
        return subprocess.Popen(
            [sys.executable, "-c", CHILD_SCRIPT, exec_nonce,
             str(marker_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    return spawn


def code_hashes() -> dict:
    return {
        "stransaction.py": hashlib.sha256(
            (Q4_DIR / "stransaction.py").read_bytes()).hexdigest(),
        "execution_ledger.py": hashlib.sha256(
            (EXP_DIR / "execution_ledger.py").read_bytes()).hexdigest(),
        "q5_adapter.py": hashlib.sha256(
            (EXP_DIR / "q5_adapter.py").read_bytes()).hexdigest(),
    }


def begin_or_open(work_dir: Path, tx_nonce: str):
    """Begin, or open EXACTLY ONCE when resuming an existing journal.

    The coordinator never re-opens during its lifetime: open() appends
    a durable ``restart`` entry, and repeated opens under contention
    would mint false restart provenance.
    """
    work_dir = Path(work_dir)
    journal = work_dir / "journal"
    if journal.exists() and any(journal.iterdir()):
        return st.ScientificTransaction.open(
            work_dir, receipt_sha256=FIXTURE_RECEIPT_SHA256,
            code_hashes=code_hashes())
    return st.ScientificTransaction.begin(
        work_dir, receipt_sha256=FIXTURE_RECEIPT_SHA256,
        code_hashes=code_hashes(), tx_nonce=tx_nonce)


def parse_crash_point(spec: str | None):
    if not spec or spec == "none":
        return None, None
    point, _, obs_id = spec.partition(":")
    if point not in ("after_prepared", "after_spawn", "after_started",
                     "after_completion") or not obs_id:
        raise ValueError(f"bad crash point: {spec!r}")
    return point, obs_id


def parse_delay(spec):
    """Parse --delay-spawn-for OBS:SECONDS."""
    if not spec:
        return None, 0.0
    obs_id, _, secs = spec.partition(":")
    if not obs_id or not secs:
        raise ValueError(f"bad delay spec: {spec!r}")
    return obs_id, float(secs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--tx-nonce", required=True)
    ap.add_argument("--observations", default="obs-A,obs-B")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--sync-spawn", action="store_true")
    ap.add_argument("--fail-spawn-for", default=None)
    ap.add_argument("--delay-spawn-for", default=None,
                    help="OBS:SECONDS -- sleep SECONDS inside OBS's spawn() "
                         "after the rendezvous, so a sibling worker "
                         "deterministically wins ContactGate")
    ap.add_argument("--crash-point", default="none")
    ap.add_argument("--marker-dir", default=None)
    ap.add_argument("--hold", action="store_true",
                    help="after the run, hold the coordinator lock alive "
                         "until killed (exclusion test)")
    args = ap.parse_args()

    work_dir = Path(args.work_dir)
    marker_dir = Path(args.marker_dir) if args.marker_dir \
        else work_dir / "exec_markers"

    try:
        # One coordinator per work directory, for its whole lifetime.
        # Acquisition is non-blocking: a second coordinator fails
        # closed here, before opening/mutating Q4, before any ledger
        # record, and before any contact state.
        with qa.interprocess_lock(work_dir):
            tx = begin_or_open(work_dir, args.tx_nonce)
            gate = ContactGate(work_dir / "contact_marker.json")
            coord = qa.Coordinator(
                work_dir=work_dir, tx=tx, gate=gate,
                receipt_sha256=FIXTURE_RECEIPT_SHA256,
                code_hashes=code_hashes())
            coord.reconcile_contact()

            obs_ids = [o for o in args.observations.split(",") if o]
            observations = [(o, "discovery") for o in obs_ids]
            point, point_id = parse_crash_point(args.crash_point)
            crash_points = {point_id: point} if point else {}
            fail_obs = args.fail_spawn_for
            delay_obs, delay_secs = parse_delay(args.delay_spawn_for)
            base_spawn = make_spawn(marker_dir)

            def argv_for(obs_id: str):
                return [sys.executable, "-c", "fixture-child", obs_id]

            def spawn_for(obs_id: str):
                # Per-observation spawn so --fail-spawn-for can target
                # one observation with a deterministic, real Popen
                # failure (no child created), and --delay-spawn-for can
                # hold one worker's spawn path after the rendezvous so a
                # sibling deterministically wins ContactGate.
                def spawn(exec_nonce: str):
                    if delay_obs == obs_id:
                        time.sleep(delay_secs)
                    if fail_obs == obs_id:
                        return subprocess.Popen(
                            ["/nonexistent-rsi-006-q5-binary"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
                    return base_spawn(exec_nonce)
                return spawn

            applied = coord.run_all(
                observations=observations, spawn=base_spawn,
                argv_for=argv_for, spawn_for=spawn_for,
                crash_points=crash_points,
                sync_spawn=args.sync_spawn, max_workers=args.workers)
            for row in applied:
                print(json.dumps(row), flush=True)
            print(json.dumps({"done": True, "results": applied}),
                  flush=True)
            if args.hold:
                # Stay alive holding the coordinator lock until killed.
                # Real process death releases the flock; a successor
                # then resumes via open().
                print(json.dumps({"holding": True}), flush=True)
                sys.stdin.read()
            return 0
    except qa.CoordinatorExclusionError as exc:
        print(json.dumps({"excluded": True, "error": str(exc)}),
              flush=True)
        return 3
    except qa.UncertainExecution as exc:
        print(json.dumps({"fail_closed": True, "error": str(exc)}),
              flush=True)
        return 2
    except Exception as exc:  # noqa: BLE001 -- driver reports, never hides
        print(json.dumps({"driver_error": f"{type(exc).__name__}: {exc}"}),
              flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
