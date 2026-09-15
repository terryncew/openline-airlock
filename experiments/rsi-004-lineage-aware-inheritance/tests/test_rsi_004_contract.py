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
    assert len(prereg["bindings"]) == 16
    decided = prereg["decided"]
    assert decided.startswith("DECIDED"), "preregistration must be frozen before primary contact"
    assert not decided.startswith("PROPOSED")
    old_hash = "5750248e5236c506270fd5506bd695f62468dbc3114305cc2284e40d7a544d9c"
    assert r.PREREG_SHA256 != old_hash
    assert old_hash in decided, "superseded pre-run draft hash must be recorded"


# ----------------------------------- corrected contract: actual generation base ---

def _make_three_commit_chain(tmp: Path) -> tuple[str, str, str]:
    """base (policy STEP=1, VALUE 0) -> parent (policy STEP=2) -> child
    (VALUE 4 only, policy untouched). Mirrors the gen1 -> gen2 shape."""
    repo = tmp / "chain"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    git("init", "-q")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    (repo / "src").mkdir()
    (repo / "src" / "policy.py").write_text("STEP = 1\n")
    (repo / "src" / "value.py").write_text("VALUE = 0\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                          stdout=subprocess.PIPE, text=True).stdout.strip()
    (repo / "src" / "policy.py").write_text("STEP = 2\n")
    git("commit", "-qam", "parent policy change")
    parent = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                            stdout=subprocess.PIPE, text=True).stdout.strip()
    (repo / "src" / "value.py").write_text("VALUE = 4\n")
    git("commit", "-qam", "child value change")
    child = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                           stdout=subprocess.PIPE, text=True).stdout.strip()
    return base, parent, child


def test_gen2_gen3_actual_base_candidate_diffs():
    """The base-diff bug regression: the child diff must be measured from
    the parent's exact installed commit, not the fixture base. No Nightshift."""
    with tempfile.TemporaryDirectory() as td:
        base, parent, child = _make_three_commit_chain(Path(td))
        repo = Path(td) / "chain"
        # Correct: child's own change is value.py only; the inherited parent
        # policy change is not counted as the child's candidate change.
        assert r.candidate_paths(repo, parent, child) == ["src/value.py"]
        # The stale fixture-base diff pollutes the child diff with the
        # inherited policy change and would violate the [src/value.py]-only
        # assertion: this is the bug being fixed.
        stale = r.candidate_paths(repo, base, child)
        assert "src/policy.py" in stale
        assert stale != ["src/value.py"]


def test_actual_generation_base_uses_signed_record_base():
    state = {"base_commit": "b" * 40}
    gen1_commit = "b" * 40
    parent_commit = "c" * 40
    # rootU/gen1: actual base is the fixture base, cross-checked.
    gen = {"payload": {"base_commit": gen1_commit}}
    assert r.actual_generation_base(prefix="gen1", state=state, generation=gen,
                                    parent_commit=None) == gen1_commit
    assert r.actual_generation_base(prefix="rootU", state=state, generation=gen,
                                    parent_commit=None) == gen1_commit
    # gen2/gen3: actual base is the parent's exact installed commit.
    gen2 = {"payload": {"base_commit": parent_commit}}
    assert r.actual_generation_base(prefix="gen2", state=state, generation=gen2,
                                    parent_commit=parent_commit) == parent_commit
    assert r.actual_generation_base(prefix="gen3", state=state, generation=gen2,
                                    parent_commit=parent_commit) == parent_commit
    # A generation record whose base disagrees with the expected base fails closed.
    wrong = {"payload": {"base_commit": "d" * 40}}
    with pytest.raises(r.PreconditionFailure):
        r.actual_generation_base(prefix="gen2", state=state, generation=wrong,
                                 parent_commit=parent_commit)
    with pytest.raises(r.PreconditionFailure):
        r.actual_generation_base(prefix="gen3", state=state, generation=gen2,
                                 parent_commit=None)


# --------------------------- corrected contract: centralized projector boundary ---

