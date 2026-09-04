#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True)
    ap.add_argument("--parent-work-id", required=True)
    ap.add_argument("--root-id", required=True)
    ap.add_argument("--evidence-dir", type=Path, required=True)
    args = ap.parse_args()

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    marker = args.evidence_dir / f"{args.role}.json"
    if marker.exists():
        raise RuntimeError(f"duplicate execution marker for {args.role}")
    marker.write_text(
        json.dumps(
            {
                "schema": "airlock.cascade-001b.execution.v1",
                "role": args.role,
                "parent_work_id": args.parent_work_id,
                "root_id": args.root_id,
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "started_at_unix_ns": time.time_ns(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
