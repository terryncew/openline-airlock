"""RSI-006-Q6 code/environment binding: thin additive layer (prereg §9).

Mints schema airlock.rsi-006-q6.env-receipt.v1 (stage
q6-environment-qualification). Reuses Q5's pure read-only helpers
without modifying them; performs its own Q6 manifest schema check (Q5's
load/freeze hardcode the Q5 schema) and binds the Q6 code hashes in the
qualifier. Frozen Q5 module/manifest/receipt are never written to.
"""

import json
import os
import sys
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
if str(Q5_DIR) not in sys.path:
    sys.path.insert(0, str(Q5_DIR))

import environment_receipt as q5r  # noqa: E402

RECEIPT_SCHEMA = "airlock.rsi-006-q6.env-receipt.v1"
MANIFEST_SCHEMA = "airlock.rsi-006-q6.execution-manifest.v1"
STAGE = "q6-environment-qualification"
Q6_MANIFEST_RELPATH = (
    "experiments/rsi-006-q6-completion-recorder/execution_manifest.json")
_Q6P = "experiments/rsi-006-q6-completion-recorder/"
_Q5P = "experiments/rsi-006-q5-durable-substrate-qualification/"
Q6_REQUIRED_FILES = tuple(
    [_Q6P + n for n in ("q6_recorder.py", "q6_adapter.py", "q6_runner.py",
                        "q6_receipt.py", "q6_stage1.py")] +
    [_Q5P + n for n in ("execution_ledger.py", "q5_adapter.py",
                        "run_rsi_006_q5.py", "environment_receipt.py",
                        "stage1/env_qualify.py")] +
    ["experiments/rsi-006-q4-durable-transaction/stransaction.py",
     "experiments/rsi-006-q3-substrate-qualification/contact.py"])

# Qualification-critical implementation files the Q6 receipt must bind:
# the exact bytes of the code that decides the environment is
# admissible (mirrors Q5's QUALIFIER_CRITICAL_FILES pattern). The Q6
# execution surface itself is bound separately through the execution
# manifest, not here.
Q6_QUALIFIER_CRITICAL_FILES = (
    "q6_stage1.py",
    "q6_receipt.py",
    "execution_manifest.json",
)
Q6_RECEIPT_MODULE_REL = (
    "experiments/rsi-006-q6-completion-recorder/q6_receipt.py")


def q6_qualifier_code_hashes(root: Path) -> dict:
    """SHA-256 of each Q6 qualification-critical file (pure reads)."""
    root = Path(root)
    hashes = {}
    for rel in Q6_QUALIFIER_CRITICAL_FILES:
        p = root / rel
        if not p.is_file():
            raise q5r.ReceiptError(
                f"Q6 qualification-critical file missing: {p}")
        hashes[rel] = q5r.sha256_file(p)
    return hashes


def validate_q6_manifest(repo_root, manifest_path=None) -> dict:
    """Validate the Q6 manifest; hash every governed file (pure read).

    Returns the manifest binding the Q6 receipt freezes, mirroring the
    Q5 binding shape. Raises ManifestIncomplete/ManifestError.
    """
    repo_root = Path(repo_root)
    path = Path(manifest_path or repo_root / Q6_MANIFEST_RELPATH)
    try:
        manifest = json.loads(path.read_bytes())
    except (OSError, ValueError) as e:
        raise q5r.ManifestError(f"Q6 manifest unreadable: {e}") from None
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise q5r.ManifestError("Q6 manifest schema mismatch")
    code_files = manifest.get("code_files")
    if not isinstance(code_files, list) or not code_files:
        raise q5r.ManifestError("Q6 manifest has no code_files list")
    absent = [f for f in Q6_REQUIRED_FILES if f not in code_files]
    if absent:
        raise q5r.ManifestError(
            "Q6 manifest omits required files: " + ", ".join(absent))
    missing = [f for f in code_files if not (repo_root / f).is_file()]
    q3 = manifest.get("q3_receipt") or {}
    if not q3.get("path") or not q3.get("sha256"):
        raise q5r.ManifestError("Q6 manifest must pin the Q3 receipt")
    if not (repo_root / q3["path"]).is_file():
        missing.append(q3["path"])
    if missing:
        raise q5r.ManifestIncomplete(
            "Q6 manifest incomplete: " + ", ".join(sorted(set(missing))))
    live_q3 = q5r.sha256_file(repo_root / q3["path"])
    if live_q3 != q3["sha256"]:
        raise q5r.ManifestError("Q6 manifest Q3 receipt pin mismatch")
    return {"manifest_sha256": q5r.sha256_file(path),
            "files": {f: q5r.sha256_file(repo_root / f) for f in code_files},
            "q3_receipt_path": q3["path"], "q3_receipt_sha256": live_q3}


