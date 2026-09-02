from __future__ import annotations
import json
from pathlib import Path

def load_objective(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("objective must be an object")
    return data
