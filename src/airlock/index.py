from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema": "airlock.evidence-index.v1", "by_evidence_hash": {}}
    return json.loads(path.read_text())


def add(path: Path, proof_path: str, evidence_hashes: list[str]) -> None:
    index = load(path)
    bucket = index.setdefault("by_evidence_hash", {})
    for digest in sorted(set(evidence_hashes)):
        rows = bucket.setdefault(digest, [])
        if proof_path not in rows:
            rows.append(proof_path)
            rows.sort()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
