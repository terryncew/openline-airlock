#!/usr/bin/env python3
from __future__ import annotations
import json


def linked(row: dict) -> tuple:
    return (
        bool(row.get("public_anchor")),
        bool(row.get("trace_to_lever")),
        bool(row.get("top_level_outcome")),
        bool(row.get("reproducible_probe")),
        int(row.get("files", 99)) <= 2,
        -int(row.get("files", 99)),
    )


def main() -> int:
    outcome_linked = {
        "name": "Public workflow with traced local lever",
        "public_anchor": True,
        "trace_to_lever": True,
        "top_level_outcome": True,
        "reproducible_probe": True,
        "files": 1,
    }
    cosmetic = {
        "name": "Locally measurable cleanup",
        "public_anchor": False,
        "trace_to_lever": False,
        "top_level_outcome": False,
        "reproducible_probe": True,
        "files": 1,
    }
    ordered = sorted([cosmetic, outcome_linked], key=linked, reverse=True)
    passed = ordered[0]["name"] == outcome_linked["name"]
    print(json.dumps({
        "schema": "airlock.search-001c.outcome-link-power.v1",
        "pass": passed,
        "winner": ordered[0]["name"],
        "loser": ordered[1]["name"],
    }))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
