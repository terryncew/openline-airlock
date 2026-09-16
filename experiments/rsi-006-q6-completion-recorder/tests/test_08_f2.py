"""F2 — recorder dies before seal / seal without Q5 completion: fail closed."""

import json
import subprocess
import sys

import pytest

import q6_testkit as kit  # noqa: F401
import q6_recorder as qr
import execution_ledger as ledger


def _build_halted_config(work_dir, coord, spawn, obs_id):
    """Build a recorder config with halt_after_seal fixture flag."""
    import os
    # The recorder now verifies bindings against the durable prepared
    # record pre-spawn (frozen §7): the fixture must create it, exactly
    # as the coordinator's _q6_scientific_run does.
    ledger.record_prepared(
        work_dir=str(work_dir), txid=coord._tx.txid,
        observation_id=obs_id, phase="discovery", attempt=1,
        receipt_sha256=kit.RECEIPT_SHA, code_hashes=kit.CODE_HASHES,
        pid=os.getpid())
    prep = spawn.q6_prep
    # Inject the halt flag via builder_context (fixture-only seam).
    prep = dict(prep)
    prep["builder_context"] = {"halt_after_seal": True}
    cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
        work_dir=str(work_dir), tx=coord._tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id=obs_id,
        phase="discovery", attempt=1, prep=prep,
        marker_path=str(work_dir / "m.json"))
    cfg = json.loads(cfg_bytes)
    cfg["fixture"] = {"halt_after_seal": True}
    halted = json.dumps(cfg, sort_keys=True).encode("utf-8")
    ledger.ledger_dir(str(work_dir)).mkdir(parents=True, exist_ok=True)
    cfg_path = kit.q6_adapter.write_recorder_config(
        str(work_dir), obs_id, halted)
    return cfg_path, __import__("hashlib").sha256(halted).hexdigest()


def test_f2_recorder_dies_before_seal_no_completion(work_dir, explicit_env):
    """Recorder halts after seal write but before Q5 completion: the
    outcome/launch/seal exist but completion does not. A successor must
    NOT adopt — it must fail closed with UncertainExecution."""
    coord = kit.make_coordinator(str(work_dir))
    spawn = kit.FixtureSpawn("obs-f2-1", run_dir=str(work_dir))
    cfg_path, cfg_sha = _build_halted_config(
        work_dir, coord, spawn, "obs-f2-1")
    # Run the recorder directly (simulating the halt).
    r = subprocess.run(
        [sys.executable, qr.__file__, str(cfg_path), cfg_sha],
        capture_output=True, text=True)
    # The halt flag causes a non-zero exit after seal (fixture seam).
    assert r.returncode != 0
    # Seal exists, completion does not.
    assert kit.ledger_file(str(work_dir), "obs-f2-1", "q6_seal").exists()
    assert not kit.ledger_file(
        str(work_dir), "obs-f2-1", "complete").exists()
    # A successor verifying must fail closed: seal without Q5 completion
    # is UncertainExecution, zero adoption.
    coord2 = kit.make_coordinator(
        str(work_dir), tx=kit.open_tx(str(work_dir)),
        gate=kit.make_gate(str(work_dir)))
    with pytest.raises(ledger.UncertainExecution):
        coord2._q6_verify("obs-f2-1", "discovery")


def test_f2_seal_without_q5_completion_fails_closed(work_dir, explicit_env):
    """A forged seal (no Q5 completion record) fails verification."""
    coord = kit.make_coordinator(str(work_dir))
    spawn = kit.FixtureSpawn("obs-f2-2", run_dir=str(work_dir))
    result = kit.run_fixture(coord, spawn)
    assert result["result"] == "completed"
    # Delete the Q5 completion; the seal remains.
    kit.ledger_file(str(work_dir), "obs-f2-2", "complete").unlink()
    with pytest.raises(ledger.UncertainExecution):
        coord._q6_verify("obs-f2-2", "discovery")
