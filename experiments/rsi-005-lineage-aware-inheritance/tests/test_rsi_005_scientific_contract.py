"""Non-primary contract tests for the RSI-005 scientific package.

These tests NEVER pass --execute-primary, NEVER dispatch scientific phases,
NEVER touch Nightshift, NEVER write the primary-contact marker, NEVER issue
REOPEN, and NEVER produce a result.json or scientific receipt. They verify
the frozen structure: harness binding, choke-point exclusivity, verdict
precedence, and the mutual prereg/runner hash binding.
"""
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXP_DIR))

import run_rsi_005 as h
import run_rsi_005_scientific as sci

RUNNER_PATH = EXP_DIR / "run_rsi_005_scientific.py"
HARNESS_PATH = EXP_DIR / "run_rsi_005.py"
PREREG_PATH = EXP_DIR / "RSI_005_PREREGISTRATION.json"
MARKER = h.PRIMARY_CONTACT_MARKER

QUALIFIED_HARNESS_SHA256 = "1fa894bd623eb4aacc39645ad546c0d31889dec391b1a65d65a27842937665e3"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runner_ast() -> ast.Module:
    return ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))


def test_qualified_harness_hash_binding():
    """The scientific package binds to the exact qualified harness bytes."""
    assert sha256_file(HARNESS_PATH) == QUALIFIED_HARNESS_SHA256
    assert sha256_file(HARNESS_PATH) == sci.QUALIFIED_HARNESS_SHA256


def test_state_dir_repair_present():
    """The earned repair survives: build_fixture() creates state_dir before
    the orchestrator phase token is written (no Nightshift involved)."""
    with tempfile.TemporaryDirectory(prefix="rsi005-contract-") as tmp:
        state = h.build_fixture(Path(tmp))
        state_dir = Path(state["state_dir"])
        assert state_dir.is_dir(), "state_dir must exist straight out of build_fixture()"
        token = h.write_phase_token(state_dir)
        assert (state_dir / ".phase_token").read_text(encoding="utf-8").strip() == token


def test_no_bypass_of_qualified_nightshift_entry():
    """No Nightshift call path in the scientific runner except the qualified
    harness's nightshift_entry()."""
    tree = runner_ast()
    direct = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "run_nightshift"]
    assert not direct, "scientific runner must not reference run_nightshift directly"
    defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "nightshift_entry"]
    assert not defs, "scientific runner must not define its own nightshift_entry"
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "nightshift_entry"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "h"
    ]
    assert len(calls) == 4, f"expected exactly 4 h.nightshift_entry() call sites, found {len(calls)}"


def test_no_primary_marker_write_in_scientific_runner():
    """The marker is written only by the qualified choke point; the
    scientific runner never writes it, and none exists after non-primary
    operations."""
    tree = runner_ast()

    def _is_marker_write(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "write_text"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "PRIMARY_CONTACT_MARKER"
        )

    writes = [n for n in ast.walk(tree) if _is_marker_write(n)]
    assert not writes, "scientific runner must never write the primary-contact marker"
    assert not MARKER.exists(), "no RSI-005 primary-contact marker may exist outside a primary"


def test_actual_generation_base_rules():
    """gen2/gen3 generation bases are their parents' exact installed commits;
    the signed generation record base must match the actual base."""
    state = {"base_commit": "base123"}
    root_gen = {"payload": {"base_commit": "base123"}}
    assert sci.actual_generation_base(prefix="rootU", state=state, generation=root_gen, parent_commit=None) == "base123"
    assert sci.actual_generation_base(prefix="gen1", state=state, generation=root_gen, parent_commit=None) == "base123"
    child_gen = {"payload": {"base_commit": "parent456"}}
    assert sci.actual_generation_base(prefix="gen2", state=state, generation=child_gen, parent_commit="parent456") == "parent456"
    assert sci.actual_generation_base(prefix="gen3", state=state, generation=child_gen, parent_commit="parent456") == "parent456"
    # Wrong or missing parent binding fails closed.
    with pytest.raises(sci.PreconditionFailure):
        sci.actual_generation_base(prefix="gen2", state=state, generation=child_gen, parent_commit="other")
    with pytest.raises(sci.PreconditionFailure):
        sci.actual_generation_base(prefix="gen2", state=state, generation=root_gen, parent_commit="parent456")
    with pytest.raises(sci.PreconditionFailure):
        sci.actual_generation_base(prefix="gen3", state=state, generation=child_gen, parent_commit=None)
    # Source pins the wiring: gen2 <- gen1, gen3 <- gen2.
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert 'prefix="gen2", parent_prefix="gen1"' in src
    assert 'prefix="gen3", parent_prefix="gen2"' in src


