from __future__ import annotations
import json
from pathlib import Path

def read_inbox(path: str | Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows
