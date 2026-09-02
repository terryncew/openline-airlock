#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "experiments" / "airlock-search-003" / "run_search_003.py"


def sh(cmd, cwd):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def load_target():
    spec = importlib.util.spec_from_file_location("search003_target_runtime_restore", TARGET)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {TARGET}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def restore_committed_chunk_state(repo: Path) -> None:
    """Discard only non-admitted worker state between sequential chunks.

    SEARCH-003's authoritative state is committed HEAD:
    - all previously admitted improvements are already committed;
    - the current depletion scoreboard is already committed;
    - blocked/rejected worker edits have no standing.

    Airlock can leave a rejected worker edit in the parent working tree. Restore
    tracked files to HEAD, remove untracked runtime residue, then verify clean.
    """
    before = sh(["git", "status", "--porcelain"], repo).stdout.strip()
    if before:
        print("SEARCH-003 R1 discarding non-admitted runtime state:")
        print(before)

    cp = sh(["git", "reset", "--hard", "HEAD"], repo)
    if cp.returncode:
        raise RuntimeError(f"SEARCH-003 reset failed:\n{cp.stderr}")

    # Remove Airlock runtime outputs and other untracked residue. Tracked
    # scoreboard/config/checks survive because git clean never removes tracked files.
    cp = sh(["git", "clean", "-fd"], repo)
    if cp.returncode:
        raise RuntimeError(f"SEARCH-003 clean failed:\n{cp.stderr}")

    # Interpreter caches can appear inside ignored directories.
    for path in repo.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    for path in repo.rglob("*.pyc"):
        path.unlink(missing_ok=True)

    dirty = sh(["git", "status", "--porcelain"], repo).stdout.strip()
    if dirty:
        raise RuntimeError(
            "SEARCH-003 R1 failed to restore committed chunk state:\n" + dirty
        )


def main() -> int:
    mod = load_target()

    # Harness-only repair. The frozen experiment logic, score dimensions,
    # retirement rule, prompts, oracle, authority envelope, budgets and verdict
    # thresholds remain in the original script unchanged.
    mod.clear_airlock_runtime_state = restore_committed_chunk_state
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
