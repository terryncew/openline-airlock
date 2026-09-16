"""Q6 seal/sidecar verification: the evidence chain binds."""

import sys

import pytest

import q6_testkit as kit  # noqa: F401


@pytest.fixture
def completed(work_dir, explicit_env):
    """Run one fixture observation to a sealed completion."""
    coord = kit.make_coordinator(work_dir)
    spawn = kit.FixtureSpawn("obs-verify-1", run_dir=work_dir)
    result = kit.run_fixture(coord, spawn)
    assert result["result"] == "completed"
    return coord, spawn, result


def test_verify_accepts_sealed_chain(completed, explicit_env):
    coord, spawn, result = completed
    outcome_bytes, launch, seal = coord._q6_verify(
        "obs-verify-1", "discovery")
    assert outcome_bytes == result["outcome_bytes"]
    assert launch == result["launch"]
    assert seal["contact_created"] is True
    assert seal["child_pid"] == result["child_pid"]
    assert seal["exec_nonce"] == result["exec_nonce"]


def test_seal_binds_config_and_sidecar(completed, work_dir):
    import hashlib
    coord, spawn, result = completed
    seal = kit.read_json(kit.ledger_file(work_dir, "obs-verify-1", "q6_seal"))
    sidecar_raw = kit.ledger_file(
        work_dir, "obs-verify-1", "q6_launch").read_bytes()
    config_raw = kit.ledger_file(
        work_dir, "obs-verify-1", "q6_config").read_bytes()
    assert seal["launch_sha256"] == hashlib.sha256(sidecar_raw).hexdigest()
    assert seal["config_sha256"] == hashlib.sha256(config_raw).hexdigest()
    assert seal["outcome_sha256"] == hashlib.sha256(
        result["outcome_bytes"]).hexdigest()


def test_durable_order_outcome_launch_seal_completion(completed, work_dir):
    import os
    names = ["outcome", "q6_launch", "q6_seal", "complete"]
    mtimes = [os.stat(kit.ledger_file(work_dir, "obs-verify-1", n)).st_mtime_ns
              for n in names]
    assert mtimes == sorted(mtimes), "sealed order violated"
    # started precedes all of them.
    started_mtime = os.stat(kit.ledger_file(
        work_dir, "obs-verify-1", "started")).st_mtime_ns
    assert started_mtime < mtimes[0]
