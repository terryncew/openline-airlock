#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORECARD = ROOT / ".airlock" / "search-002" / "scorecard.json"
REFERENCE_POWER = ROOT / ".airlock" / "search-002" / "reference_power_check.py"

def public_scoreboard(retired: set[str]) -> dict:
    base = json.loads(SCORECARD.read_text())
    rows = []
    for dim in base["dimensions"]:
        row = dict(dim)
        is_retired = dim["id"] in retired
        row["retired"] = is_retired
        row["marginal_value"] = 0 if is_retired else int(dim.get("weight", 1))
        rows.append(row)
    return {
        "schema": "airlock.search-003.scoreboard.v1",
        "principle": "Earned dimensions remain visible but pay zero marginal value.",
        "dimensions": rows,
    }

def main() -> int:
    base = json.loads(SCORECARD.read_text())
    ids = [d["id"] for d in base["dimensions"]]
    if len(ids) != 9 or len(set(ids)) != 9:
        print(json.dumps({"pass": False, "reason": "EXPECTED_NINE_UNIQUE_DIMENSIONS"}))
        return 2

    retired = {ids[0], ids[-1]}
    board = public_scoreboard(retired)
    rows = {d["id"]: d for d in board["dimensions"]}
    retirement_ok = all(
        (rows[i]["retired"] and rows[i]["marginal_value"] == 0) if i in retired
        else ((not rows[i]["retired"]) and rows[i]["marginal_value"] > 0)
        for i in ids
    )

    ref = subprocess.run(
        ["python", str(REFERENCE_POWER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    reference_ok = ref.returncode == 0

    passed = retirement_ok and reference_ok
    print(json.dumps({
        "schema": "airlock.search-003.depletion-power.v1",
        "pass": passed,
        "retirement_dimension_level": retirement_ok,
        "retired_dimensions": sorted(retired),
        "retired_credit": 0,
        "reference_9_of_9_reachable": reference_ok,
    }, sort_keys=True))
    return 0 if passed else 3

if __name__ == "__main__":
    raise SystemExit(main())
