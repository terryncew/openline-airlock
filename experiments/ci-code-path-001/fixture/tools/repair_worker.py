#!/usr/bin/env python3
"""Deterministic positive-control worker for the CI code-repair integration path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


FORBIDDEN = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "SSH_AUTH_SOCK",
    "AIRLOCK_VERIFICATION_KEY",
    "OPENLINE_RELEASE_KEY",
)


def main() -> int:
    leaked = [name for name in FORBIDDEN if os.environ.get(name)]
    if leaked:
        print("forbidden authority reached fixture worker: " + ",".join(leaked), file=sys.stderr)
        return 4
    if os.environ.get("AIRLOCK_RELEASE_AUTHORITY") != "ABSENT":
        print("release authority boundary was not explicit", file=sys.stderr)
        return 5
    if os.environ.get("AIRLOCK_DOCTOR_MODE") != "1":
        print("worker was not launched through CI Doctor", file=sys.stderr)
        return 6

    source = Path("src/retry_policy.py")
    before = "return failures_seen <= retry_budget + 1"
    after = "return failures_seen <= retry_budget"
    text = source.read_text()
    if text.count(before) != 1:
        print("fixture defect is not present exactly once", file=sys.stderr)
        return 7
    source.write_text(text.replace(before, after))

    report = Path(os.environ["AIRLOCK_AGENT_REPORT"])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "reported_cost_usd": 0,
        "provider": "fixture-worker",
        "model": "deterministic-positive-control",
        "local_checks_passed": False
    }, sort_keys=True) + "\n")
    print("CI_CODE_PATH_001_WORKER_BOUNDARY_CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

