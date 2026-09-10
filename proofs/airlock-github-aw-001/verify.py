"""Verify AIRLOCK-GITHUB-AW-001 Airlock-arm evidence.

This verifier does not declare a cross-system winner. The GitHub Agentic
Workflows live arm must complete separately before any category claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

AIRLOCK_BASE = "fb02207f3ac561368beeabf9ff168076bf828824"
TARGET_FULL = "mrphrazer/binary-ninja-headless-mcp"
TARGET_SHA = "49c39c2d4427b586ce1ec3499baa86c38f980ece"


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_command_pass(record: dict[str, Any], label: str) -> None:
    if record.get("timed_out"):
        raise AssertionError(f"{label} timed out")
    if record.get("exit_code") != 0:
        raise AssertionError(f"{label} did not pass")


def source_hashes() -> dict[str, str]:
    paths = [
        ".github/workflows/airlock-github-aw-001.yml",
        "AIRLOCK_GITHUB_AW_001.md",
        "proofs/airlock-github-aw-001/run.py",
        "proofs/airlock-github-aw-001/verify.py",
        "proofs/airlock-github-aw-001/prereg.json",
        "proofs/airlock-github-aw-001/candidate-a.patch",
        "proofs/airlock-github-aw-001/candidate-b.patch",
        "proofs/airlock-github-aw-001/github-aw/airlock-github-aw-001.md",
    ]
    return {path: sha256_path(REPO_ROOT / path) for path in paths}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir")
    args = parser.parse_args(argv)
    root = Path(args.artifact_dir).resolve()

    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    if result.get("schema") != "airlock.github_aw_001.airlock_result.v1":
        raise AssertionError("schema mismatch")
    if result.get("experiment_id") != "AIRLOCK-GITHUB-AW-001":
        raise AssertionError("experiment mismatch")
    if result.get("airlock_base") != AIRLOCK_BASE:
        raise AssertionError("Airlock base mismatch")
    if result.get("target") != {"repository": TARGET_FULL, "commit": TARGET_SHA}:
        raise AssertionError("target pin mismatch")
    if result.get("source_sha256") != source_hashes():
        raise AssertionError("source hashes changed")

    if result.get("airlock_status") == "AIRLOCK_INIT_FAILED":
        print("AIRLOCK-GITHUB-AW-001: INCONCLUSIVE_AIRLOCK_INIT_FAILURE")
        return 0

    for name, record in result["baseline"].items():
        verify_command_pass(record, f"baseline {name}")

    a = result["ground_truth"]["a"]
    b = result["ground_truth"]["b"]
    if a.get("functional_pass") is not True or b.get("functional_pass") is not True:
        raise AssertionError("functional pair premise failed")
    if a.get("acceptance_pass") is not False:
        raise AssertionError("candidate A no longer provides the noncompliant control")
    if b.get("acceptance_pass") is not True:
        raise AssertionError("candidate B no longer provides the compliant control")

    if result.get("airlock_pair_class") not in {
        "AIRLOCK_DISCRIMINATED",
        "AIRLOCK_UNDERCONSTRAINED",
        "AIRLOCK_OVERCONSERVATIVE_OR_INSUFFICIENT",
        "AIRLOCK_INVERTED",
        "AIRLOCK_INCONCLUSIVE",
    }:
        raise AssertionError("unknown Airlock pair class")

    if result.get("github_aw_status") != "PENDING_LIVE_ARM":
        raise AssertionError("live GitHub arm was incorrectly claimed complete")
    if result.get("claim_status") != "NO_CATEGORY_CLAIM_UNTIL_GITHUB_AW_ARM_COMPLETES":
        raise AssertionError("cross-system claim made before live comparator")

    print(
        "AIRLOCK-GITHUB-AW-001 Airlock arm verified: "
        f"{result['airlock_pair_class']}; GitHub AW live arm still pending"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
