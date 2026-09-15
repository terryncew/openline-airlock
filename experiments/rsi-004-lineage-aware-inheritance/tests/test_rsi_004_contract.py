"""RSI-004 contract tests.

These tests assert the fail-closed gates and the preregistered contract.
They produce zero Nightshift generations, zero candidate executions, zero
REOPEN mutations, and zero RSI-004 primary contact by construction: they
never invoke the primary (no --execute-primary, no phase dispatch), they
never create the contact marker, and they only import the runner module
and call its pure helpers.
"""

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
RUNNER = EXP_DIR / "run_rsi_004.py"
PREREG = EXP_DIR / "RSI_004_PREREGISTRATION.json"
MARKER = EXP_DIR / ".rsi-004-primary-contact"

sys.path.insert(0, str(EXP_DIR))

import run_rsi_004 as r


def read_source() -> str:
    return RUNNER.read_text(encoding="utf-8")


# ---------------------------------------------------------------- gating ---

def test_default_invocation_does_not_execute_primary():
    """Default invocation (no flags) runs only the self-check; it must not
    create the primary-contact marker or any result."""
    assert not MARKER.exists()
    cp = subprocess.run(
        [sys.executable, str(RUNNER)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert cp.returncode == 0
    assert "Primary NOT executed" in cp.stdout
    assert not MARKER.exists(), "default invocation created the primary-contact marker"
    assert not (EXP_DIR / "result.json").exists()


def test_self_check_flag_does_not_execute_primary():
    cp = subprocess.run(
        [sys.executable, str(RUNNER), "--self-check"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert cp.returncode == 0
    assert "Primary NOT executed" in cp.stdout
    assert not MARKER.exists()


def test_phase_without_gate_is_rejected():
    """A phase dispatch without the explicit gate must be refused by the CLI."""
    cp = subprocess.run(
        [sys.executable, str(RUNNER), "--phase", "select-rootU",
         "--state", "/tmp/does-not-exist.json"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert cp.returncode != 0
    assert "execute-primary" in cp.stderr
    assert not MARKER.exists()


def test_phase_with_wrong_gate_value_is_rejected():
    """A misspelled gate flag must not be accepted as the gate."""
    cp = subprocess.run(
        [sys.executable, str(RUNNER), "--execute_primary",
         "--phase", "select-rootU", "--state", "/tmp/x.json"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert cp.returncode != 0
    assert not MARKER.exists()


def test_primary_gate_predicate():
    assert r.primary_gate(["--execute-primary"]) is True
    assert r.primary_gate([]) is False
    assert r.primary_gate(["--self-check"]) is False
    assert r.primary_gate(["--execute_primary"]) is False


def test_execute_primary_without_phase_is_the_only_live_path():
    """The only live execution path requires the exact gate flag, and it is
    not invoked here. This test only inspects the gate predicate."""
    assert not r.primary_gate([])
    assert not MARKER.exists()


# ------------------------------------------------------- verdict contract ---

def test_exactly_three_verdicts_and_cause_code_only():
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    assert set(prereg["verdicts"]) == {
        r.VERDICT_PASS, r.VERDICT_FAIL, r.VERDICT_INCONCLUSIVE,
    }
    assert set(prereg["cause_codes"]) == set(r.CAUSE_CODES)
    verdict_re = __import__("re").compile(r"^(PASS|FAIL|INCONCLUSIVE)_RSI_004")
    found = {
        n.value for n in ast.walk(ast.parse(read_source()))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and verdict_re.match(n.value)
    }
    assert found == {r.VERDICT_PASS, r.VERDICT_FAIL, r.VERDICT_INCONCLUSIVE}


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(pre_reopen_ok=False), (r.VERDICT_INCONCLUSIVE, "CHECKPOINT_NOT_ESTABLISHED")),
        (dict(lineage_ok=False), (r.VERDICT_INCONCLUSIVE, "LINEAGE_BINDING_FAILURE")),
        (dict(refs_unchanged=False), (r.VERDICT_FAIL, "INSTALLED_REF_MUTATION")),
        (dict(receipts_unchanged=False), (r.VERDICT_FAIL, "RECEIPT_MUTATION")),
        (dict(deterministic=False), (r.VERDICT_FAIL, "PROJECTION_NONDETERMINISM")),
        (dict(gen1_questioned=False), (r.VERDICT_INCONCLUSIVE, "REOPEN_NOT_OBSERVED")),
        (
            dict(standings={"gen1": "questioned", "gen2": "inherited", "gen3": "inherited",
                            "rootU": "inherited"}),
            (r.VERDICT_FAIL, "REQUIRED_ANCESTRY_NOT_ENFORCED"),
        ),
        (
            dict(standings={"gen1": "questioned", "gen2": "questioned", "gen3": "questioned",
                            "rootU": "inherited"},
                 gen4_probe="DENIED"),
            (r.VERDICT_PASS, "NONE"),
        ),
        (
            dict(standings={"gen1": "questioned", "gen2": "questioned", "gen3": "questioned",
                            "rootU": "inherited"},
                 gen4_probe="ADMITTED"),
            (r.VERDICT_FAIL, "REQUIRED_ANCESTRY_NOT_ENFORCED"),
        ),
    ],
)
def test_verdict_precedence(kwargs, expected):
    base = dict(
        pre_reopen_ok=True,
        lineage_ok=True,
        refs_unchanged=True,
        receipts_unchanged=True,
        deterministic=True,
        gen1_questioned=True,
        standings={"gen1": "questioned", "gen2": "questioned", "gen3": "questioned",
                  "rootU": "inherited"},
        gen4_probe="DENIED",
    )
    base.update(kwargs)
    assert r.decide_verdict(**base) == expected


def test_verdict_precedence_ordering_is_preregistered():
    """Integrity failures outrank the scientific question: with several
    failures present, the first preregistered cause wins."""
    verdict, cause = r.decide_verdict(
        pre_reopen_ok=True, lineage_ok=True,
        refs_unchanged=False, receipts_unchanged=False, deterministic=False,
        gen1_questioned=True,
        standings={"gen1": "questioned", "gen2": "questioned", "gen3": "questioned"},
        gen4_probe="DENIED",
    )
    assert (verdict, cause) == (r.VERDICT_FAIL, "INSTALLED_REF_MUTATION")


# ------------------------------------------------------- receipt bindings ---

def test_receipt_required_bindings_present():
    """The receipt schema keys must cover every binding the preregistration
    demands of the final primary receipt."""
    assert set(r.RECEIPT_REQUIRED_TOP_KEYS) >= {
        "airlock_base_sha", "verified_memory_sha",
        "verified_memory_evidence_py_sha256", "preregistration_sha256",
        "generations", "required_edges", "pre_reopen_established",
        "reopen_evidence", "restart_evidence", "post_reopen_standings",
        "lineage_witness_paths", "gen4_probe", "historical_receipt_hashes",
        "installed_ref_hashes", "installed_policy_hashes",
        "installed_refs_unchanged", "reprojection_deterministic",
        "verdict", "cause_code",
    }


def test_receipt_validator_rejects_incomplete_receipt():
    assert r.validate_receipt_bindings({})  # everything missing
    assert r.validate_receipt_bindings({"verdict": r.VERDICT_PASS})  # mostly missing


def test_gen4_probe_disposition_is_bound_without_execution():
    """The probe computes admission from persisted records; there is no
    phase, install ref, or Nightshift path that could execute gen4."""
    assert r.GEN4_LESSON_ID == "rsi-004-gen4-admission-probe"
    source = read_source()
    tree = ast.parse(source)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "probe_gen4_admission" in names
    for forbidden in ("phase_select_gen4", "phase_install_gen4", "GEN4_INSTALL_REF"):
        assert forbidden not in names
        assert forbidden not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def test_inconclusive_result_carries_only_verdict_and_cause():
    res = r.inconclusive_result("checkpoint could not be established", None)
    assert res["verdict"] == r.VERDICT_INCONCLUSIVE
    assert res["cause_code"] == "CHECKPOINT_NOT_ESTABLISHED"
    assert res["preregistration_sha256"] == r.PREREG_SHA256
    assert res["airlock_base_sha"] == r.AIRLOCK_BASE_MAIN


def test_preregistration_bytes_are_frozen():
    assert PREREG.exists()
    assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == r.PREREG_SHA256
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    assert len(prereg["bindings"]) == 15


# ------------------------------------------------------- zero contact proof ---

def test_no_primary_artifacts_exist():
    """After self-check and these tests: no marker, no result, no receipt,
    no frozen proof directory. This is the zero-primary-contact assertion."""
    assert not MARKER.exists(), "primary-contact marker exists: the primary ran"
    assert not (EXP_DIR / "result.json").exists()
    assert not (EXP_DIR / "receipt.json").exists()
    repo_root = EXP_DIR.parents[1]
    assert not (repo_root / "proofs" / "rsi-004").exists()
