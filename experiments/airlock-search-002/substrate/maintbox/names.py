from __future__ import annotations
import re

def slugify(value: str) -> str:
    parts = re.findall(r"[a-z0-9]+", value.lower())
    return "-".join(parts)
