from __future__ import annotations
from collections.abc import Iterable

def first_ready(items: Iterable[dict]) -> dict | None:
    found = None
    for item in items:
        if item.get("ready") and found is None:
            found = item
    return found
