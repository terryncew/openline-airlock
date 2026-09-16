"""Q6 Stage-1 qualification binding fixtures (Gate 2A).

Covers the full Gate-2 contract: Q6 manifest accepted / Q5 manifest
rejected; exact Q6 receipt schema; create-once freeze; receipt tamper
refusal; manifest and governed-code drift; qualifier and
source-commit drift; interpreter/dependency drift; repo checkout/tree
drift; Q3/Q4 drift; baseline-vector tamper; missing/changed attempt
evidence; witness and filesystem drift; Stage-2 work-dir escape;
Stage2Runner consumption of the verified receipt; and the
no-scientific-contact guard.

The verifier's live probes (interpreter identity, dependency lock,
repo checkout/tree, filesystem identity) are monkeypatched to canned
values, and the receipt is built from those same canned values, so
every drift test proves the comparison itself refuses. The probes are
Q5's frozen, separately tested code; these fixtures test the Q6
comparison logic, not the probes.
"""

import ast
import copy
import json
import sys
from pathlib import Path

import pytest

Q6_DIR = Path(__file__).resolve().parent.parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q5_STAGE1 = Q5_DIR / "stage1"
REPO_ROOT = Q6_DIR.parent.parent
Q3_DIR = REPO_ROOT / "experiments" / "rsi-006-q3-substrate-qualification"

