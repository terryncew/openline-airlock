"""RSI-006-Q3 scientific-contact authorization gate (receiver-owned).

The one-run scientific authorization is consumed by exactly one atomic
transition: the first actual start of a mutant-observation subprocess.

The gate owns the contact-marker file. Its sole mutating entry point is
``ContactGate.note_process_started``, which ``observe.run_suite_once``
invokes with the child pid immediately after ``subprocess.Popen``
returns on the mutant observation path -- i.e. only once the OS has
actually spawned the mutant-observation process. Nothing else may call
it:

- receipt verification, the feasibility guard, mutation generation,
  executor creation, and failed submissions all happen before any mutant
  ``Popen``, so none of them can consume authorization;
- the baseline path (``observe.observe_baseline``) never receives the
  hook, so environment qualification can never consume it either;
- a spawn failure (``OSError`` from ``Popen``) never reaches the hook.

Exactly-once is mechanical, not conventional: an in-process lock plus
an atomic ``O_CREAT|O_EXCL`` create of the marker file. The first actual
start creates the marker; every later start is a no-op that reads back
the winner's marker instead of rewriting or duplicating the event.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MARKER_SCHEMA = "airlock.rsi-006-q3.scientific-contact.v1"


class ContactGate:
    """Receiver-owned single-transition authorization gate."""

    def __init__(self, marker_path: Path):
        self._marker_path = Path(marker_path)
        self._lock = threading.Lock()

    @property
    def marker_path(self) -> Path:
        return self._marker_path

    @property
    def consumed(self) -> bool:
        """True once the authorization has been consumed."""
        return self._marker_path.exists()

    def read(self) -> dict | None:
        """Return the recorded contact event, or None if not consumed."""
        if not self._marker_path.exists():
            return None
        return json.loads(self._marker_path.read_bytes())

    def note_process_started(self, mutant_id: str, receipt_sha: str,
                             pid: int) -> dict:
        """Record the authorization-consumption event, exactly once.

        Must be called only from the mutant-observation subprocess-start
        boundary (``observe.run_suite_once``, immediately after ``Popen``
        returns). The first call atomically creates the marker and
        returns ``{"created": True, "marker": ...}``; every later call is
        a no-op returning ``{"created": False, "marker": <winner>}``.
        """
        marker = {
            "schema": MARKER_SCHEMA,
            "event": "scientific_contact",
            "mutant_id": mutant_id,
            "receipt_sha256": receipt_sha,
            "child_pid": pid,
            "ts": time.time(),
        }
        blob = json.dumps(marker, indent=1, sort_keys=True).encode("utf-8") \
            + b"\n"
        with self._lock:
            try:
                fd = os.open(str(self._marker_path),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return {"created": False,
                        "marker": self._read_winner_marker()}
            try:
                os.write(fd, blob)
                os.fsync(fd)
            finally:
                os.close(fd)
        print(f"[q3] SCIENTIFIC CONTACT: first mutant-observation process "
              f"started (pid {pid}, {mutant_id}); authorization consumed.",
              flush=True)
        return {"created": True, "marker": marker}

    def _read_winner_marker(self) -> dict:
        """Read back the winner's marker after losing an atomic-create race.

        The winner may still be writing, so poll briefly for parseable,
        schema-valid JSON rather than trusting the first bytes seen.
        """
        deadline = time.time() + 10.0
        last: Exception | None = None
        while time.time() < deadline:
            try:
                data = json.loads(self._marker_path.read_bytes())
                if data.get("schema") == MARKER_SCHEMA:
                    return data
            except (OSError, json.JSONDecodeError) as e:
                last = e
            time.sleep(0.01)
        raise RuntimeError(
            f"contact marker unreadable after atomic-create race: {last}")
