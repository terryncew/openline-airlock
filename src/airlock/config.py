from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema") != "airlock.config.v1":
        raise ValueError("unsupported .airlock/config.json schema")
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
