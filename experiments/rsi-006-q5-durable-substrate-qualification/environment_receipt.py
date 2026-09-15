"""RSI-006-Q5 environment receipt: freeze and verify.

Schema: ``airlock.rsi-006-q5.env-receipt.v1``

This module is used both by Stage 1 (``stage1/env_qualify.py``) to freeze
the qualification receipt and by the future Q5 Stage 2 runner to verify
the frozen receipt BEFORE any scientific contact. Verification performs
no baseline execution, no test runs, and no mutation work of any kind:
it re-probes the live environment and fails closed on any drift.

Binding rule (inherited from Q3): the receipt binds the *selected*
interpreter, never the process running the check. Interpreter identity
and dependency-lock probes interrogate the selected executable through
an observable subprocess.

Create-once freeze: ``freeze_receipt`` uses an atomic hard-link so an
existing frozen receipt can never be overwritten. If a receipt already
exists, qualification must not rerun baselines or repair the
environment -- it may only verify the already-frozen receipt or fail
closed.

Q3 is read-only here. This module reuses Q3's already-tested
``receipt`` helpers (canonical serialization, hashing, interpreter and
lock probes, checkout/tree hashing) without calling Q3's
``qualify_environment()`` -- Q5 freezes its own receipt schema.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"

sys.path.insert(0, str(Q3_DIR))
import receipt as _q3_receipt  # noqa: E402  (frozen helpers; Q3 is read-only)

RECEIPT_SCHEMA = "airlock.rsi-006-q5.env-receipt.v1"
MANIFEST_SCHEMA = "airlock.rsi-006-q5.execution-manifest.v1"
WITNESS_SCHEMA = "airlock.rsi-006-q5.storage-witness.v1"

# Minimum code surface the production execution manifest must enumerate.
# ``run_rsi_006_q5.py`` does not exist yet: until it does, the production
# qualifier refuses before any environment mutation. Paths are relative
# to the repository root.
REQUIRED_MANIFEST_FILES = (
    "experiments/rsi-006-q5-durable-substrate-qualification/execution_ledger.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/q5_adapter.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/environment_receipt.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/stage1/env_qualify.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/run_rsi_006_q5.py",
    "experiments/rsi-006-q4-durable-transaction/stransaction.py",
)

# Qualification-critical implementation files the receipt must bind.
# The frozen receipt binds the exact *bytes* of the code that decided
# the environment was admissible -- not just the source commit SHA,
# because a dirty working tree can execute bytes that are not in that
# commit. Paths are relative to the experiment directory (EXP_DIR).
# Kept distinct from the execution-manifest binding on purpose: the
# qualifier binding answers "what decided admissibility", the
# execution-manifest binding answers "what may later perform
# scientific contact".
QUALIFIER_CRITICAL_FILES = (
    "stage1/env_qualify.py",
    "environment_receipt.py",
    "execution_manifest.json",
)


def qualifier_code_hashes(root: Path) -> dict:
    """SHA-256 of each qualification-critical file (pure reads).

    Raises ReceiptError when a critical file is missing: a qualifier
    that cannot even locate its own implementation must not freeze.
    """
    root = Path(root)
    hashes = {}
    for rel in QUALIFIER_CRITICAL_FILES:
        p = root / rel
        if not p.is_file():
            raise ReceiptError(
                f"qualification-critical file missing: {p}")
        hashes[rel] = sha256_file(p)
    return hashes

# Re-exported frozen helpers (single implementation lives in Q3).
canonical_bytes = _q3_receipt.canonical_bytes
sha256_bytes = _q3_receipt.sha256_bytes
sha256_file = _q3_receipt.sha256_file
interpreter_identity = _q3_receipt.interpreter_identity
dependency_lock = _q3_receipt.dependency_lock
tree_hash = _q3_receipt.tree_hash
repo_checkout_sha = _q3_receipt.repo_checkout_sha


def interpreter_path_under_root(python: str, root: Path) -> bool:
    """True iff the selected interpreter *invocation path* lives beneath ``root``.

    Pure check, no I/O beyond PATH lookup. The path is normalized
    lexically on purpose: a venv's ``bin/python`` is typically a
    symlink to a base interpreter outside the venv, and resolving it
    would reject every ordinary venv. Lexical containment proves the
    invocation path is beneath the root -- it does not prove the
    symlink target is. The resolved interpreter identity (resolved
    executable, version, implementation) is bound separately in the
    receipt and re-verified; that binding is what detects a swapped or
    moved interpreter.
    """
    p = Path(str(python))
    if not p.is_absolute():
        found = shutil.which(str(python))
        if found is None:
            return False
        p = Path(found)
    norm = Path(os.path.normpath(p))
    root = Path(root)
    return norm == root or root in norm.parents


class ReceiptError(RuntimeError):
    """The Q5 environment receipt is missing or no longer matches."""


class ReceiptExists(ReceiptError):
    """A frozen receipt already exists; refusing to overwrite it."""


class ManifestError(RuntimeError):
    """The execution manifest is invalid."""


class ManifestIncomplete(ManifestError):
    """The execution manifest names files that are absent or unpinned."""

    def __init__(self, message: str, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = list(missing or [])


# ---------------------------------------------------------------------------
# Execution manifest
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> dict:
    """Load and schema-check an execution manifest (pure read)."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise ManifestError(f"execution manifest not found: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ManifestError(f"execution manifest unparseable: {e}") from None
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ManifestError(
            f"execution manifest schema mismatch: {manifest.get('schema')!r} "
            f"(want {MANIFEST_SCHEMA!r})")
    return manifest


