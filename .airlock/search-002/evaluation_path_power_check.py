#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUB = ROOT / "experiments" / "airlock-search-002" / "substrate"
TEST = SUB / "tests" / "test_public_contract.py"

REQUIRED = {
    "maintbox.objectives",
    "maintbox.queue",
    "maintbox.inbox",
    "maintbox.gitview",
    "maintbox.names",
    "maintbox.retry",
    "maintbox.paths",
    "maintbox.chunks",
    "maintbox.capacity",
}

def main() -> int:
    tree = ast.parse(TEST.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    missing = sorted(REQUIRED - imported)
    test_run = subprocess.run(
        ["python", "tests/test_public_contract.py"],
        cwd=SUB,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    passed = not missing and test_run.returncode == 0
    print(json.dumps({
        "schema": "airlock.search002.evaluation-path-power.v1",
        "pass": passed,
        "required_changed_modules": sorted(REQUIRED),
        "missing_test_references": missing,
        "baseline_test_green": test_run.returncode == 0,
    }, sort_keys=True))
    return 0 if passed else 4

if __name__ == "__main__":
    raise SystemExit(main())
