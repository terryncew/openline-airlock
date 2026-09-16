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
                        "q6_receipt.py")] +
    [_Q5P + n for n in ("execution_ledger.py", "q5_adapter.py",
                        "run_rsi_006_q5.py", "environment_receipt.py")] +
    ["experiments/rsi-006-q4-durable-transaction/stransaction.py",
     "experiments/rsi-006-q3-substrate-qualification/contact.py"])


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


def build_q6_receipt(*, frozen_at, manifest_binding, qualifier_binding,
                     airlock_commit, fs_witness) -> dict:
    """Assemble the Q6 environment receipt dict (pure; no I/O)."""
    return {
        "schema": RECEIPT_SCHEMA, "stage": STAGE, "frozen_at": frozen_at,
        "airlock_commit": airlock_commit,
        "execution_manifest_sha256": manifest_binding["manifest_sha256"],
        "execution_manifest_files": manifest_binding["files"],
        "qualifier": {
            "source_commit": qualifier_binding["source_commit"],
            "code_hashes": dict(qualifier_binding["code_hashes"]),
        },
        "q3": {
            "receipt_path": manifest_binding["q3_receipt_path"],
            "receipt_sha256": manifest_binding["q3_receipt_sha256"],
        },
        "storage_witness": dict(fs_witness),
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