def validate_manifest(manifest_path: Path, repo_root: Path, *,
                    required: tuple[str, ...] = REQUIRED_MANIFEST_FILES
                    ) -> dict:
    """Validate the manifest and hash every file it governs (pure read).

    Returns the manifest binding the receipt freezes:
    ``{"manifest_sha256", "files": {relpath: sha256},
    "q3_receipt_path", "q3_receipt_sha256"}``.

    ``required`` is the minimum execution-surface file set the manifest
    must enumerate; production callers use the default. Tests inject
    their fixture file set through this internal parameter (there is no
    CLI override by design).

    Raises ManifestIncomplete when any required or listed file is absent,
    and ManifestError when the manifest is malformed or its pinned Q3
    receipt hash does not match the live file. Performs no mutation.
    """
    manifest_path = Path(manifest_path)
    repo_root = Path(repo_root)
    manifest = load_manifest(manifest_path)

    code_files = manifest.get("code_files")
    if not isinstance(code_files, list) or not code_files:
        raise ManifestError("execution manifest has no code_files list")
    absent_required = [f for f in required if f not in code_files]
    if absent_required:
        raise ManifestError(
            "execution manifest omits required execution-surface files: "
            + ", ".join(absent_required))

    missing = [f for f in code_files if not (repo_root / f).is_file()]
    q3 = manifest.get("q3_receipt") or {}
    q3_rel = q3.get("path")
    q3_pin = q3.get("sha256")
    if not q3_rel or not q3_pin:
        raise ManifestError(
            "execution manifest must pin the frozen Q3 environment receipt")
    if not (repo_root / q3_rel).is_file():
        missing.append(q3_rel)
    if missing:
        raise ManifestIncomplete(
            "execution manifest incomplete: required files absent: "
            + ", ".join(sorted(set(missing))),
            missing=sorted(set(missing)))

    live_q3_sha = sha256_file(repo_root / q3_rel)
    if live_q3_sha != q3_pin:
        raise ManifestError(
            f"pinned Q3 receipt hash mismatch: manifest pins {q3_pin}, "
            f"live file hashes to {live_q3_sha}")

    return {
        "manifest_sha256": sha256_file(manifest_path),
        "files": {f: sha256_file(repo_root / f) for f in code_files},
        "q3_receipt_path": q3_rel,
        "q3_receipt_sha256": live_q3_sha,
    }


# ---------------------------------------------------------------------------
# Receipt freeze / load
# ---------------------------------------------------------------------------

