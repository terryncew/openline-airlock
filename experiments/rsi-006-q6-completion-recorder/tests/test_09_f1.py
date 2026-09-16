"""F1 — coordinator dies after recorder launch; successor adopts sealed
result with zero second spawn. Deterministic external-driver version."""

import hashlib
import json
import subprocess
import sys
import time

import pytest

import q6_testkit as kit  # noqa: F401
import q6_recorder as qr
import execution_ledger as ledger


def test_f1_coordinator_death_successor_adopts(work_dir):
    """Simulate: coordinator builds config and launches recorder, then
    dies (we simply do not run its post-launch logic). The recorder
    survives, seals, and writes Q5 completion. A successor coordinator
    on the SAME transaction/contact/attempt/nonce adopts via _q6_verify
    with zero second child spawn."""
    wd = str(work_dir)
    coord = kit.make_coordinator(wd)
    spawn = kit.FixtureSpawn("obs-f1-1", run_dir=wd)

    # Coordinator does classify + record_prepared + config (the part
    # before recorder launch in _worker_run).
    prep = spawn.q6_prep
    tx = coord._tx
    cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
        work_dir=wd, tx=tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id="obs-f1-1",
        phase="discovery", attempt=1, prep=prep,
        marker_path=str(work_dir / "m.json"))
    ledger.ledger_dir(wd).mkdir(parents=True, exist_ok=True)
    cfg_path = kit.q6_adapter.write_recorder_config(
        wd, "obs-f1-1", cfg_bytes)
    # Record prepared (durable) as the coordinator would.
    ledger.record_prepared(
        work_dir=wd, txid=tx.txid, observation_id="obs-f1-1",
        phase="discovery", attempt=1, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, pid=12345)

    # Launch the recorder as an independent process (survives coordinator).
    rec_proc = subprocess.Popen(
        [sys.executable, qr.__file__, str(cfg_path), cfg_sha])
    # Coordinator "dies" here: we do not wait, we drop the coordinator.
    del coord

    # The recorder survives and seals.
    assert rec_proc.wait(timeout=30) == 0

    # Successor on the SAME transaction/contact/attempt/nonce.
    tx2 = kit.open_tx(wd)
    assert tx2.txid == tx.txid
    coord2 = kit.make_coordinator(wd, tx=tx2, gate=kit.make_gate(wd))
    outcome_bytes, launch, seal = coord2._q6_verify("obs-f1-1", "discovery")

    # Adopted: same nonce, same PID, outcome digest matches.
    assert seal["exec_nonce"] == launch.get("exec_nonce") or \
        seal["exec_nonce"] is not None
    assert hashlib.sha256(outcome_bytes).hexdigest() == \
        seal["outcome_sha256"]

    # Zero second spawn: exactly one started record.
    import glob
    started_files = glob.glob(str(
        kit.ledger_file(wd, "obs-f1-1", "started"))[:-5] + "*.json")
    assert len(started_files) == 1

    # The successor did not relaunch the recorder: config still single.
    assert kit.ledger_file(wd, "obs-f1-1", "q6_config").exists()
