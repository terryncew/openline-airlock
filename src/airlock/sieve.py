from __future__ import annotations

import re
from pathlib import Path

from .acceptance import (
    discover_acceptance_evidence,
    project_control_change_check,
    run_acceptance_commands,
)
from .util import compact_result, matches_any, run, worktree_env


def protected_files_check(changed_paths: list[str], protected: list[str]) -> dict:
    touched = [path for path in changed_paths if matches_any(path, protected)]
    return {
        "rule": "protected_files",
        "status": "FAIL" if touched else "PASS",
        "touched": touched,
    }


def _candidate_base(worktree: Path) -> str | None:
    """Recover the frozen candidate base without trusting the candidate's parent.

    Normal Airlock candidates live on an ``airlock/.../candidate-*`` branch.
    The first reflog entry for that branch is the commit Airlock created it
    from, even if the worker made multiple commits afterward.
    """
    head_result = run(["git", "rev-parse", "HEAD"], worktree)
    if head_result["exit_code"] != 0:
        return None
    candidate_head = head_result["stdout"].strip()

    refs = run(
        ["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/airlock/"],
        worktree,
    )
    if refs["exit_code"] == 0:
        for raw in refs["stdout"].splitlines():
            if not raw.strip():
                continue
            try:
                branch, commit = raw.rsplit(" ", 1)
            except ValueError:
                continue
            if commit != candidate_head or "/candidate-" not in branch:
                continue
            reflog = run(
                ["git", "reflog", "show", "--format=%H", branch],
                worktree,
            )
            if reflog["exit_code"] == 0:
                rows = [row.strip() for row in reflog["stdout"].splitlines() if row.strip()]
                if rows:
                    return rows[-1]

    # External evaluator harnesses may use detached one-commit candidates.
    result = run(["git", "rev-parse", "HEAD^"], worktree)
    if result["exit_code"] != 0:
        return None
    value = result["stdout"].strip()
    return value or None


def run_checks(worktree: Path, commands: list[list[str]], *, timeout: int, kind: str) -> dict:
    records = []
    for argv in commands:
        result = run(argv, worktree, env=worktree_env(worktree), timeout=timeout)
        compact = compact_result(result)
        compact["kind"] = kind
        records.append(compact)
        if compact["exit_code"] != 0 or compact["timed_out"]:
            return {"rule": kind, "status": "FAIL", "commands": records}

    if kind != "regression":
        return {"rule": kind, "status": "PASS", "commands": records}

    base_commit = _candidate_base(worktree)
    if not base_commit:
        return {
            "rule": kind,
            "status": "PASS",
            "commands": records,
            "repository_acceptance": {
                "status": "INSUFFICIENT",
                "basis": "candidate_base_unavailable",
            },
        }

    control = project_control_change_check(worktree, base_commit)
    if control["status"] != "PASS":
        return {
            "rule": "repository_acceptance",
            "status": "FAIL",
            "basis": control["basis"],
            "commands": records,
            "project_control": control,
        }

    evidence = discover_acceptance_evidence(worktree, base_commit)
    acceptance = run_acceptance_commands(
        worktree,
        base_commit,
        evidence,
        timeout=timeout,
        already_ran=commands,
    )
    combined = records + acceptance.get("commands", [])
    if acceptance["status"] != "PASS":
        acceptance["commands"] = combined
        return acceptance

    return {
        "rule": kind,
        "status": "PASS",
        "commands": combined,
        "repository_acceptance": {
            "status": "PASS",
            "basis": acceptance["basis"],
            "sources": acceptance.get("sources", []),
            "restored_judge_paths": acceptance.get("restored_judge_paths", []),
        },
    }


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
    acceptance = discover_acceptance_evidence(repo, base_commit)
    if acceptance.get("unresolved"):
        return {
            "rule": "evidence_sufficiency",
            "status": "INSUFFICIENT",
            "basis": "unresolved_repository_acceptance_evidence",
            "matched_tests": [],
            "repository_acceptance": {
                "sources": acceptance.get("sources", []),
                "unresolved": acceptance.get("unresolved", []),
            },
        }

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
