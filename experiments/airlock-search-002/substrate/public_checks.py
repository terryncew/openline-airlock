#!/usr/bin/env python3
from __future__ import annotations
import json, tempfile
from pathlib import Path
from maintbox.chunks import chunks
from maintbox.gitview import git_snapshot
from maintbox.inbox import read_inbox
from maintbox.names import slugify
from maintbox.objectives import load_objective
from maintbox.paths import dedupe_paths
from maintbox.queue import first_ready
from maintbox.retry import retry_delays

def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        obj = root/"o.json"; obj.write_text(json.dumps({"goal":"ship"}))
        ib = root/"i.jsonl"; ib.write_text('{"id":1}\n{"id":2}\n')
        state={"calls":0}
        def provider():
            state["calls"] += 1
            return {"branch":"main","dirty":False}
        checks = {
            "objective_valid": load_objective(obj)["goal"] == "ship",
            "queue_normal": first_ready([{"ready":False},{"ready":True}]) == {"ready":True},
            "inbox_valid": [r["id"] for r in read_inbox(ib)] == [1,2],
            "git_snapshot_value": git_snapshot(provider) == {"branch":"main","dirty":False},
            "slug_normal": slugify("Hello World") == "hello-world",
            "retry_normal": retry_delays(3) == [0.5,1.0,2.0],
            "paths_unique": sorted(dedupe_paths(["a","b","a"])) == ["a","b"],
            "chunks_even": chunks([1,2,3,4],2) == [[1,2],[3,4]],
        }
    print(json.dumps({"schema":"airlock.search002.public-checks.v1","checks":checks,"passed":all(checks.values())}, sort_keys=True))
    return 0 if all(checks.values()) else 3

if __name__ == "__main__":
    raise SystemExit(main())