def build_q6_receipt(
    *,
    frozen_at: float,
    python: str,
    interpreter: dict,
    dep_lock: dict,
    repos: dict,
    vectors: dict,
    vector_hashes: dict,
    baseline_evidence: dict,
    attempt_id: str,
    attempt_evidence_files: dict,
    airlock_commit: str,
    manifest_binding: dict,
    qualifier_binding: dict,
    q3_code_hashes: dict,
    q4_relpath: str,
    q6_module_relpath: str,
    q6_module_sha256: str,
    witness_digest: str,
    witness_relpath: str,
    armed_boot_id: str,
    qualify_boot_id: str,
    armed_at: float,
    durable_root: str,
    witness_fs: dict,
    host_platform: str,
) -> dict:
    """Assemble the Q6 environment receipt dict (pure; no I/O).

    Full Stage-1 shape: everything the inherited Stage 2 runner needs
    (baseline vectors, repo tree hashes) plus the Q6 code/manifest
    bindings. Mirrors Q5's build_receipt field-for-field, with the Q6
    schema/stage and a ``q6`` module self-binding in place of Q5's.
    """
    manifest_files = manifest_binding["files"]
    return {
        "schema": RECEIPT_SCHEMA, "stage": STAGE, "frozen_at": frozen_at,
        "python": python,
        "interpreter": interpreter,
        "dependency_lock": dep_lock,
        "repos": repos,
        "baseline_vectors": vectors,
        "baseline_vector_hashes": vector_hashes,
        "baseline_evidence": baseline_evidence,
        "attempt": {
            "id": attempt_id,
            "evidence_files": attempt_evidence_files,
        },
        "airlock_commit": airlock_commit,
        "execution_manifest_sha256": manifest_binding["manifest_sha256"],
        "execution_manifest_files": manifest_files,
        "qualifier": {
            "source_commit": qualifier_binding["source_commit"],
            "code_hashes": dict(qualifier_binding["code_hashes"]),
        },
        "q3": {
            "receipt_path": manifest_binding["q3_receipt_path"],
            "receipt_sha256": manifest_binding["q3_receipt_sha256"],
            "code_hashes": q3_code_hashes,
        },
        "q4": {
            "stransaction_path": q4_relpath,
            "stransaction_sha256": manifest_files[q4_relpath],
        },
        "q6": {
            "receipt_module": q6_module_relpath,
            "receipt_module_sha256": q6_module_sha256,
        },
        "storage_witness": {
            "witness_path": witness_relpath,
            "witness_digest": witness_digest,
            "armed_boot_id": armed_boot_id,
            "qualify_boot_id": qualify_boot_id,
            "armed_at": armed_at,
            "durable_root": durable_root,
            "fs": witness_fs,
        },
        "host": {
            "platform": host_platform,
            "frozen_at": frozen_at,
        },
    }


def freeze_q6_receipt(path, receipt) -> dict:
    """Freeze the Q6 receipt exactly once (Q5 atomic pattern; no clobber)."""
    path = Path(path)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise q5r.ReceiptError("refusing to freeze: Q6 schema mismatch")
    if path.exists():
        raise q5r.ReceiptExists(f"Q6 receipt exists; refusing: {path}")
    data = q5r.canonical_bytes(receipt) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise q5r.ReceiptExists(f"Q6 receipt exists: {path}") from None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return receipt


def load_q6_receipt(path) -> dict:
    """Load a frozen Q6 receipt (pure read)."""
    try:
        receipt = json.loads(Path(path).read_bytes())
    except (OSError, ValueError) as e:
        raise q5r.ReceiptError(f"Q6 receipt unreadable: {e}") from None
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise q5r.ReceiptError("Q6 receipt schema mismatch")
    return receipt


