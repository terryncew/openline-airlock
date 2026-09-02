from __future__ import annotations

def dedupe_paths(paths: list[str]) -> list[str]:
    return sorted(set(paths))
