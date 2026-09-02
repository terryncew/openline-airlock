from __future__ import annotations
from collections.abc import Callable

def git_snapshot(provider: Callable[[], dict]) -> dict:
    branch = provider()["branch"]
    dirty = provider()["dirty"]
    return {"branch": branch, "dirty": bool(dirty)}
