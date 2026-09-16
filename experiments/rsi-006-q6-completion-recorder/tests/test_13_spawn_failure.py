"""Real spawn-failure test: Popen raises OSError, Q6 records it correctly.

Uses the REAL frozen builders (run_rsi_006_q5.build_q3_spawn_failure)
and the REAL frozen ledger (record_spawn_failed). The child argv points
to a nonexistent executable, so Popen raises FileNotFoundError (an
OSError) -- a genuine spawn failure, not a mocked one.

Requires:
- zero child created (no started record);
- zero contact (no ContactGate marker);
- spawn_failed exists with attempt and error string;
- canonical spawn-failure outcome produced;
- Q6 durable completion boundary reached (outcome -> launch -> seal
  -> completion LAST);
- seal exec_nonce is null, child_pid is null;
- ordinary coordinator commit path succeeds.
"""

import os
import subprocess
import sys
from pathlib import Path

import q6_testkit as kit
import q6_recorder as qr
import execution_ledger as ledger


def test_real_spawn_failure(work_dir, explicit_env):
    wd = str(work_dir)
    obs_id = "obs-spawnfail-1"

    tx = kit.make_tx(wd)
    coord = kit.make_coordinator(wd, tx=tx)
    # Nonexistent executable: Popen raises FileNotFoundError (OSError).
    spawn = kit.FixtureSpawn(
        obs_id, run_dir=wd,
        child_argv=["/nonexistent/q6-fixture-binary-xyz"],
        timeout_s=30)
    spawn.q6_prep["builder"] = "run_rsi_006_q5.build_q3_completion"
    spawn.q6_prep["spawn_failure_builder"] = \
        "run_rsi_006_q5.build_q3_spawn_failure"
    spawn.q6_prep["mutant"] = {
        "mutant_id": "fixture-mutant-1",
        "operator": "fixture-op",
        "site_key": "fixture-site",
        "seed": 42,
    }

    # Run through the ordinary coordinator path.
    result = kit.run_fixture(coord, spawn)
    assert result["result"] == "completed", \
        f"spawn failure should complete (as Q3 scored observation): {result}"

    ldir = ledger.ledger_dir(wd)
    # Zero child: no started record.
    assert not (ldir / f"{obs_id}.started.json").exists(), \
        "spawn failure must not create a started record"
    # Zero contact: ContactGate never crossed.
    assert not (work_dir / "contact_marker.json").exists(), \
        "spawn failure must not cross ContactGate"
    # spawn_failed exists with the frozen signature fields.
    failed_path = ldir / f"{obs_id}.spawn_failed.json"
    assert failed_path.exists(), "spawn_failed record missing"
    failed = kit.read_json(failed_path)
    assert failed["attempt"] == 1
    assert "FileNotFoundError" in failed["error"], \
        f"error should name the exception: {failed['error']}"

    # Q6 durable boundary reached: outcome -> launch -> seal -> completion.
    for name in ("outcome", "q6_launch", "q6_seal", "complete"):
        assert (ldir / f"{obs_id}.{name}.json").exists(), \
            f"missing {name} after spawn failure"
    seal = kit.read_json(ldir / f"{obs_id}.q6_seal.json")
    assert seal["disposition"] == "spawn-failure"
    assert seal["exec_nonce"] is None, "spawn-failure seal nonce must be null"
    assert seal["child_pid"] is None, "spawn-failure seal pid must be null"

    # Ordinary commit path: the coordinator can commit this.
    applied = coord._apply(result)
    assert applied["status"] == "committed", \
        f"spawn failure should commit normally: {applied}"
