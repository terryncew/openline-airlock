"""Process-ownership boundary for Q6 (frozen §6 launch mechanics).

The frozen contract: the coordinator worker spawns the recorder with
``start_new_session=True`` so a coordinator SIGKILL does not take the
recorder with it; orphan survival after coordinator death is the same
property Q5's crash tests already rely on empirically.

This fixture proves the actual frozen property against a real
dedicated coordinator process:

- coordinator PID is distinct;
- recorder PID is distinct;
- recorder is a session leader (its own independent session);
- recorder session differs from coordinator session;
- the scientific child remains owned by the recorder path (child of
  the recorder, in the recorder's session);
- ordinary PID-local coordinator SIGKILL still leaves recorder +
  child alive.

Q6 does NOT claim survival under process-group kill (killpg /
kill -- -PGID), session/container/job teardown, host crash, power
loss, or filesystem loss. The frozen out-of-scope list remains
authoritative.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import q6_testkit as kit  # noqa: F401  (sets up sys.path for q6_adapter)

TESTS_DIR = Path(__file__).resolve().parent
DRIVER = str(TESTS_DIR / "f1_driver.py")
CHILD = str(TESTS_DIR / "f1_child.py")


def _wait_for(path, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if Path(path).exists():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {path}")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _children_of(ppid):
    """PIDs whose parent is ppid, via /proc."""
    kids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            data = (entry / "stat").read_text().split()
            if int(data[3]) == ppid:
                kids.append(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return kids


def _cmdline(pid):
    try:
        return (Path(f"/proc/{pid}/cmdline").read_bytes()
                .replace(b"\0", b" ").decode("utf-8", "replace"))
    except OSError:
        return ""


def _find_recorder(coordinator_pid, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for pid in _children_of(coordinator_pid):
            if "q6_recorder.py" in _cmdline(pid):
                return pid
        time.sleep(0.1)
    raise AssertionError("recorder process never appeared")


def test_recorder_independent_session_survives_coordinator_sigkill(
        work_dir, explicit_env):
    """Frozen §6: recorder in its own session survives coordinator SIGKILL."""
    work = Path(work_dir)
    obs_id = "obs-boundary-1"
    ready = work / "ready"; release = work / "release"
    marker = work / "marker"; out = work / "out"
    coord_proc = subprocess.Popen(
        [sys.executable, DRIVER, "fresh", str(work), obs_id,
         str(ready), str(release), str(marker), str(out), CHILD])
    rec_pid = None
    try:
        coord_pid = coord_proc.pid
        _wait_for(ready)  # child started; recorder blocked in wait
        rec_pid = _find_recorder(coord_pid)
        assert rec_pid != coord_pid

        coord_sid = os.getsid(coord_pid)
        rec_sid = os.getsid(rec_pid)
        # Recorder is a session leader with an independent session.
        assert rec_sid == rec_pid
        assert rec_sid != coord_sid

        # Scientific child owned by the recorder path, in its session.
        kids = _children_of(rec_pid)
        assert kids, "recorder has no scientific child"
        child_pid = kids[0]
        assert os.getsid(child_pid) == rec_sid
        assert "f1_child.py" in _cmdline(child_pid)

        # PID-local coordinator SIGKILL: recorder + child survive.
        os.kill(coord_pid, signal.SIGKILL)
        coord_proc.wait(timeout=30)
        assert not _alive(coord_pid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not _alive(rec_pid):
            time.sleep(0.1)
        assert _alive(rec_pid), "recorder died with coordinator"
        assert _alive(child_pid), "scientific child died with coordinator"
        # Session identity is unchanged after the kill.
        assert os.getsid(rec_pid) == rec_sid == rec_pid
    finally:
        release.touch()
        try:
            coord_proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            coord_proc.kill()
        if rec_pid is not None:  # drain the orphaned recorder before rmtree
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and _alive(rec_pid):
                time.sleep(0.1)
