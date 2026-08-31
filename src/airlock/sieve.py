from __future__ import annotations

import re
from pathlib import Path

from .util import compact_result, matches_any, run, worktree_env


def protected_files_check(changed_paths: list[str], protected: list[str]) -> dict:
    touched = [path for path in changed_paths if matches_any(path, protected)]
    return {
        "rule": "protected_files",
        "status": "FAIL" if touched else "PASS",
        "touched": touched,
    }


def run_checks(worktree: Path, commands: list[list[str]], *, timeout: int, kind: str) -> dict:
    records = []
    for argv in commands:
        result = run(argv, worktree, env=worktree_env(worktree), timeout=timeout)
        compact = compact_result(result)
        compact["kind"] = kind
        records.append(compact)
        if compact["exit_code"] != 0 or compact["timed_out"]:
            return {"rule": kind, "status": "FAIL", "commands": records}
    return {"rule": kind, "status": "PASS", "commands": records}


def infer_changed_modules(changed_paths: list[str]) -> set[str]:
    names = set()
    for path in changed_paths:
        p = Path(path)
        if p.suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go"}:
            stem = p.stem
            if stem not in {"__init__", "index", "mod"}:
                names.add(stem.lower())
            for part in p.parts[:-1]:
                if part not in {"src", "lib", "app", "pkg"}:
                    names.add(part.lower())
    return names


def sufficiency_check(repo: Path, base_commit: str, changed_paths: list[str], test_files: list[str], target_commands: list[list[str]]) -> dict:
    if target_commands:
        return {
            "rule": "evidence_sufficiency",
            "status": "PASS",
            "basis": "explicit_target_command",
            "matched_tests": [],
        }

    modules = infer_changed_modules(changed_paths)
    if not modules:
        return {
            "rule": "evidence_sufficiency",
            "status": "INSUFFICIENT",
            "basis": "no_changed_source_module_detected",
            "matched_tests": [],
        }

    matched = []
    for path in test_files:
        result = run(["git", "show", f"{base_commit}:{path}"], repo)
        if result["exit_code"] != 0:
            continue
        text = result["stdout"].lower()
        if any(re.search(rf"\b{re.escape(name)}\b", text) for name in modules):
            matched.append(path)

    if not matched:
        return {
            "rule": "evidence_sufficiency",
            "status": "INSUFFICIENT",
            "basis": "no_baseline_test_references_changed_module",
            "changed_modules": sorted(modules),
            "matched_tests": [],
        }

    return {
        "rule": "evidence_sufficiency",
        "status": "PASS",
        "basis": "baseline_test_reference_heuristic",
        "changed_modules": sorted(modules),
        "matched_tests": matched,
        "warning": "Reference coverage is a conservative v0.1 heuristic and does not establish complete coverage.",
    }
