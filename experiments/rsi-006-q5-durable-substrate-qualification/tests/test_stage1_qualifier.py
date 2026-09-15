"""RSI-006-Q5 Stage 1 qualifier contract tests.

Fixture-only: every test builds tiny local fixture git repositories and
fixture manifests. The four real RSI repositories are never cloned, no
Stage 1 is run against them, and no scientific contact occurs. No
imports of the scientific substrate (perturb, contact, stransaction,
q5_adapter, execution_ledger) appear anywhere in this file or in the
mechanism under test; Q3's frozen baseline helpers (env_qualify,
observe, pool_config, receipt) are the sanctioned reuse.
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

import environment_receipt as qr

TESTS_DIR = Path(__file__).resolve().parent
EXP_DIR = TESTS_DIR.parent
STAGE1_DIR = EXP_DIR / "stage1"
REPO_ROOT = EXP_DIR.parents[1]


def _load_stage1_env_qualify():
    """Load stage1/env_qualify.py without importing it by name."""
    spec = importlib.util.spec_from_file_location(
        "q5_stage1_env_qualify_test", STAGE1_DIR / "env_qualify.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage1 = _load_stage1_env_qualify()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        text=True, env=env, timeout=120)
    return out.stdout.strip()


_GREEN_TESTS = '''\
def test_alpha():
    assert 1 + 1 == 2


def test_beta():
    assert "x".upper() == "X"
'''

_RED_TESTS = '''\
def test_alpha():
    assert 1 + 1 == 2


def test_fails():
    assert 1 + 1 == 3, "fixture red: always fails"
'''

_FLAKY_TESTS = '''\
import os


def test_alpha():
    assert 1 + 1 == 2


def test_flaky():
    marker = os.environ.get("FX_FLAKY_MARKER", "a")
    assert marker == "a", "fixture flaky: env marker differs between runs"
'''


def make_origin(root: Path, name: str, mode: str):
    """Create a tiny local fixture git repository.

    mode: "green" (tests pass), "red" (one test always fails),
    "flaky" (passes only when FX_FLAKY_MARKER == "a").
    Returns (origin_path, commit_sha).
    """
    origin = root / name
    pkg = origin / "pkg"
    tests = origin / "tests"
    pkg.mkdir(parents=True)
    tests.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (tests / "__init__.py").write_text("")
    body = {"green": _GREEN_TESTS, "red": _RED_TESTS,
            "flaky": _FLAKY_TESTS}[mode]
    (tests / "test_basics.py").write_text(body)
    _git(origin, "init", "-q")
    _git(origin, "add", ".")
    _git(origin, "-c", "user.email=fx@example.com",
         "-c", "user.name=fx", "commit", "-qm", f"fixture {name} {mode}")
    return origin, _git(origin, "rev-parse", "HEAD")


@pytest.fixture()
def work_dir():
    # Durable experiment work belongs under ~/workspace/, never /tmp
    # (the Stage 1 qualifier itself rejects volatile roots).
    base = Path.home() / "workspace" / "tmp" / "q5-stage1-tests"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="q5-", dir=base) as tmp:
        yield Path(tmp)


@pytest.fixture()
def fx_layout(work_dir):
    """Fixture 'airlock repo' root: manifest, code files, Q3, Q4.

    A real git repo so git_head() probing works. The fixture manifest
    requires only its own fixture file set via ``manifest_required``.
    """
    fx = work_dir / "fx"
    (fx / "fxcode").mkdir(parents=True)
    (fx / "fxcode" / "a.py").write_text("X = 1\n")
    (fx / "fxcode" / "b.py").write_text("Y = 2\n")
    (fx / "fxq4").mkdir()
    (fx / "fxq4" / "stransaction.py").write_text(
        "# fixture q4 transaction layer\n")
    q3d = fx / "fxq3"
    q3d.mkdir()
    (q3d / "qa.py").write_text("# fixture q3 helper a\n")
    (q3d / "qb.py").write_text("# fixture q3 helper b\n")
    code_hashes = {n: _sha(q3d / n) for n in ("qa.py", "qb.py")}
    q3_receipt = {"schema": "airlock.rsi-006-q3.env-receipt.v1",
                  "code_hashes": code_hashes}
    (q3d / "environment-receipt.json").write_text(
        json.dumps(q3_receipt, sort_keys=True) + "\n")
    q3_pin = _sha(q3d / "environment-receipt.json")
    code_files = ["fxcode/a.py", "fxcode/b.py", "fxq4/stransaction.py"]
    manifest = {
        "schema": qr.MANIFEST_SCHEMA,
        "code_files": code_files,
        "q3_receipt": {"path": "fxq3/environment-receipt.json",
                       "sha256": q3_pin},
    }
    (fx / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n")
    _git(fx, "init", "-q")
    _git(fx, "add", ".")
    _git(fx, "-c", "user.email=fx@example.com",
         "-c", "user.name=fx", "commit", "-qm", "fixture layout")
    return {
        "root": fx,
        "manifest": fx / "manifest.json",
        "required": tuple(code_files),
        "q3_dir": q3d,
        "q3_receipt": q3d / "environment-receipt.json",
        "q3_pin": q3_pin,
        "q4": fx / "fxq4" / "stransaction.py",
        "q4_sha": _sha(fx / "fxq4" / "stransaction.py"),
    }


def fx_kwargs(layout):
    """Internal fixture-injection kwargs for stage1 functions (no CLI)."""
    return dict(manifest_path=layout["manifest"],
                repo_root=layout["root"],
                q3_dir=layout["q3_dir"],
                q3_receipt_path=layout["q3_receipt"],
                q4_path=layout["q4"],
                q3_receipt_sha256=layout["q3_pin"],
                q4_sha256=layout["q4_sha"],
                manifest_required=layout["required"])


def pool_entry(name, origin, sha):
    return {"name": name, "url": str(origin), "sha": sha,
            "pkg": "pkg", "src_layout": False, "tests": "tests"}


@pytest.fixture()
def fx_pool(work_dir):
    """Two green fixture repos, as stage1 expects a pool."""
    origins = work_dir / "origins"
    origins.mkdir()
    pool = []
    for name in ("alpha", "beta"):
        origin, sha = make_origin(origins, name, "green")
        pool.append(pool_entry(name, origin, sha))
    return pool


def fx_qualifier_binding(work_dir=None, tamper=False):
    """Fixture qualifier provenance binding the REAL qualifier bytes.

    The fixture tree is uncommitted work, so the production git check
    cannot apply; instead the fixture declares the live hashes of the
    real qualifier files with a synthetic source commit. With
    ``tamper=True`` the three files are copied to a scratch dir, one
    byte of the env_qualify.py copy is flipped, but the ORIGINAL hashes
    and the SAME source commit are declared: the preflight must detect
    the byte change and refuse, proving a dirty source is inadmissible
    even when the claimed source identity is unchanged.
    """
    live = {r: _sha(EXP_DIR / r) for r in qr.QUALIFIER_CRITICAL_FILES}
    root = EXP_DIR
    if tamper:
        assert work_dir is not None
        root = Path(work_dir) / "tampered-qualifier"
        for r in qr.QUALIFIER_CRITICAL_FILES:
            dst = root / r
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((EXP_DIR / r).read_bytes())
        eq = root / "stage1" / "env_qualify.py"
        data = bytearray(eq.read_bytes())
        data[64] ^= 0x01  # single-byte working-tree-style change
        eq.write_bytes(bytes(data))
    return {"root": root, "source_commit": "fixture-source-commit",
            "code_hashes": live}


def arm(root, layout, boot="boot-A", **kw):
    kw.setdefault("qualifier_provenance", fx_qualifier_binding())
    return stage1.arm_storage(root, boot_id_reader=lambda: boot,
                              **fx_kwargs(layout), **kw)


def fx_python(root: Path, with_pytest: bool = True) -> str:
    """A fixture interpreter living beneath the durable root.

    A real venv (own prefix under the root) with the parent
    environment's site-packages exposed via a .pth file so pytest is
    importable. ``with_pytest=False`` builds a bare venv whose missing
    pytest simulates a broken interpreter environment. Idempotent.

    The .pth exposure is fixture convenience only -- it lets the
    fixture venv reuse the parent's already-installed pytest without a
    network install. It is NOT interpreter-isolation evidence: the
    enforced isolation property is the interpreter path living beneath
    the durable root, and the genuinely-isolated negative case (no
    .pth, installs disabled) is covered by
    test_isolated_venv_missing_dependency_fails_at_admission.
    """
    venv = root / ("venv" if with_pytest else "venv-bare")
    bin_python = venv / "bin" / "python"
    if not bin_python.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv)],
            check=True, timeout=300)
        if with_pytest:
            import site as _site
            sp = _site.getsitepackages()[0]
            site_pkgs = next(venv.glob("lib/python*/site-packages"))
            (site_pkgs / "parent.pth").write_text(sp + "\n")
    return str(bin_python)


def qualify(root, layout, pool, boot="boot-B", **kw):
    if "python" not in kw:
        kw["python"] = fx_python(root)
    kw.setdefault("qualifier_provenance", fx_qualifier_binding())
    return stage1.qualify_env(root, pool=pool, install_deps=False,
                              boot_id_reader=lambda: boot,
                              **fx_kwargs(layout), **kw)


def green_run(work_dir, fx_layout, fx_pool, boot_arm="boot-A",
              boot_qual="boot-B"):
    """Arm + fully green fixture qualification; returns (root, result)."""
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot=boot_arm)
    result = qualify(root, fx_layout, fx_pool, boot=boot_qual)
    assert result["status"] == "frozen"
    return root, result


def verify_fixture(root, layout, **kw):
    receipt_path = root / stage1.RECEIPT_NAME
    kw.setdefault("stage2_work_dir", root)
    kw.setdefault("python", fx_python(root))
    return qr.verify_receipt(
        receipt_path, pool_dir=root / stage1.POOL_DIR_NAME,
        manifest_path=layout["manifest"],
        repo_root=layout["root"], q3_receipt_path=layout["q3_receipt"],
        q3_code_dir=layout["q3_dir"], q4_path=layout["q4"],
        durable_root=root, manifest_required=layout["required"], **kw)


# ---------------------------------------------------------------------------
# Production boundary: complete surface, CI never invokes it,
# production receipt is not committed
# ---------------------------------------------------------------------------

def test_production_manifest_validates_with_runner_present():
    """The production execution surface is complete: the runner is
    present and listed, and validate_manifest passes. The manifest note
    no longer claims the runner is absent."""
    manifest_path = EXP_DIR / "execution_manifest.json"
    binding = qr.validate_manifest(manifest_path, REPO_ROOT)
    runner = ("experiments/rsi-006-q5-durable-substrate-qualification/"
              "run_rsi_006_q5.py")
    assert (REPO_ROOT / runner).is_file(), "runner file absent"
    assert runner in binding["files"], "runner not bound by the manifest"
    manifest = qr.load_manifest(manifest_path)
    assert "does not exist yet" not in manifest.get("note", ""), \
        "manifest note still claims the runner is absent"


def test_production_environment_receipt_is_not_committed():
    """Production Stage 1 was executed externally and Q5 is frozen:
    no production environment receipt exists anywhere in the repository
    outside transient fixture scratch (which the fixtures clean up).
    The live production receipt remains outside the repository."""
    scratch = TESTS_DIR / "_scratch"
    receipts = [p for p in REPO_ROOT.rglob("q5-environment-receipt.json")
                if scratch not in p.parents]
    assert receipts == [], \
        f"production environment receipt committed: {receipts}"


def test_ci_never_invokes_production_stage1():
    """Neither Q5 CI gate invokes the production arming or
    qualification entry points."""
    wf_dir = REPO_ROOT / ".github" / "workflows"
    for wf in ("rsi-006-q5-stage1-gate.yml", "rsi-006-q5-runner-gate.yml"):
        text = (wf_dir / wf).read_text()
        assert "--qualify-env" not in text, f"{wf} invokes --qualify-env"
        assert "--arm-storage" not in text, f"{wf} invokes --arm-storage"


# ---------------------------------------------------------------------------
# Receipt schema / canonical freeze / create-once
# ---------------------------------------------------------------------------

def test_receipt_schema_and_canonical_freeze(work_dir):
    receipt = {
        "schema": qr.RECEIPT_SCHEMA,
        "stage": "stage1",
        "frozen_at": 1234.5,
        "manifest_binding": {"manifest_sha256": "ab" * 32, "files": {}},
        "vector_hashes": {},
    }
    path = work_dir / "r.json"
    qr.freeze_receipt(path, receipt)
    raw = path.read_bytes()
    assert raw == qr.canonical_bytes(receipt) + b"\n"
    loaded = qr.load_receipt(path)
    assert loaded == receipt
    assert qr.receipt_sha256(path) == hashlib.sha256(raw).hexdigest()


def test_receipt_freeze_is_create_once(work_dir):
    path = work_dir / "r.json"
    first = {"schema": qr.RECEIPT_SCHEMA, "stage": "stage1"}
    qr.freeze_receipt(path, first)
    before = path.read_bytes()
    with pytest.raises(qr.ReceiptExists):
        qr.freeze_receipt(path, {"schema": qr.RECEIPT_SCHEMA, "other": 1})
    assert path.read_bytes() == before


def test_receipt_schema_rejected_on_load(work_dir):
    path = work_dir / "r.json"
    path.write_bytes(qr.canonical_bytes({"schema": "wrong"}) + b"\n")
    with pytest.raises(qr.ReceiptError):
        qr.load_receipt(path)


def test_frozen_receipt_carries_full_binding(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    receipt = json.loads((root / stage1.RECEIPT_NAME).read_bytes())
    assert receipt["schema"] == qr.RECEIPT_SCHEMA
    assert receipt["stage"] == "q5-environment-qualification"
    mb_files = receipt["execution_manifest_files"]
    assert receipt["execution_manifest_sha256"]
    assert set(mb_files) == set(fx_layout["required"])
    assert receipt["python"] == fx_python(root)
    # Q3's frozen probe: resolved executable + version + implementation.
    assert (receipt["interpreter"]["executable"] ==
            str(Path(fx_python(root)).resolve()))
    assert receipt["interpreter"]["implementation"] == "CPython"
    assert receipt["dependency_lock"]["pytest"]
    assert receipt["q3"]["receipt_sha256"] == fx_layout["q3_pin"]
    assert receipt["q4"]["stransaction_sha256"] == fx_layout["q4_sha"]
    assert receipt["q5"]["receipt_module_sha256"] == _sha(
        Path(qr.__file__).resolve())
    assert receipt["repos"]["alpha"]["checkout_sha"]
    assert receipt["attempt"]["id"] == "000001"
    assert receipt["storage_witness"]["armed_boot_id"] == "boot-A"
    assert receipt["storage_witness"]["qualify_boot_id"] == "boot-B"
    wpath = root / stage1.WITNESS_NAME
    assert receipt["storage_witness"]["witness_digest"] == _sha(wpath)
    assert receipt["storage_witness"]["durable_root"] == str(root.resolve())


# ---------------------------------------------------------------------------
# Qualifier implementation binding (what decided admissibility)
# ---------------------------------------------------------------------------

def test_frozen_receipt_carries_qualifier_binding(work_dir, fx_layout,
                                                 fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    receipt = json.loads((root / stage1.RECEIPT_NAME).read_bytes())
    qb = receipt["qualifier"]
    # The qualifier binding (what decided the environment was
    # admissible) is distinct from the execution-manifest binding (what
    # may later perform scientific contact).
    assert set(qr.QUALIFIER_CRITICAL_FILES) == {
        "stage1/env_qualify.py", "environment_receipt.py",
        "execution_manifest.json"}
    assert qb["source_commit"] == "fixture-source-commit"
    expect = {r: _sha(EXP_DIR / r) for r in qr.QUALIFIER_CRITICAL_FILES}
    assert qb["code_hashes"] == expect
    # The receipt records all four: source commit, qualifier file
    # hashes, execution-manifest hash, governed execution-file hashes.
    assert receipt["execution_manifest_sha256"]
    assert receipt["execution_manifest_files"]


def test_dirty_qualifier_file_refused_before_mutation(work_dir, fx_layout,
                                                      fx_pool):
    """Falsifier: a modified qualification-critical file whose declared
    source identity is UNCHANGED is refused before any environment
    mutation. Binding the source commit alone would admit these bytes;
    the byte comparison does not."""
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    tampered = fx_qualifier_binding(work_dir, tamper=True)
    assert tampered["source_commit"] == "fixture-source-commit"
    with pytest.raises(stage1.QualifierBindingError,
                       match="differ from the declared"):
        qualify(root, fx_layout, fx_pool, boot="boot-B",
                qualifier_provenance=tampered)
    # Refused before any environment mutation: no attempt, no pool,
    # no receipt. (The witness file exists: it was armed cleanly first.)
    assert not (root / stage1.ATTEMPTS_DIR).exists()
    assert not (root / stage1.POOL_DIR_NAME).exists()
    assert not (root / stage1.RECEIPT_NAME).exists()


def test_arm_dirty_qualifier_file_refused_before_witness(work_dir,
                                                        fx_layout):
    """The same falsifier on the --arm-storage path: the common
    preflight refuses before the witness can be written."""
    root = work_dir / "droot"
    root.mkdir()
    tampered = fx_qualifier_binding(work_dir, tamper=True)
    with pytest.raises(stage1.QualifierBindingError):
        stage1.arm_storage(root, boot_id_reader=lambda: "boot-A",
                           qualifier_provenance=tampered,
                           **fx_kwargs(fx_layout))
    assert not (root / stage1.WITNESS_NAME).exists()
    assert list(root.iterdir()) == []


def test_production_git_check_clean_passes_dirty_refused(work_dir):
    """Production path: tracked qualifier files must be byte-identical
    to HEAD. A scratch git repo stands in for the real one: a clean
    tree passes and reports the source commit; a one-byte working-tree
    change with HEAD unchanged is refused; an untracked qualifier file
    is refused."""
    repo = work_dir / "scratch-repo"
    exp = (repo / "experiments"
           / "rsi-006-q5-durable-substrate-qualification")
    (exp / "stage1").mkdir(parents=True)
    for rel in qr.QUALIFIER_CRITICAL_FILES:
        (exp / rel).write_bytes(f"# {rel}\n".encode())
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=fx@example.com", "-c", "user.name=fx",
         "commit", "-qm", "clean")
    head = _git(repo, "rev-parse", "HEAD")
    with mock.patch.object(stage1, "Q5_DIR", exp):
        binding = stage1._qualifier_preflight()
        assert binding["source_commit"] == head
        assert (set(binding["code_hashes"])
                == set(qr.QUALIFIER_CRITICAL_FILES))
        # Dirty one working-tree byte; HEAD (source identity) unchanged.
        p = exp / "environment_receipt.py"
        p.write_bytes(p.read_bytes() + b"# dirty\n")
        assert _git(repo, "rev-parse", "HEAD") == head
        with pytest.raises(stage1.QualifierBindingError,
                           match="differs from HEAD"):
            stage1._qualifier_preflight()
        # Untracked qualifier file also fails closed.
        _git(repo, "rm", "-q", "--cached",
             "experiments/rsi-006-q5-durable-substrate-qualification/"
             "stage1/env_qualify.py")
        with pytest.raises(stage1.QualifierBindingError,
                           match="not tracked"):
            stage1._qualifier_preflight()


def test_verify_rejects_qualifier_drift(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    verify_fixture(root, fx_layout)  # green first
    path = root / stage1.RECEIPT_NAME
    receipt = json.loads(path.read_bytes())
    # Tamper with the receipt's qualifier binding (as if the qualifier
    # had been swapped after freezing): the verifier must refuse to
    # trust verification performed by different bytes.
    receipt["qualifier"]["code_hashes"]["environment_receipt.py"] = \
        "0" * 64
    path.write_bytes(qr.canonical_bytes(receipt) + b"\n")
    with pytest.raises(qr.ReceiptError,
                       match="qualifier implementation drifted"):
        verify_fixture(root, fx_layout)


# ---------------------------------------------------------------------------
# Freeze boundary: the source/environment binding must survive the whole
# qualification interval. The initial preflight binds the source state;
# immediately before freeze_receipt() the same pure preflight runs again
# and must reproduce the binding exactly, and the Airlock HEAD must be
# unchanged. A qualification must never span two source states.
# ---------------------------------------------------------------------------

def _drifting_preflight(monkeypatch, mutate):
    """Wrap stage1.preflight so the SECOND call (the pre-freeze
    revalidation) observes source state mutated after the initial
    preflight but before freeze."""
    real_preflight = stage1.preflight
    calls = []

    def wrapper(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            mutate()
        return real_preflight(*a, **k)

    monkeypatch.setattr(stage1, "preflight", wrapper)
    return calls


def test_mid_qualification_source_drift_rejects_freeze(work_dir, fx_layout,
                                                       fx_pool, monkeypatch):
    """Falsifier: a manifest-governed source file mutated after the
    initial preflight but before freeze must fail closed at the final
    preflight. No receipt is frozen, the completed attempt evidence is
    preserved exactly as produced, and a new attempt after the source
    state is stable succeeds."""
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    target = fx_layout["root"] / "fxcode" / "a.py"
    original = target.read_bytes()
    _drifting_preflight(
        monkeypatch,
        lambda: target.write_text("# drifted mid-qualification\n"))
    with pytest.raises(stage1.SourceDriftError, match="drifted"):
        qualify(root, fx_layout, fx_pool, boot="boot-B")
    # No receipt frozen; the completed attempt's evidence is preserved
    # exactly as produced (append-only, never rewritten).
    assert not (root / stage1.RECEIPT_NAME).exists()
    attempts = sorted((root / stage1.ATTEMPTS_DIR).iterdir())
    assert [p.name for p in attempts] == ["000001"]
    assert (attempts[0] / "attempt-manifest.json").is_file()
    assert (attempts[0] / "evidence").is_dir()
    # A new Stage 1 attempt is required after the source state is
    # stable -- and it succeeds.
    target.write_bytes(original)
    result = qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert result["status"] == "frozen"
    assert result["attempt"] == "000002"


def test_head_movement_with_unchanged_bytes_rejects_freeze(
        work_dir, fx_layout, fx_pool, monkeypatch):
    """Falsifier: the Airlock HEAD moving mid-qualification -- with every
    governed byte unchanged (empty commit) -- must fail closed at the
    final preflight. The source commit identity used for one
    qualification must remain stable across the qualification interval."""
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    head_before = _git(fx_layout["root"], "rev-parse", "HEAD")

    def move_head():
        _git(fx_layout["root"], "-c", "user.email=fx@example.com",
             "-c", "user.name=fx", "commit", "-q", "--allow-empty",
             "-m", "mid-qualification HEAD move")

    _drifting_preflight(monkeypatch, move_head)
    with pytest.raises(stage1.SourceDriftError,
                       match="moved mid-qualification"):
        qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert _git(fx_layout["root"], "rev-parse", "HEAD") != head_before
    assert not (root / stage1.RECEIPT_NAME).exists()
    attempts = sorted((root / stage1.ATTEMPTS_DIR).iterdir())
    assert [p.name for p in attempts] == ["000001"]


# ---------------------------------------------------------------------------
# Binding: drift anywhere is rejected by the verifier
# ---------------------------------------------------------------------------

def test_manifest_bytes_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    verify_fixture(root, fx_layout)  # green first
    manifest = json.loads(fx_layout["manifest"].read_text())
    manifest["note"] = "drift"
    fx_layout["manifest"].write_text(
        json.dumps(manifest, sort_keys=True) + "\n")
    with pytest.raises(qr.ReceiptError, match="execution manifest bytes drifted"):
        verify_fixture(root, fx_layout)


def test_execution_file_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    verify_fixture(root, fx_layout)
    (fx_layout["root"] / "fxcode" / "a.py").write_text("X = 999\n")
    with pytest.raises(qr.ReceiptError, match="fxcode/a.py"):
        verify_fixture(root, fx_layout)


def test_execution_file_missing_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    (fx_layout["root"] / "fxcode" / "b.py").unlink()
    with pytest.raises(qr.ManifestIncomplete):
        verify_fixture(root, fx_layout)


def test_q3_receipt_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    fx_layout["q3_receipt"].write_text("{}\n")
    # Caught by the manifest's pinned Q3 hash before the receipt check.
    with pytest.raises(qr.ManifestError,
                       match="pinned Q3 receipt hash mismatch"):
        verify_fixture(root, fx_layout)


def test_q3_code_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    (fx_layout["q3_dir"] / "qa.py").write_text("# drifted\n")
    with pytest.raises(qr.ReceiptError, match="Q3 code file drifted"):
        verify_fixture(root, fx_layout)


def test_q4_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    fx_layout["q4"].write_text("# drifted q4\n")
    # Caught first by the manifest binding (the manifest pins every
    # governed file); the receipt's explicit Q4 section is defense in depth.
    with pytest.raises(qr.ReceiptError,
                       match="manifest-governed execution files drifted"):
        verify_fixture(root, fx_layout)


def test_interpreter_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    fake = dict(qr.interpreter_identity(sys.executable))
    fake["sha256"] = "0" * 64
    with mock.patch.object(qr, "interpreter_identity", return_value=fake):
        with pytest.raises(qr.ReceiptError, match="selected interpreter drift"):
            verify_fixture(root, fx_layout)


def test_dependency_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    with mock.patch.object(qr, "dependency_lock",
                           return_value={"pytest": "0.0.0-fake"}):
        with pytest.raises(qr.ReceiptError, match="dependency lock drift"):
            verify_fixture(root, fx_layout)


def test_repo_checkout_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    clone = root / stage1.POOL_DIR_NAME / "alpha"
    _git(clone, "-c", "user.email=fx@example.com",
         "-c", "user.name=fx", "commit", "-q", "--allow-empty",
         "-m", "drift")
    with pytest.raises(qr.ReceiptError, match="checkout drift"):
        verify_fixture(root, fx_layout)


def test_repo_tree_drift_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    clone = root / stage1.POOL_DIR_NAME / "alpha"
    (clone / "pkg" / "__init__.py").write_text("# tree drift\n")
    with pytest.raises(qr.ReceiptError, match="tree drift since freeze"):
        verify_fixture(root, fx_layout)


def test_baseline_vector_tamper_rejected(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    path = root / stage1.RECEIPT_NAME
    receipt = json.loads(path.read_bytes())
    vec = receipt["baseline_vectors"]["alpha"]
    vec["test_alpha"] = "failed"  # outcome vector tampered
    path.write_bytes(qr.canonical_bytes(receipt) + b"\n")
    with pytest.raises(qr.ReceiptError, match="baseline vector hash mismatch"):
        verify_fixture(root, fx_layout)


def test_baseline_launch_evidence_tamper_rejected(work_dir, fx_layout,
                                                  fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    ev = (root / stage1.ATTEMPTS_DIR / "000001" / "evidence" /
          "alpha-baseline-run-1.json")
    data = json.loads(ev.read_bytes())
    data["n_tests"] = 999  # launch evidence tampered
    ev.write_bytes(qr.canonical_bytes(data) + b"\n")
    with pytest.raises(qr.ReceiptError, match="attempt evidence file drifted"):
        verify_fixture(root, fx_layout)


def test_witness_file_tamper_after_freeze_rejected(work_dir, fx_layout,
                                                   fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    wpath = root / stage1.WITNESS_NAME
    wpath.write_bytes(wpath.read_bytes() + b" ")
    with pytest.raises(qr.ReceiptError, match="storage witness bytes drifted"):
        verify_fixture(root, fx_layout)


# ---------------------------------------------------------------------------
# Baseline admission: two untouched green deterministic runs
# ---------------------------------------------------------------------------

def test_two_untouched_green_deterministic_runs(work_dir, fx_layout,
                                                fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    receipt = json.loads((root / stage1.RECEIPT_NAME).read_bytes())
    for name in ("alpha", "beta"):
        vec = receipt["baseline_vectors"][name]
        assert set(vec) == {"tests.test_basics::test_alpha",
                        "tests.test_basics::test_beta"}
        assert set(vec.values()) == {"passed"}
        bev = receipt["baseline_evidence"][name]
        assert bev["n_tests"] == 2
        assert bev["deterministic"] is True
        run1, run2 = bev["launch_files"]["run1"], bev["launch_files"]["run2"]
        # Distinct evidence files per run (Q3 overwrote the same file).
        # Receipt stores durable-root-relative paths.
        assert run1 != run2
        p1, p2 = root / run1, root / run2
        assert p1.is_file() and p2.is_file()
        d1 = json.loads(p1.read_bytes())
        d2 = json.loads(p2.read_bytes())
        assert d1["run"] == 1 and d2["run"] == 2
        assert d1["launch"]["exit_status"] == 0
        assert d2["launch"]["exit_status"] == 0
        assert bev["launch_sha256"]["run1"] == _sha(p1)
        assert bev["launch_sha256"]["run2"] == _sha(p2)
        expect_vec_hash = qr.sha256_bytes(qr.canonical_bytes(vec))
        assert receipt["baseline_vector_hashes"][name] == expect_vec_hash
        assert bev["vector_sha256"] == expect_vec_hash


def test_red_baseline_refuses_and_freezes_nothing(work_dir, fx_layout):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    origins = work_dir / "origins"
    origins.mkdir()
    origin, sha = make_origin(origins, "gamma", "red")
    with pytest.raises(stage1.q3_env.EnvironmentNotReady):
        qualify(root, fx_layout, [pool_entry("gamma", origin, sha)],
                boot="boot-B")
    assert not (root / stage1.RECEIPT_NAME).exists()
    attempt = root / stage1.ATTEMPTS_DIR / "000001"
    assert attempt.is_dir()
    assert (attempt / "evidence" / "gamma-baseline-run-1.json").is_file()


def test_nondeterministic_baseline_refuses(work_dir, fx_layout):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    origins = work_dir / "origins"
    origins.mkdir()
    origin, sha = make_origin(origins, "delta", "flaky")
    # Run 1 sees marker "a" (passes); run 2 sees "b" (fails).
    # Q3's run_suite_once inherits os.environ, so flipping the marker
    # between the two observe_baseline calls makes run 2 flaky.
    real_observe = stage1.q3_observe.observe_baseline
    calls = {"n": 0}

    def flaky_observe(*args, **kwargs):
        calls["n"] += 1
        os.environ["FX_FLAKY_MARKER"] = "a" if calls["n"] == 1 else "b"
        return real_observe(*args, **kwargs)

    with mock.patch.object(stage1.q3_observe, "observe_baseline",
                           side_effect=flaky_observe):
        with pytest.raises(stage1.q3_env.EnvironmentNotReady,
                           match="not deterministic"):
            qualify(root, fx_layout, [pool_entry("delta", origin, sha)],
                    boot="boot-B")
    os.environ.pop("FX_FLAKY_MARKER", None)
    assert not (root / stage1.RECEIPT_NAME).exists()


# ---------------------------------------------------------------------------
# Pre-contact: zero scientific substrate, zero residue
# ---------------------------------------------------------------------------

def _stage1_source_paths():
    return [STAGE1_DIR / "env_qualify.py", EXP_DIR / "environment_receipt.py"]


def test_stage1_source_imports_no_scientific_substrate():
    import ast
    # Q3's frozen baseline helpers (observe, env_qualify, pool_config,
    # receipt) are the sanctioned reuse and are NOT banned here.
    banned = {"perturb", "contact", "stransaction",
              "q5_adapter", "execution_ledger", "model"}
    for path in _stage1_source_paths():
        tree = ast.parse(path.read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not (imported & banned), f"{path}: {imported & banned}"


def test_stage1_dynamic_load_pulls_no_scientific_substrate():
    probe = (
        "import importlib.util, sys; "
        "spec = importlib.util.spec_from_file_location("
        "'probe_stage1', r'" + str(STAGE1_DIR / "env_qualify.py") + "'); "
        "m = importlib.util.module_from_spec(spec); "
        "sys.modules['probe_stage1'] = m; spec.loader.exec_module(m); "
        "banned = [n for n in sys.modules if n.split('.')[0] in "
        "{'perturb','stransaction','q5_adapter','execution_ledger',"
        "'contact'}]; "
        "print('BANNED:' + ','.join(sorted(banned)))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "BANNED:"


def test_zero_scientific_residue_after_green_run(work_dir, fx_layout,
                                                 fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    forbidden_names = {"contact_marker.json", "journal",
                       "execution_ledger", "scientific_transaction"}
    text_hits = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        assert not any(name in rel for name in forbidden_names), rel
        if path.is_file() and path.suffix in {".json", ".txt", ".md"}:
            text = path.read_text(errors="replace")
            for token in ("tx_nonce", "confirmation_nonce",
                          "ScientificTransaction", "ScientificContact",
                          "mutant"):
                if token in text:
                    text_hits.append((rel, token))
    assert text_hits == []


def test_verifier_executes_zero_baselines(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    real_run = subprocess.run
    seen = []

    def recording(*args, **kwargs):
        seen.append(args[0] if args else kwargs.get("args"))
        return real_run(*args, **kwargs)

    with mock.patch("subprocess.run", side_effect=recording):
        verify_fixture(root, fx_layout)
    for argv in seen:
        # A baseline launch would exec pytest as a command token
        # ([python, "-m", "pytest", ...]); the dependency-lock probe only
        # passes "pytest" as JSON *data* inside sys.argv[1].
        toks = list(argv) if isinstance(argv, (list, tuple)) else [argv]
        assert not any(str(t) == "pytest" for t in toks), toks


# ---------------------------------------------------------------------------
# Attempts: preservation, concurrency, volatile roots
# ---------------------------------------------------------------------------

def test_failed_attempt_preserved_byte_identical(work_dir, fx_layout,
                                                fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    # Attempt 1 fails at dependency probing: the bare venv under the
    # root has no pytest (broken interpreter environment).
    with pytest.raises(stage1.q3_env.EnvironmentNotReady):
        qualify(root, fx_layout, fx_pool, boot="boot-B",
                python=fx_python(root, with_pytest=False))
    assert not (root / stage1.RECEIPT_NAME).exists()
    attempt1 = root / stage1.ATTEMPTS_DIR / "000001"
    before = {p.relative_to(root).as_posix(): p.read_bytes()
              for p in sorted(attempt1.rglob("*")) if p.is_file()}
    assert before
    # Attempt 2 (repaired environment) goes green; attempt 1 untouched.
    result = qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert result["status"] == "frozen"
    after = {rel: (root / rel).read_bytes() for rel in before}
    assert after == before
    assert (root / stage1.ATTEMPTS_DIR / "000002").is_dir()


def test_isolated_venv_missing_dependency_fails_at_admission(work_dir,
                                                            fx_layout,
                                                            fx_pool):
    """Genuinely isolated fixture venv: no .pth exposure, installs
    disabled. pytest is unavailable, so qualification fails at
    dependency admission -- before any repo baseline executes and
    before any receipt freezes. No network pip install is involved;
    the failure evidence is preserved."""
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    bare = fx_python(root, with_pytest=False)
    # The venv is genuinely isolated: pytest is not importable.
    probe = subprocess.run([bare, "-c", "import pytest"],
                           capture_output=True, timeout=60)
    assert probe.returncode != 0
    with pytest.raises(stage1.q3_env.EnvironmentNotReady,
                       match="installs disabled"):
        qualify(root, fx_layout, fx_pool, boot="boot-B", python=bare)
    # No receipt froze, no pool was cloned, no baseline ran.
    assert not (root / stage1.RECEIPT_NAME).exists()
    assert not (root / stage1.POOL_DIR_NAME).exists()
    attempt = root / stage1.ATTEMPTS_DIR / "000001"
    assert attempt.is_dir()
    evidence = attempt / "evidence"
    assert evidence.is_dir()
    assert list(evidence.glob("*-baseline-run-*.json")) == []
    # Failure evidence preserved (attempt dir is non-empty).
    assert any(p.is_file() for p in attempt.rglob("*"))


def test_second_qualify_is_verify_only(work_dir, fx_layout, fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    receipt_path = root / stage1.RECEIPT_NAME
    before = receipt_path.read_bytes()
    result = qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert result["status"] == "already_frozen"
    assert receipt_path.read_bytes() == before
    assert not (root / stage1.ATTEMPTS_DIR / "000002").exists()


def test_simultaneous_qualifier_excluded_before_mutation(work_dir, fx_layout,
                                                        fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    holder_src = (
        "import importlib.util, sys, time; "
        "spec = importlib.util.spec_from_file_location("
        "'holder', r'" + str(STAGE1_DIR / "env_qualify.py") + "'); "
        "m = importlib.util.module_from_spec(spec); "
        "sys.modules['holder'] = m; spec.loader.exec_module(m); "
        "from pathlib import Path; "
        "lk = m.stage1_lock(Path(r'" + str(root) + "')); "
        "lk.__enter__(); print('held', flush=True); time.sleep(30)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_src], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        line = holder.stdout.readline()
        assert "held" in line
        with pytest.raises(stage1.Stage1Locked):
            qualify(root, fx_layout, fx_pool, boot="boot-B")
        # Refused before any environment mutation.
        assert not (root / stage1.ATTEMPTS_DIR).exists()
        assert not (root / stage1.POOL_DIR_NAME).exists()
        assert not (root / stage1.RECEIPT_NAME).exists()
    finally:
        holder.kill()
        holder.wait(timeout=30)


def test_volatile_roots_rejected(work_dir, fx_layout):
    for volatile in ("/tmp", "/var/tmp", "/dev/shm"):
        root = Path(volatile) / "q5-stage1-volatile-probe"
        with pytest.raises(stage1.Stage1Error, match="volatile"):
            stage1.resolve_durable_root(root)
        with pytest.raises(stage1.Stage1Error, match="volatile"):
            stage1.arm_storage(root, boot_id_reader=lambda: "boot-A",
                               **fx_kwargs(fx_layout))
        assert not root.exists()


# ---------------------------------------------------------------------------
# Interpreter beneath the durable root
# ---------------------------------------------------------------------------

def test_interpreter_path_predicate():
    root = Path("/durable/root")
    assert qr.interpreter_path_under_root(
        "/durable/root/venv/bin/python", root)
    # Lexical .. normalization stays beneath the root...
    assert qr.interpreter_path_under_root(
        "/durable/root/venv/bin/../bin/python", root)
    # ...but a sibling prefix is not the root (no startswith trap).
    assert not qr.interpreter_path_under_root(
        "/durable/root-evil/venv/bin/python", root)
    assert not qr.interpreter_path_under_root("/usr/bin/python3", root)
    assert not qr.interpreter_path_under_root("definitely-not-a-python",
                                              root)


def test_interpreter_outside_durable_root_rejected(work_dir, fx_layout,
                                                   fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    with pytest.raises(stage1.Stage1Error,
                       match="not beneath the durable root"):
        qualify(root, fx_layout, fx_pool, boot="boot-B",
                python=sys.executable)
    # Refused before any environment mutation.
    assert not (root / stage1.ATTEMPTS_DIR).exists()
    assert not (root / stage1.POOL_DIR_NAME).exists()
    assert not (root / stage1.RECEIPT_NAME).exists()


def test_fixture_interpreter_lives_beneath_durable_root(work_dir, fx_layout,
                                                        fx_pool):
    # The enforcement is active on the green path: the venv python is
    # beneath the root and the receipt records that exact invocation.
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    receipt = json.loads((root / stage1.RECEIPT_NAME).read_bytes())
    assert receipt["python"].startswith(str(root) + os.sep)
    assert qr.interpreter_path_under_root(receipt["python"], root)
    # The verifier enforces it too.
    with pytest.raises(qr.ReceiptError,
                       match="not beneath the durable root"):
        verify_fixture(root, fx_layout, python=sys.executable)


# ---------------------------------------------------------------------------
# Storage witness state machine
# ---------------------------------------------------------------------------

def test_witness_missing_rejected(work_dir, fx_layout, fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    with pytest.raises(stage1.WitnessError, match="no storage witness"):
        qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert not (root / stage1.RECEIPT_NAME).exists()


def test_witness_same_boot_rejected(work_dir, fx_layout, fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    with pytest.raises(stage1.WitnessError, match="same boot"):
        qualify(root, fx_layout, fx_pool, boot="boot-A")
    assert not (root / stage1.RECEIPT_NAME).exists()


def test_witness_fs_changed_rejected(work_dir, fx_layout, fx_pool):
    # A valid-JSON mutation of a cross-checked witness field is rejected
    # before any environment work: the root was moved/copied to new
    # storage since arming, so its durability is unproven.
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    wpath = root / stage1.WITNESS_NAME
    witness = json.loads(wpath.read_bytes())
    witness["fs"] = {"st_dev": -1}
    wpath.write_bytes(json.dumps(witness).encode())
    with pytest.raises(stage1.WitnessError,
                       match="filesystem identity changed"):
        qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert not (root / stage1.RECEIPT_NAME).exists()
    assert not (root / stage1.POOL_DIR_NAME).exists()


def test_witness_tampered_rejected(work_dir, fx_layout, fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    # Corrupt the witness JSON: qualify must fail closed before any
    # environment work. Threat boundary (documented in the spec): the
    # witness demonstrates that bytes written beneath the durable root
    # were later observed intact under a different boot ID, with
    # filesystem/root identity cross-checks; it detects the tested
    # persistence and migration failures. It is not cryptographic
    # attestation against an actor with write access to the durable
    # root. The receipt permanently records the claimed boot IDs, so
    # an auditor sees exactly what was asserted.
    wpath = root / stage1.WITNESS_NAME
    wpath.write_bytes(b"{corrupted")
    with pytest.raises(stage1.WitnessError, match="corrupted"):
        qualify(root, fx_layout, fx_pool, boot="boot-B")
    assert not (root / stage1.RECEIPT_NAME).exists()


def test_witness_wrong_root_rejected(work_dir, fx_layout, fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    other = work_dir / "other"
    other.mkdir()
    (other / stage1.WITNESS_NAME).write_bytes(
        (root / stage1.WITNESS_NAME).read_bytes())
    with pytest.raises(stage1.WitnessError, match="bound to"):
        qualify(other, fx_layout, fx_pool, boot="boot-B")


def test_witness_schema_rejected(work_dir, fx_layout, fx_pool):
    root = work_dir / "droot"
    root.mkdir()
    arm(root, fx_layout, boot="boot-A")
    wpath = root / stage1.WITNESS_NAME
    witness = json.loads(wpath.read_bytes())
    witness["schema"] = "wrong"
    wpath.write_bytes(json.dumps(witness, sort_keys=True).encode())
    with pytest.raises(stage1.WitnessError, match="schema"):
        qualify(root, fx_layout, fx_pool, boot="boot-B")


def test_verifier_rejects_changed_live_filesystem_identity(
        work_dir, fx_layout, fx_pool, monkeypatch):
    """Falsifier: same durable-root pathname, same receipt bytes, same
    witness bytes, but a different CURRENT live filesystem identity --
    as if the qualified root were copied or remounted onto different
    storage at the same path after Stage 1. Verification must fail
    closed before any scientific contact. st_dev is not claimed to be
    cryptographic or globally stable storage identity; it is only the
    tested signal for a change of underlying storage between arming,
    qualification, and verification."""
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    verify_fixture(root, fx_layout)  # green first
    real_fs_identity = qr.fs_identity

    def moved_storage(path):
        ident = real_fs_identity(path)
        return {"st_dev": ident["st_dev"] + 1}

    monkeypatch.setattr(qr, "fs_identity", moved_storage)
    with pytest.raises(qr.ReceiptError,
                       match="filesystem identity changed"):
        verify_fixture(root, fx_layout)


def test_boot_transition_accepts_and_binds_witness(work_dir, fx_layout,
                                                   fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool,
                        boot_arm="boot-A", boot_qual="boot-B")
    witness = json.loads((root / stage1.WITNESS_NAME).read_bytes())
    assert witness["schema"] == qr.WITNESS_SCHEMA
    assert witness["armed_boot_id"] == "boot-A"
    assert witness["durable_root"] == str(root.resolve())
    receipt = json.loads((root / stage1.RECEIPT_NAME).read_bytes())
    sw = receipt["storage_witness"]
    assert sw["witness_digest"] == _sha(root / stage1.WITNESS_NAME)
    assert sw["armed_boot_id"] == "boot-A"
    assert sw["qualify_boot_id"] == "boot-B"
    assert sw["durable_root"] == str(root.resolve())


def test_stage2_work_dir_must_live_under_durable_root(work_dir, fx_layout,
                                                      fx_pool):
    root, _ = green_run(work_dir, fx_layout, fx_pool)
    inside = root / "stage2-work"
    inside.mkdir()
    verify_fixture(root, fx_layout, stage2_work_dir=inside)  # ok
    outside = work_dir / "elsewhere"
    outside.mkdir()
    with pytest.raises(qr.ReceiptError,
                       match="not beneath the qualified durable root"):
        verify_fixture(root, fx_layout, stage2_work_dir=outside)