def verify_q6_receipt(
    receipt_path,
    *,
    pool_dir,
    python: str,
    manifest_path,
    repo_root,
    q3_receipt_path,
    q3_code_dir,
    q4_path,
    durable_root,
    stage2_work_dir,
    manifest_required=None,
    qualifier_root=None,
) -> dict:
    """Verify every live binding against the frozen Q6 receipt.

    Mirrors Q5's verify_receipt check-for-check (12 checks), with the
    Q6 schema, the Q6 execution manifest, the Q6 qualifier root, and
    the Q6 receipt-module self-binding. Raises ReceiptError (or
    ManifestError) on any drift. Returns the receipt on success.
    Performs no baseline execution, no test runs, and no mutation.
    """
    receipt_path = Path(receipt_path)
    pool_dir = Path(pool_dir)
    manifest_path = Path(manifest_path)
    repo_root = Path(repo_root)
    q3_receipt_path = Path(q3_receipt_path)
    q3_code_dir = Path(q3_code_dir)
    q4_path = Path(q4_path)
    durable_root = Path(durable_root).resolve()
    stage2_work_dir = Path(stage2_work_dir).resolve()
    if manifest_required is None:
        manifest_required = Q6_REQUIRED_FILES

    if not q5r.interpreter_path_under_root(str(python), durable_root):
        raise q5r.ReceiptError(
            f"selected interpreter {python} is not beneath the durable "
            f"root {durable_root}")

    receipt = load_q6_receipt(receipt_path)

    # 1. Q6 execution manifest bytes and every governed file.
    binding = validate_q6_manifest(repo_root, manifest_path)
    if binding["manifest_sha256"] != receipt["execution_manifest_sha256"]:
        raise q5r.ReceiptError(
            "Q6 execution manifest bytes drifted since freeze")
    live_files = binding["files"]
    frozen_files = receipt["execution_manifest_files"]
    if set(live_files) != set(frozen_files):
        raise q5r.ReceiptError(
            "Q6 execution manifest file set changed since freeze: "
            f"live={sorted(live_files)} frozen={sorted(frozen_files)}")
    drifted = [f for f in live_files if live_files[f] != frozen_files[f]]
    if drifted:
        raise q5r.ReceiptError(
            f"Q6 manifest-governed execution files drifted: {drifted}")
    # The required-file floor is enforced inside validate_q6_manifest;
    # manifest_required is accepted for signature parity with Q5.
    _ = manifest_required

    # 2. Q6 qualifier implementation bytes.
    if qualifier_root is None:
        qualifier_root = Q6_DIR
    live_qualifier = q6_qualifier_code_hashes(Path(qualifier_root))
    frozen_qualifier = receipt["qualifier"]["code_hashes"]
    if live_qualifier != frozen_qualifier:
        bad = [r for r in live_qualifier
               if live_qualifier[r] != frozen_qualifier.get(r)]
        raise q5r.ReceiptError(
            f"Q6 qualifier implementation drifted since freeze: {bad}")

    # 3. OpenLine/Airlock source commit.
    if q5r.git_head(repo_root) != receipt["airlock_commit"]:
        raise q5r.ReceiptError(
            "airlock source commit drift: "
            f"receipt={receipt['airlock_commit']} "
            f"live={q5r.git_head(repo_root)}")

    # 4. Frozen Q3 receipt and its complete code-hash map.
    q3 = receipt["q3"]
    if q5r.sha256_file(q3_receipt_path) != q3["receipt_sha256"]:
        raise q5r.ReceiptError("frozen Q3 environment receipt file drifted")
    q3_live = json.loads(q3_receipt_path.read_bytes())
    if q3_live.get("schema") != "airlock.rsi-006-q3.env-receipt.v1":
        raise q5r.ReceiptError("frozen Q3 receipt schema unexpected")
    for name, frozen_hash in q3["code_hashes"].items():
        live = q5r.sha256_file(q3_code_dir / name)
        if live != frozen_hash:
            raise q5r.ReceiptError(f"Q3 code file drifted: {name}")

    # 5. Q4 transaction code.
    if q5r.sha256_file(q4_path) != receipt["q4"]["stransaction_sha256"]:
        raise q5r.ReceiptError("Q4 stransaction.py drifted since freeze")

    # 6. Q6 receipt/binding module (this file).
    if q5r.sha256_file(Path(__file__)) != \
            receipt["q6"]["receipt_module_sha256"]:
        raise q5r.ReceiptError("Q6 q6_receipt.py drifted since freeze")

    # 7. Selected interpreter and dependency lock (probed, never
    #    trusted from the running process).
    try:
        live_interp = q5r.interpreter_identity(python)
    except OSError as oe:
        raise q5r.ReceiptError(
            f"cannot probe selected interpreter {python}: {oe}") from None
    if live_interp != receipt["interpreter"]:
        raise q5r.ReceiptError(
            f"selected interpreter drift: receipt={receipt['interpreter']} "
            f"live={live_interp}")
    try:
        live_lock = q5r.dependency_lock(
            python, tuple(sorted(receipt["dependency_lock"])))
    except OSError as oe:
        raise q5r.ReceiptError(
            f"cannot probe dependency lock in {python}: {oe}") from None
    if live_lock != receipt["dependency_lock"]:
        raise q5r.ReceiptError(
            f"dependency lock drift: receipt={receipt['dependency_lock']} "
            f"live={live_lock}")

    # 8. Repository pins, checkout SHAs, and tree hashes.
    for name, frozen in receipt["repos"].items():
        root = pool_dir / name
        if not root.is_dir():
            raise q5r.ReceiptError(f"repo missing from pool: {name}")
        live_sha = q5r.repo_checkout_sha(root)
        if live_sha != frozen["checkout_sha"]:
            raise q5r.ReceiptError(
                f"repo {name} checkout drift: "
                f"receipt={frozen['checkout_sha']} live={live_sha}")
        live_tree = q5r.tree_hash(root)
        if live_tree != frozen["tree_hash"]:
            raise q5r.ReceiptError(f"repo {name} tree drift since freeze")

    # 9. Baseline-vector self-consistency.
    for name, vec in receipt["baseline_vectors"].items():
        expect = receipt["baseline_vector_hashes"][name]
        if q5r.sha256_bytes(q5r.canonical_bytes(vec)) != expect:
            raise q5r.ReceiptError(
                f"baseline vector hash mismatch for {name}: receipt "
                "tampered")
        ev = receipt["baseline_evidence"][name]
        if ev["vector_sha256"] != expect:
            raise q5r.ReceiptError(
                f"baseline evidence vector hash mismatch for {name}")

    # 10. Attempt evidence binding.
    for rel, frozen_hash in receipt["attempt"]["evidence_files"].items():
        p = durable_root / rel
        if not p.is_file():
            raise q5r.ReceiptError(f"attempt evidence file missing: {rel}")
        if q5r.sha256_file(p) != frozen_hash:
            raise q5r.ReceiptError(f"attempt evidence file drifted: {rel}")

    # 11. Durable-storage witness.
    wit = receipt["storage_witness"]
    if durable_root != Path(wit["durable_root"]):
        raise q5r.ReceiptError(
            f"durable root binding drift: receipt={wit['durable_root']} "
            f"live={durable_root}")
    witness_path = durable_root / wit["witness_path"]
    if not witness_path.is_file():
        raise q5r.ReceiptError("storage witness missing from durable root")
    witness_bytes = witness_path.read_bytes()
    if q5r.sha256_bytes(witness_bytes) != wit["witness_digest"]:
        raise q5r.ReceiptError("storage witness bytes drifted since freeze")
    try:
        witness = json.loads(witness_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise q5r.ReceiptError(
            f"storage witness corrupted: {e}") from None
    if witness.get("schema") != q5r.WITNESS_SCHEMA:
        raise q5r.ReceiptError(
            f"storage witness schema mismatch: {witness.get('schema')!r}")
    for field in ("durable_root", "armed_boot_id", "armed_at"):
        if witness.get(field) != wit[field]:
            raise q5r.ReceiptError(
                f"storage witness field {field!r} differs from the "
                f"frozen receipt: witness={witness.get(field)!r} "
                f"receipt={wit[field]!r}")
    if witness.get("fs") != wit["fs"]:
        raise q5r.ReceiptError(
            "storage witness filesystem identity differs from the "
            "frozen receipt")
    live_fs = q5r.fs_identity(durable_root)
    if live_fs != wit["fs"]:
        raise q5r.ReceiptError(
            f"durable root filesystem identity changed since freeze: "
            f"receipt={wit['fs']} live={live_fs}; the qualified root was "
            "moved or remounted onto different storage")

    # 12. The Stage 2 work directory must resolve beneath the
    #     receipt-bound durable root.
    if not (stage2_work_dir == durable_root
            or durable_root in stage2_work_dir.parents):
        raise q5r.ReceiptError(
            f"Stage 2 work dir {stage2_work_dir} is not beneath the "
            f"qualified durable root {durable_root}")

    return receipt


def verify_q6_production_receipt(
    receipt_path,
    *,
    pool_dir,
    python: str,
    stage2_work_dir,
) -> dict:
    """Verify a production Q6 receipt with repo-relative paths derived.

    All manifest/Q3/Q4 locations follow the production layout under the
    repository root containing this module. Performs no baselines, no
    mutation, and no scientific execution: it re-probes the live
    environment and compares against the frozen receipt.
    """
    repo_root = Q6_DIR.parent.parent
    return verify_q6_receipt(
        receipt_path,
        pool_dir=pool_dir,
        python=python,
        manifest_path=Q6_DIR / "execution_manifest.json",
        repo_root=repo_root,
        q3_receipt_path=repo_root / "proofs" / "rsi-006-q3"
        / "environment-receipt.json",
        q3_code_dir=repo_root / "experiments"
        / "rsi-006-q3-substrate-qualification",
        q4_path=repo_root / "experiments"
        / "rsi-006-q4-durable-transaction" / "stransaction.py",
        durable_root=Path(receipt_path).parent,
        stage2_work_dir=stage2_work_dir,
    )
