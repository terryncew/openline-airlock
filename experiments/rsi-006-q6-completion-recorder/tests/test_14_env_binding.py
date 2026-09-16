"""Environment binding: drift causes zero child spawn.

Proves the earned rule: Q6 binds the ACTUAL prepared environment, not
a required 80x24. If the recorder's inherited env differs from the
prepared digest, it refuses BEFORE spawning the child (fail-closed).

Two cases:
1. Matching env: recorder runs the child normally.
2. Drifted env: recorder refuses (exit 3), no child spawned, no
   started record, no contact.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import q6_testkit as kit
import q6_recorder as qr
import execution_ledger as ledger


def _build_config(work_dir, obs_id, columns, lines):
    """Build a recorder config with explicit COLUMNS/LINES in prep."""
    old_c, old_l = os.environ.get("COLUMNS"), os.environ.get("LINES")
    os.environ["COLUMNS"] = str(columns)
    os.environ["LINES"] = str(lines)
    try:
        tx = kit.make_tx(str(work_dir))
        coord = kit.make_coordinator(str(work_dir), tx=tx)
        spawn = kit.FixtureSpawn(obs_id, run_dir=str(work_dir))
        prep = spawn.q6_prep
        cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
            work_dir=str(work_dir), tx=tx, receipt_sha256=kit.RECEIPT_SHA,
            code_hashes=kit.CODE_HASHES, observation_id=obs_id,
            phase="discovery", attempt=1, prep=prep,
            marker_path=str(work_dir / "m.json"))
        ledger.ledger_dir(str(work_dir)).mkdir(parents=True, exist_ok=True)
        cfg_path = kit.q6_adapter.write_recorder_config(
            str(work_dir), obs_id, cfg_bytes)
        ledger.record_prepared(
            work_dir=str(work_dir), txid=tx.txid, observation_id=obs_id,
            phase="discovery", attempt=1, receipt_sha256=kit.RECEIPT_SHA,
            code_hashes=kit.CODE_HASHES, pid=os.getpid())
        return cfg_path, cfg_sha
    finally:
        if old_c is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = old_c
        if old_l is None:
            os.environ.pop("LINES", None)
        else:
            os.environ["LINES"] = old_l


def test_env_match_runs_child(work_dir, explicit_env):
    """Matching env: recorder spawns the child and seals."""
    cfg_path, cfg_sha = _build_config(work_dir, "obs-env-ok", 80, 24)
    # Env matches the prep (80/24 set by explicit_env fixture).
    proc = subprocess.Popen(
        [sys.executable, qr.__file__, str(cfg_path), cfg_sha])
    assert proc.wait(timeout=30) == 0, "recorder should accept matching env"
    assert kit.ledger_file(
        str(work_dir), "obs-env-ok", "complete").exists()


def test_env_drift_refuses_zero_spawn(work_dir, explicit_env):
    """Drifted env: recorder refuses BEFORE child spawn.

    Prep was captured with COLUMNS=80/LINES=24. The recorder is launched
    with different values: it must refuse (exit 3) with zero child
    spawn -- no started record, no contact, no completion.
    """
    cfg_path, cfg_sha = _build_config(work_dir, "obs-env-drift", 80, 24)
    # Drift the env: different values than prep captured.
    env = dict(os.environ)
    env["COLUMNS"] = "137"
    env["LINES"] = "51"
    proc = subprocess.Popen(
        [sys.executable, qr.__file__, str(cfg_path), cfg_sha],
        env=env, stderr=subprocess.PIPE)
    _, stderr = proc.communicate(timeout=30)
    assert proc.returncode == 3, \
        f"recorder should refuse on env drift, got {proc.returncode}"
    assert b"prepared environment digest mismatch" in stderr

    # Zero scientific child spawn: no started, no contact, no completion.
    ldir = ledger.ledger_dir(str(work_dir))
    assert not (ldir / "obs-env-drift.started.json").exists(), \
        "drift must not spawn a child"
    assert not (work_dir / "contact_marker.json").exists(), \
        "drift must not cross ContactGate"
    assert not (ldir / "obs-env-drift.complete.json").exists(), \
        "drift must not complete"
