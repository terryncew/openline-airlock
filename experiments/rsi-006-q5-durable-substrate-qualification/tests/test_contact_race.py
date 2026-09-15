"""Concurrency under the single-writer coordinator model.

One coordinator process owns the live ScientificTransaction; its worker
threads race at real process-start/contact (Q3's gate) and return
evidence for the coordinator to journal serially. The test asserts the
Q3 model: exactly one contact winner, exactly one Q4 contact event, a
valid journal, and -- because open() is never used as a
concurrency-refresh primitive -- zero restart entries.

A separate test covers the real coordinator crash: the successor opens
exactly once and the journal gains exactly one restart entry.
"""

from contact import ContactGate

from conftest import (FIXTURE_RECEIPT_SHA256, journal_types,
                      marker_nonces, reopen_tx, run_driver,
                      restart_entry_count)


def test_simultaneous_child_starts_single_contact_single_writer(
        work_dir, bindings):
    # One coordinator, two worker threads, rendezvoused spawns: both
    # children physically start at the same time.
    r = run_driver(work_dir, "--observations", "race-1,race-2",
                   "--workers", "2", "--sync-spawn")
    assert r.returncode == 0, r.stdout + r.stderr

    # Both children physically executed.
    assert len(marker_nonces(work_dir)) == 2
    # Q3's gate decided exactly one winner.
    assert (work_dir / "contact_marker.json").exists()
    # Exactly one Q4 contact event.
    assert journal_types(work_dir).count("contact") == 1
    # Zero restart entries: the coordinator began the journal and never
    # called open() during ordinary operation. Count from the raw
    # journal -- opening here would mint a restart entry itself.
    assert restart_entry_count(work_dir) == 0

    # The reopened journal verifies (open() raises unless the chain,
    # bindings, and artifacts all verify) and names the single winner.
    tx = reopen_tx(work_dir, bindings)
    assert set(tx.observations) == {"race-1", "race-2"}
    assert tx.contact_event is not None
    assert tx.contact_event["mutant_id"] in ("race-1", "race-2")


def test_reconcile_rejournals_won_but_unjournaled_contact(
        work_dir, bindings):
    # The gate was won outside the coordinator (crash between the gate
    # win and the journal append, simulated directly). The next
    # coordinator start must re-journal the winner's marker exactly
    # once, on its single opened instance -- no extra restart entries.
    gate = ContactGate(work_dir / "contact_marker.json")
    gate.note_process_started("external-winner", FIXTURE_RECEIPT_SHA256,
                              424242)

    r = run_driver(work_dir, "--observations", "obs-A", "--workers", "1")
    assert r.returncode == 0, r.stdout + r.stderr

    assert journal_types(work_dir).count("contact") == 1
    tx = reopen_tx(work_dir, bindings)
    assert tx.contact_event["mutant_id"] == "external-winner"
    # The observation itself still ran and committed (it lost the gate,
    # so it journaled no second contact).
    assert "obs-A" in tx.observations
    assert len(marker_nonces(work_dir)) == 1
