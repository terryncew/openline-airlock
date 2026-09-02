#!/usr/bin/env python3
from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import shutil

SUBSTRATE = "91861c77e4b03ace60df147b0accf94f4351de18"

HIDDEN = [
    ".airlock/self-001/evaluator.py",
    ".airlock/self-001/scope_registry.json",
    ".airlock/self-001/preregistration.json",
    ".airlock/self-001/fixtures",
    "experiments/airlock-self-001/README.md",
    "experiments/airlock-self-001/run_self_001.py",
    "experiments/airlock-self-001/fixtures",
]


def main() -> int:
    repo = Path(".").resolve()
    if subprocess.check_output(["git", "rev-parse", SUBSTRATE], cwd=repo, text=True).strip() != SUBSTRATE:
        raise RuntimeError("pinned substrate unavailable")

    tmp = Path(tempfile.mkdtemp(prefix="search001c-density-"))
    try:
        archive = subprocess.check_output(["git", "archive", "--format=tar", SUBSTRATE], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
            tf.extractall(tmp)

        for rel in HIDDEN:
            p = tmp / rel
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()

        doc_files = [
            p for p in tmp.rglob("*.md")
            if ".git" not in p.parts
        ]
        public_checks = [
            p for p in tmp.rglob("*.py")
            if (
                "tests" in p.parts
                or p.name.startswith("test_")
                or p.as_posix().endswith(".airlock/self-001/protected_checks.py")
            )
        ]

        documented_functions = 0
        for p in tmp.rglob("*.py"):
            if any(part in {".git", "__pycache__"} for part in p.parts):
                continue
            try:
                tree = ast.parse(p.read_text())
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node):
                    documented_functions += 1

        cli_surface = int(
            (tmp / "src/airlock/cli.py").is_file()
            or (tmp / "src/airlock/entry.py").is_file()
            or (tmp / "pyproject.toml").is_file()
        )

        try:
            commit_count = int(subprocess.check_output(
                ["git", "rev-list", "--count", SUBSTRATE], cwd=repo, text=True
            ).strip())
        except Exception:
            commit_count = 0

        channels = {
            "documentation": len(doc_files),
            "public_checks": len(public_checks),
            "documented_code_contracts": documented_functions,
            "cli_or_package_surface": cli_surface,
            "git_history_commits": commit_count,
        }
        active_channels = sum(1 for value in channels.values() if value > 0)
        passed = (
            active_channels >= 3
            and channels["public_checks"] > 0
            and channels["documented_code_contracts"] > 0
        )

        print(json.dumps({
            "schema": "airlock.search-001c.evidence-density.v1",
            "pass": passed,
            "active_public_channels": active_channels,
            "counts": channels,
            "note": "Counts only; no target names or hidden evaluator content are emitted.",
        }, sort_keys=True))
        return 0 if passed else 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
