"""F1 — real coordinator-process failure.

A dedicated Q6 coordinator driver subprocess runs the ordinary
Q6Coordinator._worker_run path with a blocking fixture child. The
parent test observes prepared/started/contact, SIGKILLs the
coordinator PID, verifies the recorder and child survive, releases
the child, waits for the sealed completion, then starts a fresh
successor process that goes through the ordinary recovery path
(_classify -> recoverable -> reconcile_contact -> inherited _apply ->
adopt_orphan_observation), proving the original ContactGate event is
reconciled into the resumed Q4 transaction before observation_adopted.

Physical execution count is proven by an fsync'd marker file written
by the child itself (one line per execution), not by ledger filename
inference.

Durability scope (narrow): the fixture work dir lives under the repo
tree (never /tmp); ledger writes are fsync'd and atomic where the
frozen ledger implements them. What F1 proves is recovery across
coordinator-PROCESS failure on the same host, filesystem, and durable
root. Explicitly NOT proven: reboot, host crash, power loss,
device/filesystem loss, VM destruction, process-group destruction, or
recorder death before completion (that case is F2: fail closed, zero
replay/adoption).

Fixture-only. No Stage 1, no real Q3 workload, no scientific contact.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import q6_testkit as kit
import execution_ledger as ledger

TESTS_DIR = Path(__file__).resolve().parent
CHILD_SCRIPT = str(TESTS_DIR / "f1_child.py")
DRIVER_SCRIPT = str(TESTS_DIR / "f1_driver.py")


def _wait_for(cond, timeout=30, desc="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.1)
    raise AssertionError(f"F1: timed out waiting for {desc}")


def _process_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _find_recorder_pid(config_path):
    """Find the q6_recorder.py process running with this config."""
    want = str(config_path)
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        if "q6_recorder.py" in cmd and want in cmd:
            return int(pid)
    return None


def _controlled_env(columns, lines):
    """Build an explicit env for the driver subprocess.

    The mechanism must bind the ACTUAL prepared environment values,
    not require 80x24. The parent sets COLUMNS/LINES explicitly so the
    driver, the prep capture, and the recorder all see the same values.
    """
    env = dict(os.environ)
    if columns is None:
        env.pop("COLUMNS", None)
    else:
        env["COLUMNS"] = str(columns)
    if lines is None:
        env.pop("LINES", None)
    else:
        env["LINES"] = str(lines)
    return env


def _run_f1(work_dir, columns, lines):
    """Execute the full F1 protocol; return the evidence dict."""
    wd = str(work_dir)
    obs_id = "obs-f1-kill"
    ready_file = work_dir / "child_ready"
    release_file = work_dir / "child_release"
    marker_file = work_dir / "exec_marker"
    txid_file = work_dir / "driver_txid"
    result_file = work_dir / "successor_result.json"
    env = _controlled_env(columns, lines)

    # --- 1. Launch the coordinator driver (fresh mode). ---
    driver = subprocess.Popen(
        [sys.executable, DRIVER_SCRIPT, "fresh", wd, obs_id,
         str(ready_file), str(release_file), str(marker_file),
         str(txid_file), CHILD_SCRIPT],
        env=env)
    coord_pid = driver.pid
    assert _process_alive(coord_pid), "F1: driver did not start"

    # --- 2. Wait for the child READY signal. ---
    # READY proves: prepared durable, recorder launched, started
    # durable, ContactGate crossed, child spawned and alive.
    _wait_for(ready_file.exists, timeout=60, desc="child READY")
    txid_before = txid_file.read_text(encoding="utf-8").strip()
    assert txid_before, "F1: driver did not write txid"

    # --- 3. Observe pre-kill state. ---
    assert kit.ledger_file(wd, obs_id, "prepared").exists(), \
        "F1: prepared not durable before kill"
    assert kit.ledger_file(wd, obs_id, "started").exists(), \
        "F1: started not durable before kill"
    contact_marker = work_dir / "contact_marker.json"
    assert contact_marker.exists(), "F1: ContactGate not crossed before kill"
    # If completion exists before the kill, the run is invalid.
    assert not kit.ledger_file(wd, obs_id, "complete").exists(), \
        "F1 INVALID: completion existed before coordinator kill"

    started = kit.read_json(kit.ledger_file(wd, obs_id, "started"))
    child_pid = started["child_pid"]
    assert isinstance(child_pid, int) and child_pid > 0
    assert _process_alive(child_pid), "F1: child not alive before kill"

    config_path = ledger.ledger_dir(wd) / f"{obs_id}.q6_config.json"
    recorder_pid = _find_recorder_pid(config_path)
    assert recorder_pid is not None, "F1: recorder PID not found"
    assert recorder_pid != coord_pid, "F1: recorder is the coordinator?"
    assert _process_alive(recorder_pid), "F1: recorder not alive before kill"

    # --- 4. SIGKILL the coordinator PID. ---
    os.kill(coord_pid, signal.SIGKILL)
    driver.wait(timeout=10)
    assert driver.returncode == -signal.SIGKILL, \
        f"F1: driver exit was {driver.returncode}, not SIGKILL"
    assert not _process_alive(coord_pid), "F1: coordinator still alive"

    # --- 5. Recorder and child must survive. ---
    assert _process_alive(recorder_pid), "F1: recorder died with coordinator"
    assert _process_alive(child_pid), "F1: child died with coordinator"

    # --- 6. Release the child; recorder seals. ---
    release_file.write_text("release\n", encoding="utf-8")
    _wait_for(lambda: kit.ledger_file(wd, obs_id, "complete").exists(),
              timeout=60, desc="Q5 completion")

    # Recorder must have exited after sealing.
    _wait_for(lambda: not _process_alive(recorder_pid),
              timeout=30, desc="recorder exit after seal")

    # --- 7. Verify seal ordering: outcome -> launch -> seal -> completion. ---
    ldir = ledger.ledger_dir(wd)
    outcome_p = ldir / f"{obs_id}.outcome.json"
    launch_p = ldir / f"{obs_id}.q6_launch.json"
    seal_p = ldir / f"{obs_id}.q6_seal.json"
    complete_p = ldir / f"{obs_id}.complete.json"
    for p in (outcome_p, launch_p, seal_p, complete_p):
        assert p.exists(), f"F1: missing {p.name}"
    # mtime order proves persistence order (files created sequentially).
    assert outcome_p.stat().st_mtime <= launch_p.stat().st_mtime <= \
        seal_p.stat().st_mtime <= complete_p.stat().st_mtime, \
        "F1: persistence order violated"

    seal = kit.read_json(seal_p)
    outcome_bytes = outcome_p.read_bytes()
    outcome_digest = hashlib.sha256(outcome_bytes).hexdigest()
    assert seal["outcome_sha256"] == outcome_digest
    assert seal["child_pid"] == child_pid
    exec_nonce = seal["exec_nonce"]
    assert exec_nonce, "F1: seal has no exec_nonce"
    assert seal["disposition"] == "normal"

    # --- 8. Successor: fresh process, ordinary recovery path. ---
    successor = subprocess.Popen(
        [sys.executable, DRIVER_SCRIPT, "successor", wd, obs_id,
         str(ready_file), str(release_file), str(marker_file),
         str(result_file), CHILD_SCRIPT],
        env=env)
    rc = successor.wait(timeout=60)
    assert rc == 0, f"F1: successor exited {rc}"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["worker_result"] == "recoverable", \
        f"F1: successor did not classify recoverable: {result}"
    assert result["applied_status"] == "adopted", \
        f"F1: successor did not adopt: {result}"
    assert result["contact_reconciled"] is True, \
        f"F1: successor did not reconcile contact: {result}"
    assert result["contact_child_pid"] == child_pid, \
        "F1: reconciled contact child PID != original child PID"

    # --- 9. Exact evidence. ---
    txid_after = result["txid"]
    assert txid_after == txid_before, "F1: txid changed across kill"

    # Journal: exactly one contact event for the original
    # observation/child, ordered BEFORE exactly one observation_adopted.
    journal_dir = work_dir / "journal"
    events = []
    for jf in sorted(journal_dir.glob("[0-9]*.json")):
        events.append(kit.read_json(jf))
    contacts = [e for e in events
                if e.get("type") == "contact"
                and e.get("payload", {}).get("mutant_id") == obs_id]
    assert len(contacts) == 1, \
        f"F1: expected 1 contact event, got {len(contacts)}"
    assert contacts[0]["payload"]["child_pid"] == child_pid, \
        "F1: contact event child PID != original child PID"
    adopted = [e for e in events
               if e.get("type") == "observation_adopted"
               and e.get("payload", {}).get("mutant_id") == obs_id]
    assert len(adopted) == 1, \
        f"F1: expected 1 observation_adopted, got {len(adopted)}"
    # Ordering: contact reconciled into the resumed transaction BEFORE
    # the adoption. Journal filenames are zero-padded sequence numbers.
    contact_idx = events.index(contacts[0])
    adopted_idx = events.index(adopted[0])
    assert contact_idx < adopted_idx, \
        "F1: contact event not ordered before observation_adopted"
    # Same attempt, adopted digest equals the original outcome digest.
    assert adopted[0]["payload"]["digest"] == outcome_digest, \
        "F1: adopted digest != original outcome digest"
    prepared = kit.read_json(ldir / f"{obs_id}.prepared.json")
    assert seal["attempt"] == prepared["attempt"], \
        "F1: seal attempt != prepared attempt"

    # Exactly one physical scientific child execution (fsync'd marker).
    marker_lines = marker_file.read_text(
        encoding="utf-8").strip().split("\n")
    assert len(marker_lines) == 1, \
        f"F1: expected 1 physical execution, got {len(marker_lines)}"
    assert f"pid={child_pid}" in marker_lines[0], \
        "F1: marker PID != started child PID"

    # No second recorder launch: exactly one config, one seal.
    assert len(list(ldir.glob(f"{obs_id}.q6_config.json"))) == 1
    assert len(list(ldir.glob(f"{obs_id}.q6_seal.json"))) == 1
    # No second child Popen: exactly one started record.
    assert len(list(ldir.glob(f"{obs_id}.started.json"))) == 1

    # ContactGate marker is the boundary proof of exactly one contact.
    assert contact_marker.exists()

    return {
        "coordinator_pid": coord_pid,
        "recorder_pid": recorder_pid,
        "child_pid": child_pid,
        "txid_before": txid_before,
        "txid_after": txid_after,
        "exec_nonce": exec_nonce,
        "outcome_digest": outcome_digest,
        "adopted_digest": result["digest"],
        "columns": columns,
        "lines": lines,
    }


@pytest.mark.parametrize("columns,lines", [
    (80, 24),
    (137, 51),
])
def test_f1_real_coordinator_kill(work_dir, columns, lines):
    """F1 with explicit terminal dimensions: the mechanism binds the
    actual prepared env values, not 80x24."""
    ev = _run_f1(work_dir, columns, lines)
    assert ev["txid_before"] == ev["txid_after"]
    assert ev["columns"] == columns and ev["lines"] == lines


def test_f1_env_absent(work_dir):
    """F1 with COLUMNS/LINES absent: if the harness injects them into
    the recorder subprocess, the digest refuses (fail-closed) and the
    test documents that; if truly absent, the mechanism still binds."""
    env = _controlled_env(None, None)
    # Probe: does a subprocess actually see them absent?
    probe = subprocess.run(
        [sys.executable, "-c",
         "import os; print('COLUMNS' in os.environ, 'LINES' in os.environ)"],
        capture_output=True, text=True, env=env, timeout=10)
    if probe.stdout.strip() != "False False":
        pytest.skip("harness injects COLUMNS/LINES into subprocesses; "
                    "absent-env case not permitted by this driver")
    ev = _run_f1(work_dir, None, None)
    assert ev["txid_before"] == ev["txid_after"]
