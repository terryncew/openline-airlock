from __future__ import annotations

def chunks(values: list[int], size: int) -> list[list[int]]:
    if size <= 0:
        raise ValueError("size must be positive")
    out = []
    for start in range(0, len(values) - size + 1, size):
        out.append(values[start:start + size])
    return out
