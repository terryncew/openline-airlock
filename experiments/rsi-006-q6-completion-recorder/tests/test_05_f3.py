"""F3 — forged/misbound recorder evidence: fail closed, zero adoption."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import q6_testkit as kit  # noqa: F401
import q6_recorder as qr


@pytest.fixture
def sealed(work_dir, explicit_env):
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


def test_f3_config_argv_tamper_refuses_before_spawn(work_dir, explicit_env):
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


# --- Pre-spawn binding matrix (frozen §7): the forged config is
# internally valid and its SHA in argv is recomputed, so only the
# durable-prepared cross-check can refuse. Every case must fail BEFORE
# any scientific Popen: zero spawn, no started, no contact.


def _forged_run(work_dir, obs_id, mutate):
    """Legitimate prepared record + forged config; run recorder directly."""
    import execution_ledger as ledger
    wd = str(work_dir)
    coord = kit.make_coordinator(wd)
    tx = coord._tx
    phase, attempt = "discovery", 1
    ledger.record_prepared(
        work_dir=wd, txid=tx.txid, observation_id=obs_id,
        phase=phase, attempt=attempt, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, pid=12345)
    canary = Path(wd) / f"{obs_id}.canary"
    spawn = kit.FixtureSpawn(
        obs_id, run_dir=wd,
        child_argv=[sys.executable, "-c",
                    f"import pathlib; pathlib.Path(r'{canary}')"
                    ".write_text('spawned')"])
    cfg_bytes, _ = kit.q6_adapter.build_recorder_config(
        work_dir=wd, tx=tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id=obs_id,
        phase=phase, attempt=attempt, prep=spawn.q6_prep,
        marker_path=str(Path(wd) / f"{obs_id}.m.json"))
    cfg = json.loads(cfg_bytes)
    mutate(cfg)
    # Frozen serialization; the argv SHA matches the forged bytes, so
    # the config-digest check alone cannot save us.
    forged = json.dumps(cfg, sort_keys=True).encode("utf-8")
    forged_sha = hashlib.sha256(forged).hexdigest()
    cfg_path = ledger.ledger_dir(wd) / f"{obs_id}.q6_config.json"
    cfg_path.write_bytes(forged)
    r = subprocess.run(
        [sys.executable, qr.__file__, str(cfg_path), forged_sha],
        capture_output=True, text=True)
    return r, canary, cfg


def _assert_prespawn_refusal(work_dir, obs_id, r, canary, cfg):
    assert r.returncode != 0, f"recorder did not refuse: {r.stderr}"
    assert "refusing" in r.stderr
    assert "prepared" in r.stderr
    # Zero scientific Popen: the canary child never ran.
    assert not canary.exists(), "scientific child was spawned"
    # No started record under either the real or forged observation id.
    for oid in {obs_id, cfg["observation_id"]}:
        assert not kit.ledger_file(
            str(work_dir), oid, "started").exists()
        assert not kit.ledger_file(
            str(work_dir), oid, "complete").exists()
    # No contact: the gate marker was never created.
    assert not Path(cfg["gate_marker_path"]).exists()


def test_f3_prespawn_wrong_txid(work_dir, explicit_env):
    r, canary, cfg = _forged_run(
        work_dir, "obs-f3p-txid", lambda c: c.update(txid="tx-forged"))
    _assert_prespawn_refusal(work_dir, "obs-f3p-txid", r, canary, cfg)


def test_f3_prespawn_wrong_observation_id(work_dir, explicit_env):
    r, canary, cfg = _forged_run(
        work_dir, "obs-f3p-obs",
        lambda c: c.update(observation_id="obs-forged"))
    _assert_prespawn_refusal(work_dir, "obs-f3p-obs", r, canary, cfg)


def test_f3_prespawn_wrong_phase(work_dir, explicit_env):
    r, canary, cfg = _forged_run(
        work_dir, "obs-f3p-phase", lambda c: c.update(phase="forged"))
    _assert_prespawn_refusal(work_dir, "obs-f3p-phase", r, canary, cfg)


def test_f3_prespawn_wrong_attempt(work_dir, explicit_env):
    r, canary, cfg = _forged_run(
        work_dir, "obs-f3p-attempt", lambda c: c.update(attempt=999))
    _assert_prespawn_refusal(work_dir, "obs-f3p-attempt", r, canary, cfg)


def test_f3_prespawn_wrong_receipt_sha(work_dir, explicit_env):
    r, canary, cfg = _forged_run(
        work_dir, "obs-f3p-receipt",
        lambda c: c.update(receipt_sha256="f" * 64))
    _assert_prespawn_refusal(work_dir, "obs-f3p-receipt", r, canary, cfg)


def test_f3_prespawn_wrong_code_hashes(work_dir, explicit_env):
    r, canary, cfg = _forged_run(
        work_dir, "obs-f3p-codes",
        lambda c: c.update(code_hashes={"forged": "x"}))
    _assert_prespawn_refusal(work_dir, "obs-f3p-codes", r, canary, cfg)
