"""RSI-005 harness-qualification contract tests.

These tests bind the earned repair from RSI-004 and the qualification
stage's safety properties:

* build_fixture() creates state_dir (the RSI-004 root cause is gone), and
  the old missing-directory condition is proven to have failed.
* The primary-contact marker is written only at the real Nightshift-entry
  choke point; qualification cannot create it.
* run_nightshift is reachable only through nightshift_entry(); the
  qualification path cannot call it.
* A real fresh-process child crosses the token-gated boundary and reaches
  PRE_NIGHTSHIFT_BOUNDARY with zero Nightshift contact, zero candidate
  execution, and no marker.
* Negative paths fail closed: missing state_dir, invalid token.

Nothing here contacts Nightshift or executes a candidate.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
RUNNER = EXP_DIR / "run_rsi_005.py"
SOURCE = RUNNER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

sys.path.insert(0, str(EXP_DIR))
import run_rsi_005 as r5  # noqa: E402


def _func_node(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found in run_rsi_005.py")


def _names_in(func: ast.FunctionDef) -> set[str]:
    return {n.id for n in ast.walk(func) if isinstance(n, ast.Name)}


def _calls_in(func: ast.FunctionDef, callee: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == callee
    ]


# ---------------------------------------------------------------------------
# 1. The earned repair: state_dir creation
# ---------------------------------------------------------------------------


def test_state_dir_created_by_build_fixture():
    """Regression for the exact RSI-004 failure: build_fixture() must create
    state_dir before returning, so the phase-token write has a directory."""
    root = Path(tempfile.mkdtemp(prefix="rsi-005-test-"))
    try:
        state = r5.build_fixture(root)
        state_dir = Path(state["state_dir"])
        assert state_dir.is_dir(), "build_fixture did not create state_dir"

        token = r5.write_phase_token(state_dir)
        assert (state_dir / ".phase_token").read_text(encoding="utf-8").strip() == token
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_rsi004_missing_directory_condition_would_fail():
    """Prove the old RSI-004 condition (recorded but uncreated state_dir)
    would have failed: writing the token with no parent directory raises
    FileNotFoundError, exactly the frozen RSI-004 crash."""
    root = Path(tempfile.mkdtemp(prefix="rsi-005-test-"))
    try:
        missing = root / "state"  # recorded by old code, never created
        assert not missing.exists()
        with pytest.raises(FileNotFoundError):
            (missing / ".phase_token").write_text("x" * 64, encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_negative_state_dir_removed_before_token_write_fails_closed():
    """Negative path: if state_dir is removed before token creation, the
    harness fails closed instead of proceeding silently."""
    root = Path(tempfile.mkdtemp(prefix="rsi-005-test-"))
    try:
        state = r5.build_fixture(root)
        state_dir = Path(state["state_dir"])
        shutil.rmtree(state_dir)
        with pytest.raises(FileNotFoundError):
            r5.write_phase_token(state_dir)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 2. Token-gated child boundary, negative token path
# ---------------------------------------------------------------------------


def test_negative_invalid_token_child_refused():
    """A child launched without the orchestrator's token (or with a wrong
    one) cannot cross the internal boundary: non-zero exit, no probe
    result. Neither case touches Nightshift or a candidate."""
    root = Path(tempfile.mkdtemp(prefix="rsi-005-test-"))
    try:
        state = r5.build_fixture(root)
        state_dir = Path(state["state_dir"])
        r5.write_phase_token(state_dir)
        state_path = root / "state.json"
        for bad_env in ({}, {r5.PHASE_TOKEN_ENV: "0" * 64}):
            env = dict(os.environ)
            env.pop(r5.PHASE_TOKEN_ENV, None)
            env.update(bad_env)
            env[r5.PARENT_PID_ENV] = str(os.getpid())
            cp = subprocess.run(
                [sys.executable, str(RUNNER), "--internal-probe", "--state", str(state_path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            assert cp.returncode != 0, "child crossed the boundary with a bad token"
            assert not (state_dir / "probe_result.json").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. Marker alignment: marker only at the real Nightshift-entry choke point
# ---------------------------------------------------------------------------


def test_marker_written_only_in_nightshift_entry():
    """PRIMARY_CONTACT_MARKER may be written in exactly one place:
    nightshift_entry(), immediately before the Nightshift path. Marker
    creation and Nightshift contact are the same event by construction."""
    writers = [
        n
        for n in ast.walk(TREE)
        if isinstance(n, ast.Attribute)
        and n.attr == "write_text"
        and isinstance(n.value, ast.Name)
        and n.value.id == "PRIMARY_CONTACT_MARKER"
    ]
    assert len(writers) == 1, f"expected exactly one marker write site, found {len(writers)}"
    entry = _func_node("nightshift_entry")
    assert any(w in ast.walk(entry) for w in writers), (
        "the marker write is not inside nightshift_entry()"
    )


def _marker_writes_in(func: ast.FunctionDef) -> list[ast.Attribute]:
    return [
        n
        for n in ast.walk(func)
        if isinstance(n, ast.Attribute)
        and n.attr == "write_text"
        and isinstance(n.value, ast.Name)
        and n.value.id == "PRIMARY_CONTACT_MARKER"
    ]


def test_qualification_cannot_create_marker():
    """AST: neither qualify_harness() nor internal_probe() may WRITE the
    primary-contact marker. (Reading its absence to prove it stays absent
    is required and allowed.)"""
    for name in ("qualify_harness", "internal_probe"):
        func = _func_node(name)
        assert not _marker_writes_in(func), (
            f"{name}() can write the primary-contact marker"
        )


def test_all_nightshift_through_choke_point():
    """AST: run_nightshift() is called in exactly one place in the module —
    inside nightshift_entry(). Every future scientific Nightshift path must
    go through that choke point."""
    calls = [
        n
        for n in ast.walk(TREE)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "run_nightshift"
    ]
    assert len(calls) == 1, f"expected exactly one run_nightshift call site, found {len(calls)}"
    entry = _func_node("nightshift_entry")
    assert any(c in ast.walk(entry) for c in calls), (
        "the run_nightshift call is not inside nightshift_entry()"
    )


def test_qualification_path_cannot_call_run_nightshift():
    """AST: the qualification and probe paths contain no run_nightshift
    call and no shim-execution helper."""
    for name in ("qualify_harness", "internal_probe", "_dispatch_probe"):
        func = _func_node(name)
        assert not _calls_in(func, "run_nightshift"), f"{name}() can call run_nightshift"


def test_no_candidate_execution_machinery_in_runner():
    """The harness-qualification runner has no shim constants and no helper
    that executes a candidate; candidate execution is structurally
    impossible in this stage."""
    for const in ("ROOTU_SHIM", "GEN1_SHIM", "GEN2_SHIM", "GEN3_SHIM", "inheriting_shim"):
        assert const not in SOURCE, f"runner must not define {const}"


def test_no_scientific_primary_flag_in_this_stage():
    """This stage must not offer a scientific primary gate at all."""
    assert "--execute-primary" not in SOURCE
    assert "PASS_RSI_005" not in SOURCE
    assert "FAIL_RSI_005" not in SOURCE
    assert "INCONCLUSIVE_RSI_005" not in SOURCE


# ---------------------------------------------------------------------------
# 4. End-to-end qualification: real boundary, zero forbidden effects
# ---------------------------------------------------------------------------


def test_qualification_end_to_end():
    """Run --qualify-harness for real: fresh child process crosses the
    token-gated boundary, PRE_NIGHTSHIFT_BOUNDARY is reached, and nothing
    forbidden happens (no marker, no Nightshift, no candidate, no REOPEN,
    no scientific result)."""
    marker = EXP_DIR / ".rsi-005-primary-contact"
    assert not marker.exists(), "marker must be absent before qualification"
    out = Path(tempfile.mkdtemp(prefix="rsi-005-test-")) / "qualification.json"
    try:
        cp = subprocess.run(
            [sys.executable, str(RUNNER), "--qualify-harness", "--output", str(out)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(EXP_DIR),
        )
        assert cp.returncode == 0, f"qualification failed:\n{cp.stdout}\n{cp.stderr}"
        evidence = json.loads(out.read_text(encoding="utf-8"))

        assert evidence["qualification_status"] == r5.QUALIFIED
        assert evidence["boundary_reached"] == r5.PRE_NIGHTSHIFT_BOUNDARY
        assert evidence["airlock_base_sha"] == r5.AIRLOCK_BASE_MAIN
        assert evidence["rsi004_predecessor_runner_sha256"] == r5.PREDECESSOR_RUNNER_SHA256
        assert evidence["rsi004_frozen_prereg_sha256"] == r5.PREDECESSOR_PREREG_SHA256
        assert evidence["verified_memory_commit"] == r5.VERIFIED_MEMORY_COMMIT
        assert (
            evidence["verified_memory_evidence_py_sha256"] == r5.EVIDENCE_PY_SHA256
        )
        assert evidence["rsi005_runner_sha256"] == r5.sha256_file(RUNNER)

        # Real subprocess boundary: distinct PIDs, child reloaded state.
        assert evidence["child_pid"] != evidence["parent_pid"]
        assert evidence["distinct_process"] is True
        assert evidence["state_dir_created"] is True
        assert evidence["phase_token_round_trip"] is True
        assert evidence["child_state_reload_ok"] is True
        assert evidence["fixture_base_sha"]
        assert len(evidence["installed_ref_bindings"]) == 4
        assert all(
            sha == evidence["fixture_base_sha"]
            for sha in evidence["installed_ref_bindings"].values()
        )

        # Zero forbidden effects.
        assert evidence["marker_exists_before"] is False
        assert evidence["marker_exists_after"] is False
        assert evidence["nightshift_contacts"] == 0
        assert evidence["candidate_executions"] == 0
        assert evidence["phase_scientific_executions"] == 0
        assert evidence["reopen_mutations"] == 0
        assert not marker.exists(), "qualification created the primary-contact marker"
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
        if marker.exists():
            marker.unlink()


def test_self_check_clean():
    assert r5.self_check() == []
