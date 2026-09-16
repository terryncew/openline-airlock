"""F3 — forged/misbound recorder evidence: fail closed, zero adoption."""

import hashlib
import json
import subprocess
import sys

import pytest

import q6_testkit as kit  # noqa: F401
import q6_recorder as qr


@pytest.fixture
def sealed(work_dir):
    """A sealed fixture observation; returns (coord, work_dir, obs_id)."""
    coord = kit.make_coordinator(str(work_dir))
    spawn = kit.FixtureSpawn("obs-f3-1", run_dir=str(work_dir))
    result = kit.run_fixture(coord, spawn)
    assert result["result"] == "completed"
    return coord, str(work_dir), "obs-f3-1"


def _tamper(work_dir, obs_id, name, mutate):
    p = kit.ledger_file(work_dir, obs_id, name)
    rec = json.loads(p.read_bytes())
    mutate(rec)
    p.write_bytes(json.dumps(rec, sort_keys=True).encode("utf-8"))


def test_f3_wrong_txid(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal", lambda r: r.update(txid="tx-forged"))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_wrong_observation_id(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal",
            lambda r: r.update(observation_id="obs-forged"))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_wrong_phase(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal", lambda r: r.update(phase="forged"))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_wrong_attempt(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal", lambda r: r.update(attempt=999))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_wrong_receipt_sha(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal",
            lambda r: r.update(receipt_sha256="f" * 64))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_wrong_code_hashes(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal",
            lambda r: r.update(code_hashes={"forged": "x"}))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_wrong_nonce(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal",
            lambda r: r.update(exec_nonce="0" * 64))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_changed_outcome_bytes(sealed):
    coord, wd, oid = sealed
    p = kit.ledger_file(wd, oid, "outcome")
    p.write_bytes(b'{"forged": true}')
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_seal_outcome_digest_mismatch(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_seal",
            lambda r: r.update(outcome_sha256="0" * 64))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_sidecar_tamper(sealed):
    coord, wd, oid = sealed
    _tamper(wd, oid, "q6_launch",
            lambda r: r["launch"].update(child_pid=999999))
    with pytest.raises(Exception):
        coord._q6_verify(oid, "discovery")


def test_f3_config_argv_tamper_refuses_before_spawn(work_dir):
    """Changed child argv in the config: recorder refuses, zero spawn."""
    import execution_ledger as ledger
    coord = kit.make_coordinator(str(work_dir))
    spawn = kit.FixtureSpawn("obs-f3-arg", run_dir=str(work_dir))
    # Build the config, then tamper the argv bytes before launch.
    prep = spawn.q6_prep
    cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
        work_dir=str(work_dir), tx=coord._tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id="obs-f3-arg",
        phase="discovery", attempt=1, prep=prep,
        marker_path=str(work_dir / "m.json"))
    cfg = json.loads(cfg_bytes)
    cfg["child_argv"] = [sys.executable, "-c", "import os; os._exit(42)"]
    tampered = json.dumps(cfg, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False).encode("utf-8")
    ledger.ledger_dir(str(work_dir)).mkdir(parents=True, exist_ok=True)
    cfg_path = kit.q6_adapter.write_recorder_config(
        str(work_dir), "obs-f3-arg", tampered)
    # The sha passed in argv is for the ORIGINAL bytes; tampered bytes
    # must be refused.
    r = subprocess.run(
        [sys.executable, qr.__file__, str(cfg_path), cfg_sha],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "refusing" in r.stderr
    # Zero scientific child spawn: no started record.
    assert not kit.ledger_file(
        str(work_dir), "obs-f3-arg", "started").exists()
