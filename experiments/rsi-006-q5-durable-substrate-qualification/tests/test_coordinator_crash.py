"""Coordinator crash/resume: one open, one restart entry, no replays.

Kills the coordinator process after partial durable progress, resumes
in a fresh process, and asserts the single-writer contract:

- the successor calls ``ScientificTransaction.open()`` exactly once;
- the journal gains exactly one ``restart`` entry (no false restart
  provenance from contention-time re-opens);
- committed observations are skipped;
- any observation with uncertain execution state is never replayed.
"""

from conftest import (journal_types, marker_nonces, reopen_tx, run_driver,
                      restart_entry_count, wait_for_markers)


def test_coordinator_crash_resume_single_restart_entry(work_dir, bindings):
    # Run 1 (one coordinator, sequential workers): obs-A commits fully;
    # the coordinator dies after obs-B's started record is durable but
    # before its completion evidence exists.
    r1 = run_driver(work_dir, "--observations", "obs-A,obs-B",
                    "--workers", "1",
                    "--crash-point", "after_started:obs-B")
    assert r1.returncode == 1  # os._exit(1): the injected crash
    # Both children physically spawned (obs-B's is the orphan).
    wait_for_markers(work_dir, 2)
    # The journal was begun and never opened: zero restart entries.
    assert restart_entry_count(work_dir) == 0

    # Resume in a fresh process. begin_or_open calls open() exactly
    # once; the coordinator never re-opens during the run.
    r2 = run_driver(work_dir, "--observations", "obs-A,obs-B",
                    "--workers", "1")
    assert r2.returncode == 2, r2.stdout + r2.stderr  # fail closed
    assert '"fail_closed": true' in r2.stdout

    # Exactly one restart entry for the one genuine resume.
    assert restart_entry_count(work_dir) == 1
    # Zero second execution: no new markers for either observation.
    assert len(marker_nonces(work_dir)) == 2
    # Committed work skipped; uncertain work never replayed.
    tx = reopen_tx(work_dir, bindings)
    assert "obs-A" in tx.observations
    assert "obs-B" not in tx.observations
    # The contact ledger is intact: exactly one contact, the winner.
    assert journal_types(work_dir).count("contact") == 1
    assert tx.contact_event["mutant_id"] == "obs-A"
