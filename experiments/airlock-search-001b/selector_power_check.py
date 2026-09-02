#!/usr/bin/env python3
from __future__ import annotations

import json


def rank_key(row: dict) -> tuple:
    """Frozen public opportunity ordering for the synthetic power check.

    This is not the hidden evaluator. It only verifies that the search scaffold
    prefers measured, local opportunities over diffuse aesthetic refactors.
    """
    measurable = bool(row.get("numeric_receipt"))
    reproducible = bool(row.get("reproducible"))
    files = int(row.get("files", 999))
    scope_ok = files <= 2
    return (measurable, reproducible, scope_ok, -files)


def main() -> int:
    measured_local = {
        "name": "Measured local slowdown",
        "numeric_receipt": True,
        "reproducible": True,
        "files": 1,
    }
    diffuse_refactor = {
        "name": "Broad cleanup",
        "numeric_receipt": False,
        "reproducible": False,
        "files": 4,
    }

    ordered = sorted(
        [diffuse_refactor, measured_local],
        key=rank_key,
        reverse=True,
    )
    passed = ordered[0]["name"] == measured_local["name"]
    print(json.dumps({
        "schema": "airlock.search-001b.power-check.v1",
        "pass": passed,
        "winner": ordered[0]["name"],
        "loser": ordered[1]["name"],
    }))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