def test_centralized_lineage_projector_boundary():
    """Every lineage-aware projection funnels through project_lineage_memories,
    which is the sole caller of derive_airlock_memory_with_lineage. Direct
    calls happen only in phase_reproject; the thin project_bundles wrapper is
    used only by the checkpoint and reopen phases."""
    tree = runner_ast()
    derive_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "derive_airlock_memory_with_lineage"
    ]
    assert len(derive_calls) == 1, "exactly one derive_airlock_memory_with_lineage call (the choke point)"
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        called = {
            n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        if "project_lineage_memories" in called:
            assert node.name in {"phase_reproject", "project_bundles", "probe_gen4_admission"}, (
                f"project_lineage_memories called outside the boundary: {node.name}"
            )
        if "project_bundles" in called:
            assert node.name in {"phase_checkpoint", "phase_reopen"}, (
                f"project_bundles called outside checkpoint/reopen: {node.name}"
            )


def test_raw_receipt_formatting_mutation_detection():
    """A whitespace-only reformat of a historical receipt file changes its
    raw digest and is detected."""
    pre = {"receipts/rootU_generation.json": "a" * 64, "receipts/gen1_lineage.json": "b" * 64}
    identical = dict(pre)
    assert sci.historical_files_unchanged(pre, identical) is True
    reformatted = dict(pre)
    reformatted["receipts/gen1_lineage.json"] = "c" * 64  # same canonical parse, different bytes
    assert sci.historical_files_unchanged(pre, reformatted) is False


def test_lineage_record_set_digest_equality():
    """The lineage record-set digest is deterministic and order-independent,
    but content-sensitive."""
    rec_a = {"subject_lesson_id": "gen2", "kind": "REQUIRED", "parent": "gen1"}
    rec_b = {"subject_lesson_id": "gen3", "kind": "REQUIRED", "parent": "gen2"}
    d1 = sci.lineage_record_set_sha256([rec_a, rec_b])
    d2 = sci.lineage_record_set_sha256([rec_b, rec_a])
    assert d1 == d2
    assert len(d1) == 64 and all(c in "0123456789abcdef" for c in d1)
    d3 = sci.lineage_record_set_sha256([rec_a, dict(rec_b, parent="gen1")])
    assert d3 != d1


def _valid_standings():
    return {"gen1": "questioned", "gen2": "questioned", "gen3": "questioned", "rootU": "inherited"}


def _valid_kwargs(**over):
    kw = dict(
        pre_reopen_ok=True,
        lineage_ok=True,
        refs_unchanged=True,
        receipts_byte_identical=True,
        deterministic=True,
        gen1_questioned=True,
        standings=_valid_standings(),
        gen4_probe="DENIED",
    )
    kw.update(over)
    return kw


def test_verdict_precedence():
    """Scientific FAIL only for otherwise-valid lineage-semantics failure;
    harness/integrity failures are INCONCLUSIVE with precise cause codes."""
    assert sci.decide_verdict(**_valid_kwargs()) == (
        "PASS_RSI_005_LINEAGE_AWARE_INHERITANCE", "NONE")
    # Scientific failures -> FAIL with REQUIRED_ANCESTRY_NOT_ENFORCED.
    bad = dict(_valid_standings(), gen2="inherited")
    assert sci.decide_verdict(**_valid_kwargs(standings=bad)) == (
        "FAIL_RSI_005_REQUIRED_ANCESTRY_NOT_ENFORCED", "REQUIRED_ANCESTRY_NOT_ENFORCED")
    assert sci.decide_verdict(**_valid_kwargs(gen4_probe="ADMITTED")) == (
        "FAIL_RSI_005_REQUIRED_ANCESTRY_NOT_ENFORCED", "REQUIRED_ANCESTRY_NOT_ENFORCED")
    # Integrity failures -> INCONCLUSIVE, never the scientific FAIL.
    assert sci.decide_verdict(**_valid_kwargs(pre_reopen_ok=False))[0] == \
        "INCONCLUSIVE_RSI_005_PRECONDITION_FAILURE"
    assert sci.decide_verdict(**_valid_kwargs(pre_reopen_ok=False))[1] == "CHECKPOINT_NOT_ESTABLISHED"
    assert sci.decide_verdict(**_valid_kwargs(lineage_ok=False))[1] == "LINEAGE_BINDING_FAILURE"
    assert sci.decide_verdict(**_valid_kwargs(refs_unchanged=False))[1] == "INSTALLED_REF_MUTATION"
    assert sci.decide_verdict(**_valid_kwargs(receipts_byte_identical=False))[1] == "RECEIPT_MUTATION"
    assert sci.decide_verdict(**_valid_kwargs(deterministic=False))[1] == "PROJECTION_NONDETERMINISM"
    assert sci.decide_verdict(**_valid_kwargs(gen1_questioned=False))[1] == "REOPEN_NOT_OBSERVED"


def test_exactly_three_formal_verdicts():
    assert sci.VERDICTS == (
        "PASS_RSI_005_LINEAGE_AWARE_INHERITANCE",
        "FAIL_RSI_005_REQUIRED_ANCESTRY_NOT_ENFORCED",
        "INCONCLUSIVE_RSI_005_PRECONDITION_FAILURE",
    )
    assert set(sci.CAUSE_CODES) == {
        "NONE",
        "REQUIRED_ANCESTRY_NOT_ENFORCED",
        "INSTALLED_REF_MUTATION",
        "RECEIPT_MUTATION",
        "PROJECTION_NONDETERMINISM",
        "LINEAGE_BINDING_FAILURE",
        "REOPEN_NOT_OBSERVED",
        "CHECKPOINT_NOT_ESTABLISHED",
    }


def test_gen4_probe_only():
    """gen4 is a probe through gen3 and is never executed."""
    tree = runner_ast()
    probe_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "probe_gen4_admission"
    )
    called = {
        (n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id)
        for n in ast.walk(probe_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))
    }
    assert "nightshift_entry" not in called and "run_nightshift" not in called
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert "gen4 is probe-only and is never executed" in src or "never executed" in ast.get_docstring(probe_fn).lower() or "never executed" in src


