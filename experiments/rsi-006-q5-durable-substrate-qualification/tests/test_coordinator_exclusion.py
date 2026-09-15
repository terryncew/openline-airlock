"""Coordinator exclusion across OS processes (pre-contact).

A holds the coordinator-exclusion flock alive on a durable work
directory. B, a separate OS process, must fail closed with
``CoordinatorExclusionError`` before opening/mutating Q4, before any
restart entry, before any ledger record, and before any contact
state -- the journal must be byte-for-byte unchanged by B. After A
dies a real process death, C resumes: it acquires the released flock,
calls ``ScientificTransaction.open()`` exactly once (exactly one
restart entry), and never re-executes A's committed observation merely
because ownership transferred.

Separate OS processes -- not threads -- because the claim is that the
flock excludes a second coordinator *process*.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from conftest import (DRIVER, fresh_nonce, journal_types, marker_nonces,
                      reopen_tx, restart_entry_count, run_driver)


def _dir_snapshot(path: Path) -> dict:
    """Byte-for-byte snapshot of a directory's files."""
    snap = {}
    if path.exists():
        for p in sorted(path.iterdir()):
            if p.is_file():
                snap[p.name] = p.read_bytes()
    return snap


def _journal_snapshot(work_dir: Path) -> dict:
    return _dir_snapshot(work_dir / "journal")


def _ledger_snapshot(work_dir: Path) -> dict:
    return _dir_snapshot(work_dir / "artifacts" / "execution_ledger")


def _spawn_holder(work_dir: Path) -> subprocess.Popen:
    """Start coordinator A: commits obs-A, then holds the flock alive."""
    return subprocess.Popen(
        [sys.executable, str(DRIVER),
         "--work-dir", str(work_dir),
         "--tx-nonce", fresh_nonce(),
         "--observations", "obs-A",
         "--workers", "1",
         "--hold"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1)


def _wait_holding(proc: subprocess.Popen, timeout=120) -> None:
    """Block until A prints its holding marker (lock held, run done)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if payload.get("holding"):
            assert proc.poll() is None, "holder exited after holding"
            return
    rc = proc.poll()
    err = ""
    try:
        _, err = proc.communicate(timeout=5)
    except Exception:  # noqa: BLE001 -- best-effort diagnostics
        pass
    raise AssertionError(
        f"coordinator A never reached holding state (rc={rc}): "
        f"{err[:2000]}")


def test_coordinator_exclusion_across_os_processes(work_dir, bindings):
    # 1. Coordinator A starts, commits obs-A, and holds the
    # coordinator-exclusion flock alive.
    proc_a = _spawn_holder(work_dir)
    try:
        _wait_holding(proc_a)
        assert proc_a.poll() is None  # A alive, lock held

        journal_before = _journal_snapshot(work_dir)
        ledger_before = _ledger_snapshot(work_dir)
        assert journal_before, "A should have begun a journal"
        assert restart_entry_count(work_dir) == 0
        assert len(marker_nonces(work_dir)) == 1  # obs-A executed once

        # 2-4. Coordinator B, a separate OS process, starts while A is
        # alive. It must fail closed BEFORE opening/mutating Q4,
        # before any restart entry, before any ledger record, and
        # before any contact state.
        r_b = run_driver(work_dir, "--observations", "obs-A,obs-B",
                         "--workers", "1")
        assert r_b.returncode == 3, r_b.stdout + r_b.stderr
        assert '"excluded": true' in r_b.stdout
        assert _journal_snapshot(work_dir) == journal_before
        assert _ledger_snapshot(work_dir) == ledger_before
        assert restart_entry_count(work_dir) == 0
        assert len(marker_nonces(work_dir)) == 1  # B spawned nothing
        assert journal_types(work_dir).count("contact") == 1
    finally:
        # 5. Real process death for A; the OS releases the flock.
        if proc_a.poll() is None:
            proc_a.kill()
        proc_a.wait(timeout=60)
        for stream in (proc_a.stdin, proc_a.stdout, proc_a.stderr):
            try:
                stream.close()
            except Exception:  # noqa: BLE001 -- best-effort cleanup
                pass

    # 6-7. Coordinator C starts: acquires the released flock and calls
    # ScientificTransaction.open() exactly once -- exactly one restart
    # entry for the one genuine resume (asserted before any reopen,
    # which would itself append a restart).
    r_c = run_driver(work_dir, "--observations", "obs-A,obs-B",
                     "--workers", "1")
    assert r_c.returncode == 0, r_c.stdout + r_c.stderr
    assert restart_entry_count(work_dir) == 1

    # 8. No observation is re-executed merely because ownership
    # transferred A -> C: obs-A's committed observation is skipped
    # (still exactly one physical execution), obs-B runs its genuine
    # first attempt.
    assert len(marker_nonces(work_dir)) == 2
    tx = reopen_tx(work_dir, bindings)
    assert set(tx.observations) == {"obs-A", "obs-B"}
    assert journal_types(work_dir).count("contact") == 1
