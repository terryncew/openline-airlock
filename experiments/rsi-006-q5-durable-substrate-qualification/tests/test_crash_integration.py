"""Crash-injection integration tests with actual subprocesses.

Each test kills the fixture driver inside a crash window (os._exit),
then resumes in a fresh driver process and asserts the ledger's resume
semantics: fail closed with zero second execution, or adopt the exact
first result. Physical execution counts come from the children's
fsync'd marker files, never from the driver's word.

Crash windows (worker side):
  after_prepared   -- prepared written, before the spawn is attempted;
  after_spawn      -- child physically spawned, before the post-Popen
                      started record is durable;
  after_started    -- started written, before the wait;
  after_completion -- outcome + completion durable, before the
                      coordinator journals.
"""

import hashlib
import json

from conftest import (journal_types, ledger_record, ledger_record_path,
                      marker_nonces, reopen_tx, run_driver,
                      wait_for_markers)


def _rows(proc):
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def test_spawn_failure_is_zero_contact_and_retryable(work_dir, bindings):
    # Deterministic, real Popen failure: the executable does not exist,
    # so no child is created. Q3 treats this as zero scientific contact;
    # the ledger must prove it and allow a genuine first attempt later.
    r1 = run_driver(work_dir, "--observations", "obs-A",
                    "--fail-spawn-for", "obs-A")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    rows = _rows(r1)
    assert rows[0]["status"] == "spawn_failed"
    assert rows[0]["observation_id"] == "obs-A"

    # Zero Q3 contact: the gate marker was never created.
    assert not (work_dir / "contact_marker.json").exists()
    # Zero Q4 contact: no contact entry was journaled.
    assert "contact" not in journal_types(work_dir)
    # Durable spawn_failed, paired with the prepared attempt.
    failed = ledger_record(work_dir, "obs-A", "spawn_failed")
    assert failed["schema"] == "airlock.rsi-006-q5.spawn-failed.v1"
    assert failed["attempt"] == 1
    prepared = ledger_record(work_dir, "obs-A", "prepared")
    assert prepared["attempt"] == 1
    assert not ledger_record_path(work_dir, "obs-A",
                                  "started").exists()
    # No physical execution happened: no marker files at all.
    assert marker_nonces(work_dir) == set()

    # A later valid first launch is allowed: the same observation id
    # classifies as retry_allowed and runs for real.
    r2 = run_driver(work_dir, "--observations", "obs-A")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    rows2 = _rows(r2)
    assert rows2[0]["status"] == "committed"
    assert rows2[0]["contact_created"] is True
    assert len(marker_nonces(work_dir)) == 1
    assert "contact" in journal_types(work_dir)
    # Attempt 2 is a new reservation; the spawn_failed stays as history.
    assert ledger_record(work_dir, "obs-A", "prepared")["attempt"] == 2
    assert ledger_record(work_dir, "obs-A", "started")["attempt"] == 2
    assert ledger_record(work_dir, "obs-A",
                         "spawn_failed")["attempt"] == 1
    tx2 = reopen_tx(work_dir, bindings)
    assert "obs-A" in tx2.observations


def test_crash_after_spawn_before_started_fails_closed(work_dir, bindings):
    # prepared -> child physically spawned -> coordinator dies before
    # the post-Popen callback durably records started. On resume this
    # must fail closed: absence of a started record is not proof that
    # the child never existed.
    r1 = run_driver(work_dir, "--observations", "obs-A",
                    "--crash-point", "after_spawn:obs-A")
    assert r1.returncode == 1  # os._exit(1): the injected crash
    wait_for_markers(work_dir, 1)  # the orphan child ran exactly once

    assert ledger_record_path(work_dir, "obs-A", "prepared").exists()
    assert not ledger_record_path(work_dir, "obs-A",
                                  "started").exists()
    assert not ledger_record_path(work_dir, "obs-A",
                                  "spawn_failed").exists()

    r2 = run_driver(work_dir, "--observations", "obs-A")
    assert r2.returncode == 2, r2.stdout + r2.stderr  # fail closed
    assert '"fail_closed": true' in r2.stdout
    # Zero second execution: the orphan's marker is the only one.
    assert len(marker_nonces(work_dir)) == 1
    tx2 = reopen_tx(work_dir, bindings)
    assert "obs-A" not in tx2.observations


def test_crash_after_started_before_completion_fails_closed(
        work_dir, bindings):
    r1 = run_driver(work_dir, "--observations", "obs-A",
                    "--crash-point", "after_started:obs-A")
    assert r1.returncode == 1
    wait_for_markers(work_dir, 1)
    assert ledger_record_path(work_dir, "obs-A", "started").exists()

    r2 = run_driver(work_dir, "--observations", "obs-A")
    assert r2.returncode == 2, r2.stdout + r2.stderr
    assert '"fail_closed": true' in r2.stdout
    assert len(marker_nonces(work_dir)) == 1
    # The gate was won in run 1; resume reconciles exactly one contact
    # event for the winner without re-executing the observation.
    assert journal_types(work_dir).count("contact") == 1
    tx2 = reopen_tx(work_dir, bindings)
    assert tx2.contact_event["mutant_id"] == "obs-A"
    assert "obs-A" not in tx2.observations


def test_crash_after_completion_adopts_exact_first_result(
        work_dir, bindings):
    r1 = run_driver(work_dir, "--observations", "obs-A",
                    "--crash-point", "after_completion:obs-A")
    assert r1.returncode == 1
    wait_for_markers(work_dir, 1)
    first_bytes = (work_dir / "artifacts" / "execution_ledger"
                   / "obs-A.outcome.json").read_bytes()
    first_digest = hashlib.sha256(first_bytes).hexdigest()

    r2 = run_driver(work_dir, "--observations", "obs-A")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    rows = _rows(r2)
    assert rows[0]["status"] == "adopted"

    # Zero second execution: still exactly one marker.
    assert len(marker_nonces(work_dir)) == 1
    tx2 = reopen_tx(work_dir, bindings)
    assert tx2.observations["obs-A"] == first_digest
    # Exactly one contact event, naming the winner.
    assert journal_types(work_dir).count("contact") == 1
    assert tx2.contact_event["mutant_id"] == "obs-A"


def test_restart_after_partial_work(work_dir, bindings):
    # obs-A commits fully; obs-B dies after its completion evidence is
    # durable but before the coordinator journals. Resume must skip the
    # committed observation and adopt (never replay) the orphan.
    r1 = run_driver(work_dir, "--observations", "obs-A,obs-B",
                    "--workers", "1",
                    "--crash-point", "after_completion:obs-B")
    assert r1.returncode == 1
    wait_for_markers(work_dir, 2)
    first_b_bytes = (work_dir / "artifacts" / "execution_ledger"
                     / "obs-B.outcome.json").read_bytes()
    first_b_digest = hashlib.sha256(first_b_bytes).hexdigest()

    r2 = run_driver(work_dir, "--observations", "obs-A,obs-B",
                    "--workers", "1")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    rows = _rows(r2)
    by_id = {row["observation_id"]: row["status"] for row in rows
             if "observation_id" in row}
    assert by_id == {"obs-A": "skipped_committed", "obs-B": "adopted"}

    # Neither observation ran again.
    assert len(marker_nonces(work_dir)) == 2
    tx2 = reopen_tx(work_dir, bindings)
    assert tx2.observations["obs-B"] == first_b_digest
    assert "obs-A" in tx2.observations
    assert journal_types(work_dir).count("contact") == 1
