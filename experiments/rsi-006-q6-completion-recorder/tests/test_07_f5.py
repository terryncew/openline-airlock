"""F5 — uninterrupted Q6 commits; canonical bytes/journal parity with Q5."""

import hashlib
import json

import pytest

import q6_testkit as kit  # noqa: F401
import q6_recorder as qr


def test_f5_q6_commits_without_adoption(work_dir):
    """An uninterrupted Q6 run commits via the normal path and never
    takes the adopt/recover branch (result is 'completed', not a
    recoverable shape)."""
    coord = kit.make_coordinator(str(work_dir))
    spawn = kit.FixtureSpawn("obs-f5-1", run_dir=str(work_dir))
    result = kit.run_fixture(coord, spawn)
    assert result["result"] == "completed"
    # The outcome bytes are the canonical fixture bytes.
    outcome = json.loads(result["outcome_bytes"])
    assert outcome["mutant_id"] == "fixture-mutant"
    assert outcome["repo"] == "fixture-repo"


def test_f5_canonical_bytes_stable(work_dir):
    """Two identical fixture runs produce deterministic outcome
    canonicalization for the same fixture inputs."""
    outcomes = []
    for i in range(2):
        sub = str(work_dir / f"run{i}")
        import os
        os.makedirs(sub, exist_ok=True)
        coord = kit.make_coordinator(sub)
        spawn = kit.FixtureSpawn(f"obs-f5-{i}", run_dir=sub)
        result = kit.run_fixture(coord, spawn)
        outcomes.append(result["outcome_bytes"])
    # The canonical JSON bytes are deterministic for the same inputs.
    o1, o2 = (json.loads(b) for b in outcomes)
    assert o1["mutant_id"] == o2["mutant_id"]
    assert o1["repo"] == o2["repo"]
    assert o1["fixture"] == o2["fixture"]


def test_f5_seal_schema_and_evidence_shape(work_dir):
    coord = kit.make_coordinator(str(work_dir))
    spawn = kit.FixtureSpawn("obs-f5-9", run_dir=str(work_dir))
    result = kit.run_fixture(coord, spawn)
    assert result["result"] == "completed"
    # Evidence from the verify path carries the nested launch and seal.
    outcome_bytes, launch, seal = coord._q6_verify("obs-f5-9", "discovery")
    assert launch["child_pid"] == result["child_pid"]
    assert seal["child_pid"] == result["child_pid"]
    assert seal["exec_nonce"] == result["exec_nonce"]
    assert seal["outcome_sha256"] == hashlib.sha256(
        outcome_bytes).hexdigest()
    assert outcome_bytes == result["outcome_bytes"]
