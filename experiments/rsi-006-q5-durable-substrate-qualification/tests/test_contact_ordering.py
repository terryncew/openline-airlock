"""Durable contact-ordering falsifier (pre-contact).

The coordinator must journal the ContactGate winner's contact event
into Q4 BEFORE any observation/adoption entry from the same batch is
committed -- otherwise the durable provenance reads
observation-before-authorization.

Deterministic, not a repeated race: A and B rendezvous at the spawn
barrier; A's spawn path sleeps 2s after the rendezvous while B spawns
immediately, so B always wins the gate while A stays first in the
coordinator's dispatch/apply order.
"""

import json

from conftest import (journal_types, marker_nonces, reopen_tx, run_driver,
                      restart_entry_count)


def _done_results(stdout: str) -> list:
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if payload.get("done"):
            return payload["results"]
    raise AssertionError("no done line in driver output")


def test_contact_journaled_before_observations(work_dir, bindings):
    r = run_driver(work_dir, "--observations", "obs-A,obs-B",
                   "--workers", "2", "--sync-spawn",
                   "--delay-spawn-for", "obs-A:2")
    assert r.returncode == 0, r.stdout + r.stderr
    results = _done_results(r.stdout)

    # Both children really executed; apply order is dispatch order
    # (A first) while B deterministically won the gate.
    assert len(marker_nonces(work_dir)) == 2
    assert [row["observation_id"] for row in results] == ["obs-A", "obs-B"]
    assert results[0]["status"] == "committed"
    assert results[1]["status"] == "committed"
    assert results[0]["contact_created"] is False
    assert results[1]["contact_created"] is True

    # Exactly one Q3 gate winner, exactly one Q4 contact entry.
    assert sum(1 for row in results if row["contact_created"]) == 1
    types = journal_types(work_dir)
    assert types.count("contact") == 1

    # The contact entry precedes every observation/adoption entry:
    # durable provenance must read authorization-before-observation.
    contact_pos = types.index("contact")
    obs_positions = [i for i, t in enumerate(types)
                     if t in ("observation", "observation_adopted")]
    assert obs_positions, f"expected observation entries: {types}"
    assert all(contact_pos < p for p in obs_positions), types

    # No restart entries for an uninterrupted run.
    assert restart_entry_count(work_dir) == 0

    # The journal verifies normally afterward.
    tx = reopen_tx(work_dir, bindings)
    assert set(tx.observations) == {"obs-A", "obs-B"}
    assert tx.contact_event["mutant_id"] == "obs-B"
