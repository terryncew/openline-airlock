"""Byte-exact builder test: non-UTF-8 stdout/stderr through the real
frozen Q3 builder.

The Q6 recorder must pass exact bytes (not lossy-decoded str) to the
frozen builder. This test uses the REAL
run_rsi_006_q5.build_q3_completion (not fixture_builders) with a child
that emits non-UTF-8 bytes, and requires the launch record to preserve
exact SHA-256, length, and base64 of the raw bytes.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import q6_testkit as kit
import q6_recorder as qr
import execution_ledger as ledger

# Non-UTF-8 bytes: invalid sequences that would be mangled by
# decode("utf-8", "replace").
RAW_STDOUT = b"ok\xff\xfenot-utf8\x80end\n"
RAW_STDERR = b"err\xc3(\x00binary\x01\n"


def _write_child_script(path):
    path.write_text(
        "import os, sys\n"
        f"os.write(1, {RAW_STDOUT!r})\n"
        f"os.write(2, {RAW_STDERR!r})\n",
        encoding="utf-8")


def _write_junit(path):
    # Minimal valid JUnit XML for the real Q3 parser.
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuite name="fixture" tests="1">\n'
        '  <testcase classname="t" name="test_ok"/>\n'
        '</testsuite>\n',
        encoding="utf-8")


def test_byte_exact_builder(work_dir, explicit_env):
    """Non-UTF-8 bytes survive Q6 -> real Q3 builder byte-exact."""
    wd = str(work_dir)
    obs_id = "obs-bytes-1"
    child_script = work_dir / "byte_child.py"
    _write_child_script(child_script)
    junit_path = work_dir / "junit.xml"
    _write_junit(junit_path)

    tx = kit.make_tx(wd)
    coord = kit.make_coordinator(wd, tx=tx)
    # Use the REAL frozen Q3 builder, not the fixture builder.
    spawn = kit.FixtureSpawn(
        obs_id, run_dir=wd,
        child_argv=[sys.executable, str(child_script)],
        timeout_s=30)
    spawn.q6_prep["builder"] = "run_rsi_006_q5.build_q3_completion"
    spawn.q6_prep["spawn_failure_builder"] = \
        "run_rsi_006_q5.build_q3_spawn_failure"
    # The real builder needs full mutant fields.
    spawn.q6_prep["mutant"] = {
        "mutant_id": "fixture-mutant-1",
        "operator": "fixture-op",
        "site_key": "fixture-site",
        "seed": 42,
    }
    spawn.q6_prep["junit_path"] = str(junit_path)

    # Build and run the recorder directly (bypassing coordinator Popen
    # so we can inspect the launch record).
    prep = spawn.q6_prep
    cfg_bytes, cfg_sha = kit.q6_adapter.build_recorder_config(
        work_dir=wd, tx=tx, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, observation_id=obs_id,
        phase="discovery", attempt=1, prep=prep,
        marker_path=str(work_dir / "m.json"))
    ledger.ledger_dir(wd).mkdir(parents=True, exist_ok=True)
    cfg_path = kit.q6_adapter.write_recorder_config(wd, obs_id, cfg_bytes)
    ledger.record_prepared(
        work_dir=wd, txid=tx.txid, observation_id=obs_id,
        phase="discovery", attempt=1, receipt_sha256=kit.RECEIPT_SHA,
        code_hashes=kit.CODE_HASHES, pid=os.getpid())

    proc = subprocess.Popen(
        [sys.executable, qr.__file__, str(cfg_path), cfg_sha])
    assert proc.wait(timeout=30) == 0, "recorder failed"

    # The launch sidecar must preserve byte-exact stdout/stderr.
    launch_rec = kit.read_json(kit.ledger_file(wd, obs_id, "q6_launch"))
    launch = launch_rec["launch"]
    for name, raw in (("stdout", RAW_STDOUT), ("stderr", RAW_STDERR)):
        enc = launch[name]
        assert enc["sha256"] == hashlib.sha256(raw).hexdigest(), \
            f"{name} sha256 mismatch: lossy decode detected"
        assert enc["len"] == len(raw), f"{name} length mismatch"
        assert base64.b64decode(enc["bytes_b64"]) == raw, \
            f"{name} base64 round-trip mismatch"
        # The lossy text field exists for humans; the bytes_b64 is the
        # evidence. If the recorder had decoded lossily, sha256 would
        # not match (proven above).
