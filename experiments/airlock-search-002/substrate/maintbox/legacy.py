from __future__ import annotations

def normalize_pairs(rows: list[tuple[str, str]]) -> dict[str, str]:
    # Another decoy: verbose but behaviorally correct.
    output = {}
    for key, value in rows:
        output[str(key).strip()] = str(value).strip()
    return output
