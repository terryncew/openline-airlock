#!/usr/bin/env python3
"""Verify the Hermes harness-fingerprint extension without rerunning a worker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = "AIRLOCK_HERMES_HARNESS_001_HANDOFF.json"
EXPECTED_CHANGED_FILES = [
    "AIRLOCK_HERMES_HARNESS_001_HANDOFF.json",
    "AIRLOCK_NIGHTSHIFT_001_HANDOFF.json",
    "BUILD_RECEIPT_HERMES_HARNESS_001.json",
    "docs/HARNESS_FINGERPRINT.md",
    "schemas/harness-fingerprint-v1.schema.json",
    "scripts/verify_harness_fingerprint.py",
    "src/airlock/harness.py",
    "src/airlock/nightshift.py",
    "tests/test_harness_fingerprint.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for relative in EXPECTED_CHANGED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing {relative}")

    try:
        prereg = json.loads((root / ".airlock/hermes-live-001.json").read_text())
    except Exception as exc:
        errors.append(f"cannot read frozen HERMES-LIVE-001 preregistration: {exc}")
        prereg = {}
    for relative, expected in prereg.get("frozen_files", {}).items():
        path = root / relative
        if not path.is_file():
            errors.append(f"frozen file missing: {relative}")
        elif sha256(path) != expected:
            errors.append(f"frozen HERMES-LIVE-001 file changed: {relative}")

    try:
        schema = json.loads((root / "schemas/harness-fingerprint-v1.schema.json").read_text())
    except Exception as exc:
        errors.append(f"invalid harness fingerprint schema: {exc}")
        schema = {}
    if schema.get("properties", {}).get("schema", {}).get("const") != "airlock.hermes-harness-fingerprint.v1":
        errors.append("harness fingerprint schema identity changed")

    harness = (root / "src/airlock/harness.py").read_text() if (root / "src/airlock/harness.py").is_file() else ""
    for marker in ("config.yaml", "SOUL.md", "skills", "memories", "tools", "requested_model", "tool_registry", ".env", "auth.json", "state.db"):
        if marker not in harness:
            errors.append(f"harness implementation lost required surface marker: {marker}")

    nightshift = (root / "src/airlock/nightshift.py").read_text() if (root / "src/airlock/nightshift.py").is_file() else ""
    for marker in (
        "starting_harness",
        "harness_lineage",
        "outside an observed Nightshift transition",
        "fingerprint_harness_set",
        "effective_model_observed",
        "controller_model_route",
        "attempts",
    ):
        if marker not in nightshift:
            errors.append(f"Nightshift lost harness-lineage marker: {marker}")

    try:
        handoff = json.loads((root / HANDOFF).read_text())
    except Exception as exc:
        errors.append(f"invalid harness handoff: {exc}")
        handoff = {}
    if handoff.get("base_sha") != "ec90174f65f6120e92b20edc6a68707facef40e4":
        errors.append("handoff is not based on the frozen SEARCH-003 main")
    if handoff.get("changed_files") != EXPECTED_CHANGED_FILES:
        errors.append("handoff changed-file set is not the frozen nine-file overlay")
    if handoff.get("search_004_gate") != "HARNESS_FINGERPRINT_REQUIRED":
        errors.append("SEARCH-004 harness-fingerprint gate is missing")

    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("Airlock Hermes harness fingerprint check: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Airlock Hermes harness fingerprint check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