def test_phase_pid_uniqueness_logic():
    """Duplicate or incomplete phase-PID maps fail closed (explicit set
    uniqueness, not chained !=)."""
    with tempfile.TemporaryDirectory(prefix="rsi005-pids-") as tmp:
        state_dir = Path(tmp)
        pids = {phase: 1000 + i for i, phase in enumerate(sci.FRESH_PROCESS_PHASES)}
        (state_dir / "phase_pids.json").write_text(json.dumps(pids), encoding="utf-8")
        assert sci.require_distinct_phase_pids(state_dir) == pids
        dup = dict(pids)
        dup["reproject"] = dup["checkpoint"]  # two phases, one process
        (state_dir / "phase_pids.json").write_text(json.dumps(dup), encoding="utf-8")
        with pytest.raises(sci.PreconditionFailure):
            sci.require_distinct_phase_pids(state_dir)
        incomplete = {k: v for k, v in pids.items() if k != "reopen"}
        (state_dir / "phase_pids.json").write_text(json.dumps(incomplete), encoding="utf-8")
        with pytest.raises(sci.PreconditionFailure):
            sci.require_distinct_phase_pids(state_dir)


def test_prereg_and_runner_mutual_binding():
    """The frozen preregistration binds the scientific runner hash (via the
    documented canonicalization) and the runner binds the preregistration
    file hash; both hold simultaneously."""
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    runner_src = RUNNER_PATH.read_text(encoding="utf-8")
    canonical = re.sub(
        r'^PREREG_SHA256 = "[^"]*"$',
        'PREREG_SHA256 = "' + "0" * 64 + '"',
        runner_src,
        flags=re.M,
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == \
        prereg["bindings"]["scientific_runner_sha256"]
    assert sha256_file(PREREG_PATH) == sci.PREREG_SHA256
    assert prereg["decided"].startswith("DECIDED \u2014 FROZEN BEFORE PRIMARY CONTACT")
    assert prereg["bindings"]["airlock_main_sha"] == "5e319f069c247138ff17186674829e99feba1d9c"
    assert prereg["bindings"]["qualified_harness_runner_sha256"] == QUALIFIED_HARNESS_SHA256


def test_zero_primary_contact_during_selfcheck(tmp_path):
    """--self-check exits clean and creates no marker, no REOPEN, no
    result.json, no scientific receipt anywhere near the experiment dir."""
    cp = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--self-check"],
        capture_output=True, text=True, cwd=str(EXP_DIR),
    )
    assert cp.returncode == 0, cp.stderr
    assert "scientific self-check clean" in cp.stdout
    assert not MARKER.exists()
    assert not (EXP_DIR / "result.json").exists()
    for p in EXP_DIR.rglob("*.json"):
        assert "reopen" not in p.name.lower() or "PREREGISTRATION" in p.name


def test_no_execute_primary_in_build_and_ci():
    """The future gate flag must never be invoked by tests, workflows, or
    build scripts. Lines that merely guard against it (assert/grep/not in)
    are allowed."""
    guard_words = ("assert", "grep", "not in", "never", "must", "forbid", "invokes or enables")
    for path in list((EXP_DIR / "tests").glob("*.py")) + list((EXP_DIR / ".." / ".." / ".github" / "workflows").glob("*.yml")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "--execute-primary" not in line:
                continue
            lowered = line.lower()
            assert any(w in lowered for w in guard_words), (
                f"{path}:{i} invokes or enables --execute-primary"
            )