def test_lineage_projector_call_boundary_is_centralized():
    """derive_airlock_memory_with_lineage is called ONLY from
    project_lineage_memories(); every projection goes through the choke point."""
    source = Path(r.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: set[str] = set()
    stack: list[ast.AST] = []

    class V(ast.NodeVisitor):
        def generic_visit(self, node):
            stack.append(node)
            super().generic_visit(node)
            stack.pop()

        def visit_Call(self, node):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "derive_airlock_memory_with_lineage":
                enclosing = next(
                    (n for n in reversed(stack) if isinstance(n, ast.FunctionDef)), None)
                calls.add(enclosing.name if enclosing else "<module>")
            self.generic_visit(node)

    V().visit(tree)
    assert calls == {"project_lineage_memories"}, f"call boundary broken: {sorted(calls)}"
    assert hasattr(r, "project_lineage_memories")
    assert hasattr(r, "project_bundles")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    rule = next(b for b in prereg["bindings"] if b["id"] == "lineage_aware_projector_rule")
    assert "project_lineage_memories" in rule["value"]
    assert "only calls to derive_airlock_memory_with_lineage occur inside project_lineage_memories" in rule["verification"]


# ------------------------------ corrected contract: lineage record-set hash ---

def test_lineage_record_set_hash_contract():
    """The lineage record-set digest is deterministic and order-independent;
    any byte change changes it. Both checkpoint and reprojection values are
    bound in the receipt."""
    records = [
        {"subject_lesson_id": "gen2", "declaration": "REQUIRED", "x": 1},
        {"subject_lesson_id": "rootU", "declaration": "ROOT"},
        {"subject_lesson_id": "gen3", "declaration": "REQUIRED"},
        {"subject_lesson_id": "gen1", "declaration": "ROOT"},
    ]
    h1 = r.lineage_record_set_sha256(records)
    h2 = r.lineage_record_set_sha256(list(reversed(records)))
    assert h1 == h2, "record-set hash must be load-order independent"
    mutated = [dict(rec) for rec in records]
    mutated[0] = dict(mutated[0], x=2)
    assert r.lineage_record_set_sha256(mutated) != h1, "any byte change must change the digest"
    assert len(h1) == 64
    assert "lineage_record_set_sha256_checkpoint" in r.RECEIPT_REQUIRED_TOP_KEYS
    assert "lineage_record_set_sha256_reprojection" in r.RECEIPT_REQUIRED_TOP_KEYS


# ----------------------------------- corrected contract: rootU VALUE 0 -> 2 ---

def test_rootU_bonus_axis_produces_value_two():
    """rootU's unrelated bonus-axis policy produces VALUE 2, not 11."""
    assert "BONUS = 1" in r.POLICY_VU
    assert "BONUS = 10" not in r.POLICY_VU
    assert r.POLICY_VU != r.POLICY_V2, "rootU policy must be a distinct unrelated axis"
    ns: dict = {}
    exec(r.POLICY_VU, ns)
    assert ns["propose"](0) == 2, "rootU policy applied once must yield VALUE 2"
    assert "VALUE = 2" in r.ROOTU_SHIM
    assert "VALUE = 11" not in r.ROOTU_SHIM
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    assert prereg["generations"]["rootU"]["expected_gain"] == "VALUE 0 -> 2 on the unrelated sibling branch"
    assert "sibling" in prereg["generations"]["rootU"]["generator"]


# ------------------------------------------------------- zero contact proof ---

def test_no_primary_artifacts_exist():
    """After self-check and these tests: no marker, no result, no receipt,
    no frozen proof directory. This is the zero-primary-contact assertion."""
    assert not MARKER.exists(), "primary-contact marker exists: the primary ran"
    assert not (EXP_DIR / "result.json").exists()
    assert not (EXP_DIR / "receipt.json").exists()
    repo_root = EXP_DIR.parents[1]
    assert not (repo_root / "proofs" / "rsi-004").exists()