def build_receipt(
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
    q5_module_relpath: str,
    q5_module_sha256: str,
    witness_digest: str,
    witness_relpath: str,
    armed_boot_id: str,
    qualify_boot_id: str,
    armed_at: float,
    durable_root: str,
    witness_fs: dict,
    host_platform: str,
) -> dict:
    """Assemble the Q5 environment receipt dict (pure; no I/O)."""
    manifest_files = manifest_binding["files"]
    return {
        "schema": RECEIPT_SCHEMA,
        "stage": "q5-environment-qualification",
        "frozen_at": frozen_at,
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
            # What decided the environment was admissible. Deliberately
            # separate from the execution-manifest binding, which governs
            # what may later perform scientific contact.
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
        "q5": {
            "receipt_module": q5_module_relpath,
            "receipt_module_sha256": q5_module_sha256,
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


def freeze_receipt(path: Path, receipt: dict) -> dict:
    """Atomically freeze a receipt exactly once; never overwrite.

    The receipt bytes are written to a temp file, fsynced, then hard-
    linked to the final path: the link fails if the path already exists,
    so a frozen receipt can never be replaced, even by a concurrent
    process. Raises ReceiptExists without touching the existing file.
    """
    path = Path(path)
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ReceiptError(
            f"refusing to freeze receipt with schema "
            f"{receipt.get('schema')!r}")
    if path.exists():
        raise ReceiptExists(
            f"frozen receipt already exists; refusing to overwrite: {path}")
    data = canonical_bytes(receipt) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, path)
    except FileExistsError:
        raise ReceiptExists(
            f"frozen receipt already exists; refusing to overwrite: {path}"
        ) from None
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


def load_receipt(path: Path) -> dict:
    """Load a frozen receipt (pure read)."""
    path = Path(path)
    if not path.is_file():
        raise ReceiptError(f"Q5 environment receipt not found: {path}")
    try:
        receipt = json.loads(path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ReceiptError(f"Q5 environment receipt unparseable: {e}") from None
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ReceiptError(
            f"Q5 environment receipt schema mismatch: "
            f"{receipt.get('schema')!r} (want {RECEIPT_SCHEMA!r})")
    return receipt


def receipt_sha256(path: Path) -> str:
    return sha256_file(Path(path))


def git_head(repo_root: Path) -> str:
    """Exact source commit SHA used for qualification (pure read)."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise ReceiptError(
            f"cannot determine airlock source commit at {repo_root}: "
            f"{(out.stdout + out.stderr).strip()[:200]}")
    return out.stdout.strip()


# ---------------------------------------------------------------------------
# Receipt verification (no execution, no mutation)
# ---------------------------------------------------------------------------

def verify_receipt(
    receipt_path: Path,
    *,
    pool_dir: Path,
    python: str,
    manifest_path: Path,
    repo_root: Path,
    q3_receipt_path: Path,
    q3_code_dir: Path,
    q4_path: Path,
    durable_root: Path,
    stage2_work_dir: Path,
    manifest_required: tuple[str, ...] | None = None,
    qualifier_root: Path | None = None,
) -> dict:
    """Verify every live binding against the frozen receipt.

    Raises ReceiptError (or ManifestError) on any drift. Returns the
    receipt on success. Performs no baseline execution, no test runs,
    and no mutation: it re-probes the live environment and compares.
    Every path is explicit so tests can inject fixtures; production
    callers should use :func:`verify_production_receipt`.

    ``qualifier_root`` is the directory the receipt's qualifier
    ``code_hashes`` are resolved against; it defaults to this module's
    experiment directory (the production layout).
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
        manifest_required = REQUIRED_MANIFEST_FILES

    # The probing interpreter must itself live beneath the durable root.
    if not interpreter_path_under_root(str(python), durable_root):
        raise ReceiptError(
            f"selected interpreter {python} is not beneath the durable "
            f"root {durable_root}")

    receipt = load_receipt(receipt_path)

    # 1. Execution manifest bytes and every governed file.
    binding = validate_manifest(manifest_path, repo_root,
                                required=manifest_required)
    if binding["manifest_sha256"] != receipt["execution_manifest_sha256"]:
        raise ReceiptError("execution manifest bytes drifted since freeze")
    live_files = binding["files"]
    frozen_files = receipt["execution_manifest_files"]
    if set(live_files) != set(frozen_files):
        raise ReceiptError(
            "execution manifest file set changed since freeze: "
            f"live={sorted(live_files)} frozen={sorted(frozen_files)}")
    drifted = [f for f in live_files if live_files[f] != frozen_files[f]]
    if drifted:
        raise ReceiptError(
            f"manifest-governed execution files drifted: {drifted}")

    # 2. Qualifier implementation bytes: the exact code that decided
    #    admissibility must still match what the receipt bound. A
    #    tampered qualifier must not verify its own receipt.
    if qualifier_root is None:
        qualifier_root = EXP_DIR
    live_qualifier = qualifier_code_hashes(Path(qualifier_root))
    frozen_qualifier = receipt["qualifier"]["code_hashes"]
    if live_qualifier != frozen_qualifier:
        bad = [r for r in live_qualifier
               if live_qualifier[r] != frozen_qualifier.get(r)]
        raise ReceiptError(
            f"qualifier implementation drifted since freeze: {bad}")

    # 3. OpenLine/Airlock source commit.
    if git_head(repo_root) != receipt["airlock_commit"]:
        raise ReceiptError(
            f"airlock source commit drift: receipt={receipt['airlock_commit']} "
            f"live={git_head(repo_root)}")

    # 4. Frozen Q3 receipt and its complete code-hash map.
    q3 = receipt["q3"]
    if sha256_file(q3_receipt_path) != q3["receipt_sha256"]:
        raise ReceiptError("frozen Q3 environment receipt file drifted")
    q3_live = json.loads(q3_receipt_path.read_bytes())
    if q3_live.get("schema") != "airlock.rsi-006-q3.env-receipt.v1":
        raise ReceiptError("frozen Q3 receipt schema unexpected")
    for name, frozen_hash in q3["code_hashes"].items():
        live = sha256_file(q3_code_dir / name)
        if live != frozen_hash:
            raise ReceiptError(f"Q3 code file drifted: {name}")

    # 5. Q4 transaction code.
    if sha256_file(q4_path) != receipt["q4"]["stransaction_sha256"]:
        raise ReceiptError("Q4 stransaction.py drifted since freeze")

    # 6. Q5 receipt/verifier code (this module).
    if sha256_file(Path(__file__)) != receipt["q5"]["receipt_module_sha256"]:
        raise ReceiptError("Q5 environment_receipt.py drifted since freeze")

    # 7. Selected interpreter and dependency lock (probed, never trusted
    #    from the running process).
    try:
        live_interp = interpreter_identity(python)
    except OSError as oe:
        raise ReceiptError(
            f"cannot probe selected interpreter {python}: {oe}") from None
    if live_interp != receipt["interpreter"]:
        raise ReceiptError(
            f"selected interpreter drift: receipt={receipt['interpreter']} "
            f"live={live_interp}")
    try:
        live_lock = dependency_lock(
            python, tuple(sorted(receipt["dependency_lock"])))
    except OSError as oe:
        raise ReceiptError(
            f"cannot probe dependency lock in {python}: {oe}") from None
    if live_lock != receipt["dependency_lock"]:
        raise ReceiptError(
            f"dependency lock drift: receipt={receipt['dependency_lock']} "
            f"live={live_lock}")

    # 8. Repository pins, checkout SHAs, and tree hashes.
    for name, frozen in receipt["repos"].items():
        root = pool_dir / name
        if not root.is_dir():
            raise ReceiptError(f"repo missing from pool: {name}")
        live_sha = repo_checkout_sha(root)
        if live_sha != frozen["checkout_sha"]:
            raise ReceiptError(
                f"repo {name} checkout drift: "
                f"receipt={frozen['checkout_sha']} live={live_sha}")
        live_tree = tree_hash(root)
        if live_tree != frozen["tree_hash"]:
            raise ReceiptError(f"repo {name} tree drift since freeze")

    # 9. Baseline-vector self-consistency: frozen vectors must hash to
    #    their frozen vector hashes (Stage 2 never reruns baselines).
    for name, vec in receipt["baseline_vectors"].items():
        expect = receipt["baseline_vector_hashes"][name]
        if sha256_bytes(canonical_bytes(vec)) != expect:
            raise ReceiptError(
                f"baseline vector hash mismatch for {name}: receipt tampered")
        ev = receipt["baseline_evidence"][name]
        if ev["vector_sha256"] != expect:
            raise ReceiptError(
                f"baseline evidence vector hash mismatch for {name}")

    # 10. Attempt evidence binding: every evidence file from the
    #     successful attempt must still exist with its frozen hash.
    for rel, frozen_hash in receipt["attempt"]["evidence_files"].items():
        p = durable_root / rel
        if not p.is_file():
            raise ReceiptError(f"attempt evidence file missing: {rel}")
        if sha256_file(p) != frozen_hash:
            raise ReceiptError(f"attempt evidence file drifted: {rel}")

    # 11. Durable-storage witness bytes and root binding.
    wit = receipt["storage_witness"]
    if durable_root != Path(wit["durable_root"]):
        raise ReceiptError(
            f"durable root binding drift: receipt={wit['durable_root']} "
            f"live={durable_root}")
    witness_path = durable_root / wit["witness_path"]
    if not witness_path.is_file():
        raise ReceiptError("storage witness missing from durable root")
    if sha256_file(witness_path) != wit["witness_digest"]:
        raise ReceiptError("storage witness bytes drifted since freeze")

    # 12. The Stage 2 work directory must resolve beneath the
    #     receipt-bound durable root.
    if not (stage2_work_dir == durable_root
            or durable_root in stage2_work_dir.parents):
        raise ReceiptError(
            f"Stage 2 work dir {stage2_work_dir} is not beneath the "
            f"qualified durable root {durable_root}")

    return receipt


def verify_production_receipt(
    receipt_path: Path,
    *,
    pool_dir: Path,
    python: str,
    stage2_work_dir: Path,
) -> dict:
    """Verify a production receipt with repo-relative paths derived.

    All manifest/Q3/Q4 locations follow the production layout under the
    repository root containing this module.
    """
    repo_root = EXP_DIR.parent.parent
    q5_rel = "experiments/rsi-006-q5-durable-substrate-qualification"
    return verify_receipt(
        receipt_path,
        pool_dir=pool_dir,
        python=python,
        manifest_path=EXP_DIR / "execution_manifest.json",
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