for _p in (str(Q5_STAGE1), str(Q5_DIR), str(Q6_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_qualify as q5stage  # noqa: E402
import environment_receipt as q5r  # noqa: E402
import q6_receipt as q6r  # noqa: E402
import q6_stage1  # noqa: E402

FAKE_INTERP = {"executable": "/durable/bin/python3",
               "version": "3.11.9",
               "implementation": "CPython"}
FAKE_LOCK = {"numpy": "1.26.4", "scipy": "1.11.4"}
FAKE_CHECKOUT = "a" * 40
FAKE_TREE = "b" * 64
FAKE_FS = {"st_dev": 12345, "fs_type": "ext4"}
Q4_REL = "experiments/rsi-006-q4-durable-transaction/stransaction.py"


@pytest.fixture
def q6env(work_dir, monkeypatch):
    """A complete, self-consistent Q6 qualification fixture."""
    root = work_dir / "durable"
    root.mkdir()
    pool_dir = root / "repo-pool"
    pool_dir.mkdir()
    repo_name = "rsi-006-q3-substrate-qualification"
    (pool_dir / repo_name).mkdir()

    monkeypatch.setattr(q5r, "interpreter_identity",
                        lambda py: dict(FAKE_INTERP))
    monkeypatch.setattr(q5r, "dependency_lock",
                        lambda py, req: dict(FAKE_LOCK))
    monkeypatch.setattr(q5r, "interpreter_path_under_root",
                        lambda py, r: True)
    monkeypatch.setattr(q5r, "repo_checkout_sha",
                        lambda p: FAKE_CHECKOUT)
    monkeypatch.setattr(q5r, "tree_hash", lambda p: FAKE_TREE)
    monkeypatch.setattr(q5r, "fs_identity", lambda p: dict(FAKE_FS))

    manifest_path = Q6_DIR / "execution_manifest.json"
    binding = q6r.validate_q6_manifest(REPO_ROOT, manifest_path)
    qualifier_hashes = q6r.q6_qualifier_code_hashes(Q6_DIR)
    head = q5r.git_head(REPO_ROOT)
    q3_receipt_path = (REPO_ROOT / "proofs" / "rsi-006-q3"
                       / "environment-receipt.json")
    q3_receipt = json.loads(q3_receipt_path.read_bytes())

    armed_at = 1726000000.0
    witness = {
        "schema": q5r.WITNESS_SCHEMA,
        "durable_root": str(root),
        "armed_boot_id": "boot-ARMED-001",
        "armed_at": armed_at,
        "fs": dict(FAKE_FS),
    }
    witness_path = root / q5stage.WITNESS_NAME
    witness_path.write_bytes(q5r.canonical_bytes(witness))
    witness_digest = q5r.sha256_file(witness_path)

    attempt_id = "attempt-001"
    ev_dir = root / "attempts" / attempt_id / "evidence"
    ev_dir.mkdir(parents=True)
    ev1 = ev_dir / "baseline-run1.json"
    ev1.write_text(json.dumps({"run": 1}))
    ev_rel = ev1.relative_to(root).as_posix()
    evidence_files = {ev_rel: q5r.sha256_file(ev1)}

    vectors = {repo_name: {"n_tests": 7, "passed": 7}}
    vector_hashes = {
        n: q5r.sha256_bytes(q5r.canonical_bytes(v))
        for n, v in vectors.items()
    }
    baseline_evidence = {
        repo_name: {
            "n_tests": 7,
            "deterministic": True,
            "vector_sha256": vector_hashes[repo_name],
            "launch_sha256": {"run1": "c" * 64, "run2": "d" * 64},
            "launch_files": {"run1": "x/run1.json",
                             "run2": "x/run2.json"},
        }
    }

    receipt = q6r.build_q6_receipt(
        frozen_at=1726000001.0,
        python="/durable/bin/python3",
        interpreter=dict(FAKE_INTERP),
        dep_lock=dict(FAKE_LOCK),
        repos={repo_name: {
            "url": "https://example.invalid/repo.git",
            "pin": FAKE_CHECKOUT,
            "checkout_sha": FAKE_CHECKOUT,
            "tree_hash": FAKE_TREE,
        }},
        vectors=vectors,
        vector_hashes=vector_hashes,
        baseline_evidence=baseline_evidence,
        attempt_id=attempt_id,
        attempt_evidence_files=dict(evidence_files),
        airlock_commit=head,
        manifest_binding=binding,
        qualifier_binding={"source_commit": head,
                           "code_hashes": qualifier_hashes},
        q3_code_hashes=dict(q3_receipt["code_hashes"]),
        q4_relpath=Q4_REL,
        q6_module_relpath=q6r.Q6_RECEIPT_MODULE_REL,
        q6_module_sha256=q5r.sha256_file(
            REPO_ROOT / q6r.Q6_RECEIPT_MODULE_REL),
        witness_digest=witness_digest,
        witness_relpath=q5stage.WITNESS_NAME,
        armed_boot_id="boot-ARMED-001",
        qualify_boot_id="boot-QUALIFY-002",
        armed_at=armed_at,
        durable_root=str(root),
        witness_fs=dict(FAKE_FS),
        host_platform="Linux-test",
    )
    receipt_path = root / q6_stage1.Q6_RECEIPT_NAME
    q6r.freeze_q6_receipt(receipt_path, receipt)

    def _verify(rp=None, stage2=None):
        return q6r.verify_q6_receipt(
            receipt_path if rp is None else rp,
            pool_dir=pool_dir,
            python="/durable/bin/python3",
            manifest_path=manifest_path,
            repo_root=REPO_ROOT,
            q3_receipt_path=q3_receipt_path,
            q3_code_dir=Q3_DIR,
            q4_path=REPO_ROOT / Q4_REL,
            durable_root=root,
            stage2_work_dir=root if stage2 is None else stage2,
        )

    return {
        "root": root, "pool_dir": pool_dir, "repo_name": repo_name,
        "receipt": receipt, "receipt_path": receipt_path,
        "verify": _verify, "binding": binding,
        "manifest_path": manifest_path,
        "q3_receipt_path": q3_receipt_path,
        "evidence_file": ev1, "evidence_rel": ev_rel,
    }


def _refrozen_bad(env, mutate):
    """Freeze a mutated copy of the fixture receipt; return its path."""
    bad = copy.deepcopy(env["receipt"])
    mutate(bad)
    rp = env["root"] / "bad-receipt.json"
    q6r.freeze_q6_receipt(rp, bad)
    return rp


def _qualifier_provenance():
    return {"root": str(Q6_DIR), "source_commit": "fixture-commit",
            "code_hashes": q6r.q6_qualifier_code_hashes(Q6_DIR)}


# --- manifest / preflight ------------------------------------------

def test_q6_preflight_accepts_q6_manifest(q6env):
    pf = q6_stage1.q6_preflight(
        REPO_ROOT, Q3_DIR, q6env["q3_receipt_path"],
        REPO_ROOT / Q4_REL, q6env["manifest_path"],
        qualifier_provenance=_qualifier_provenance())
    assert (pf["manifest_binding"]["manifest_sha256"]
            == q6env["binding"]["manifest_sha256"])
    assert (pf["qualifier_binding"]["source_commit"]
            == "fixture-commit")
    assert (set(pf["qualifier_binding"]["code_hashes"])
            == set(q6r.Q6_QUALIFIER_CRITICAL_FILES))


def test_q6_preflight_rejects_q5_manifest(q6env):
    q5_manifest = Q5_DIR / "execution_manifest.json"
    assert q5_manifest.is_file()
    with pytest.raises(q5stage.ManifestLockedError):
        q6_stage1.q6_preflight(
            REPO_ROOT, Q3_DIR, q6env["q3_receipt_path"],
            REPO_ROOT / Q4_REL, q5_manifest,
            qualifier_provenance=_qualifier_provenance())


# --- receipt shape / freeze -----------------------------------------

def test_build_q6_receipt_exact_schema(q6env):
    r = q6env["receipt"]
    assert r["schema"] == "airlock.rsi-006-q6.env-receipt.v1"
    assert r["stage"] == "q6-environment-qualification"
    for key in ("frozen_at", "python", "interpreter",
                "dependency_lock", "repos", "baseline_vectors",
                "baseline_vector_hashes", "baseline_evidence",
                "attempt", "airlock_commit",
                "execution_manifest_sha256",
                "execution_manifest_files", "qualifier", "q3", "q4",
                "q6", "storage_witness", "host"):
        assert key in r, key
    assert (r["q6"]["receipt_module_sha256"]
            == q5r.sha256_file(Path(q6r.__file__)))
    assert r["q6"]["receipt_module"] == q6r.Q6_RECEIPT_MODULE_REL
    assert r["q4"]["stransaction_sha256"] == \
        r["execution_manifest_files"][Q4_REL]


def test_freeze_create_once(q6env):
    with pytest.raises(q5r.ReceiptError):
        q6r.freeze_q6_receipt(q6env["receipt_path"],
                             q6env["receipt"])


def test_receipt_tamper_refusal(q6env):
    verified = q6env["verify"]()
    assert verified["schema"] == q6r.RECEIPT_SCHEMA
    raw = bytearray(q6env["receipt_path"].read_bytes())
    raw[50] ^= 0xFF
    q6env["receipt_path"].write_bytes(bytes(raw))
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"]()


# --- drift refusals ---------------------------------------------------

def test_manifest_drift_refusal(q6env):
    rp = _refrozen_bad(
        q6env, lambda b: b.update(execution_manifest_sha256="0" * 64))
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_governed_file_drift_refusal(q6env):
    def mutate(b):
        b["execution_manifest_files"][Q4_REL] = "0" * 64
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_qualifier_drift_refusal(q6env):
    def mutate(b):
        b["qualifier"]["code_hashes"]["q6_stage1.py"] = "0" * 64
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_source_commit_drift_refusal(q6env):
    rp = _refrozen_bad(
        q6env, lambda b: b.update(airlock_commit="0" * 40))
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_interpreter_drift_refusal(q6env):
    def mutate(b):
        b["interpreter"]["version"] = "9.9.9"
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_dependency_drift_refusal(q6env):
    def mutate(b):
        b["dependency_lock"]["numpy"] = "0.0.0"
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_repo_drift_refusal(q6env):
    def mutate(b):
        b["repos"][q6env["repo_name"]]["tree_hash"] = "0" * 64
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_q3_code_drift_refusal(q6env):
    def mutate(b):
        name = next(iter(b["q3"]["code_hashes"]))
        b["q3"]["code_hashes"][name] = "0" * 64
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_q4_drift_refusal(q6env):
    rp = _refrozen_bad(
        q6env, lambda b: b["q4"].update(stransaction_sha256="0" * 64))
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_baseline_vector_tamper_refusal(q6env):
    def mutate(b):
        b["baseline_vectors"][q6env["repo_name"]]["passed"] = 0
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_attempt_evidence_missing_refusal(q6env):
    q6env["evidence_file"].unlink()
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"]()


def test_attempt_evidence_changed_refusal(q6env):
    def mutate(b):
        b["attempt"]["evidence_files"][q6env["evidence_rel"]] = \
            "f" * 64
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_witness_drift_refusal(q6env):
    def mutate(b):
        b["storage_witness"]["witness_digest"] = "e" * 64
    rp = _refrozen_bad(q6env, mutate)
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](rp=rp)


def test_witness_fs_drift_refusal(q6env, monkeypatch):
    monkeypatch.setattr(q5r, "fs_identity",
                        lambda p: {"st_dev": 999, "fs_type": "xfs"})
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"]()


def test_stage2_workdir_escape_refusal(q6env):
    with pytest.raises(q5r.ReceiptError):
        q6env["verify"](stage2=Path("/tmp"))


# --- Stage2Runner consumption -----------------------------------------

def test_stage2_runner_consumes_q6_receipt(q6env):
    import run_rsi_006_q5
    env = q6env
    name = env["repo_name"]

    def verifier():
        return (env["verify"](),
                q5r.receipt_sha256(env["receipt_path"]))

    runner = run_rsi_006_q5.Stage2Runner(
        stage2_dir=env["root"] / "stage2",
        pool={name: {"package_dir": str(env["pool_dir"] / name)}},
        pool_dir=env["pool_dir"],
        budgets={name: (2, 2, 60.0, 60.0)},
        python="/durable/bin/python3",
        receipt_path=env["receipt_path"],
        workers=1,
        code_hashes={},
        receipt_verifier=verifier,
    )
    runner._verify_and_bind_receipt()
    assert (runner._baselines[name]
            == env["receipt"]["baseline_vectors"][name])
    assert (runner._tree_hash_pre[name]
            == env["receipt"]["repos"][name]["tree_hash"])


# --- no scientific contact ----------------------------------------------

def test_no_scientific_contact_surface():
    src = (Q6_DIR / "q6_stage1.py").read_text()
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    forbidden = {"q5_adapter", "execution_ledger", "stransaction",
                 "contact", "q6_runner", "q6_adapter", "subprocess"}
    assert not (imported & forbidden), \
        f"q6_stage1 imports forbidden modules: {imported & forbidden}"
    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)
    assert not (used_names & {"ScientificTransaction", "ContactGate",
                              "Popen"}), \
        "q6_stage1 references scientific-contact machinery"
