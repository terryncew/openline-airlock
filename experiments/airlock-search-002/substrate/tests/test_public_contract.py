#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# When this file is executed directly, Python puts tests/ rather than the
# substrate root on sys.path. Add the parent repo explicitly so the protected
# baseline test can import the public package it is meant to reference.
SUBSTRATE_ROOT = Path(__file__).resolve().parents[1]
if str(SUBSTRATE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSTRATE_ROOT))

from maintbox.chunks import chunks
from maintbox.gitview import git_snapshot
from maintbox.inbox import read_inbox
from maintbox.names import slugify
from maintbox.objectives import load_objective
from maintbox.paths import dedupe_paths
from maintbox.queue import first_ready
from maintbox.retry import retry_delays
from maintbox.capacity import schedule_jobs


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        objective = root / "objective.json"
        objective.write_text(json.dumps({"goal": "ship"}))
        inbox = root / "inbox.jsonl"
        inbox.write_text('{"id":1}\n{"id":2}\n')

        state = {"calls": 0}
        def provider():
            state["calls"] += 1
            return {"branch": "main", "dirty": False}

        requested = []
        checks = {
            "objective_valid": load_objective(objective)["goal"] == "ship",
            "queue_normal": first_ready([{"ready": False}, {"ready": True}]) == {"ready": True},
            "inbox_valid": [row["id"] for row in read_inbox(inbox)] == [1, 2],
            "git_snapshot_value": git_snapshot(provider) == {"branch": "main", "dirty": False},
            "slug_normal": slugify("Hello World") == "hello-world",
            "retry_normal": retry_delays(3) == [0.5, 1.0, 2.0],
            "paths_unique": sorted(dedupe_paths(["a", "b", "a"])) == ["a", "b"],
            "chunks_even": chunks([1, 2, 3, 4], 2) == [[1, 2], [3, 4]],
            "capacity_normal": sum(schedule_jobs(3, 2, requested.append)) == 3,
        }

    print(json.dumps({
        "schema": "airlock.search002.baseline-tests.v1",
        "checks": checks,
        "passed": all(checks.values()),
    }, sort_keys=True))
    return 0 if all(checks.values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
