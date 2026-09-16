"""Q6 receipt and execution manifest: schema, bindings, frozen pins."""

import hashlib
import json

import pytest

import q6_testkit as kit  # noqa: F401


def test_receipt_schema_and_stage():
    import q6_receipt as qr
    assert qr.RECEIPT_SCHEMA == "airlock.rsi-006-q6.env-receipt.v1"
    assert qr.STAGE == "q6-environment-qualification"


def test_manifest_validates_all_pins():
    from pathlib import Path
    q6_dir = Path(kit.Q6_DIR)
    manifest_path = q6_dir / "execution_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["schema"] == "airlock.rsi-006-q6.execution-manifest.v1"
    # All ten governed files present.
    assert len(manifest["code_files"]) == 12
    # The frozen Q3 receipt pin matches.
    assert manifest["q3_receipt"]["sha256"] == \
        "d89327dcceb1536d7f66c5d1257a15f9b0de3b9f4c19ef75549eadaa7515acaa"


def test_manifest_file_hashes_match():
    """Every file listed in the manifest exists (hashes pinned in
    test_01_hashes.py against the frozen dependencies)."""
    from pathlib import Path
    q6_dir = Path(kit.Q6_DIR)
    repo_root = q6_dir.parents[1]  # openline-airlock/
    manifest = json.loads(
        (q6_dir / "execution_manifest.json").read_bytes())
    for rel in manifest["code_files"]:
        p = repo_root / rel
        assert p.exists(), f"missing {rel}"
    # The Q3 receipt exists at its pinned path.
    assert (repo_root / manifest["q3_receipt"]["path"]).exists()
