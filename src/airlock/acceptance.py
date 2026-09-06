from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from .gitops import tracked_files
from .util import compact_result, run, worktree_env


ACCEPTANCE_NAMES = {
    "check",
    "checks",
    "verify",
    "verifytypes",
    "validate",
    "validation",
    "quality",
    "ci",
    "lint",
    "typecheck",
    "type-check",
    "test",
    "tests",
}

QUALITY_EXECUTABLES = {
    "pytest",
    "py.test",
    "ruff",
    "mypy",
    "pyright",
    "flake8",
    "black",
    "isort",
    "tox",
    "nox",
    "pre-commit",
    "make",
    "npm",
    "pnpm",
    "yarn",
    "cargo",
    "go",
    "hatch",
    "poe",
    "pdm",
    "uv",
    "poetry",
}

PYTHON_QUALITY_MODULES = {
    "pytest",
    "unittest",
    "ruff",
    "mypy",
    "pyright",
    "flake8",
    "black",
    "isort",
    "coverage",
}

PROJECT_CONTROL_NAMES = {
    "pyproject.toml",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "mypy.ini",
    "ruff.toml",
    ".ruff.toml",
    "package.json",
    "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "makefile",
    "GNUmakefile",
    ".pre-commit-config.yaml",
    ".pre-commit-config.yml",
    "noxfile.py",
    "Taskfile.yml",
    "Taskfile.yaml",
    "justfile",
}

CONTRIBUTOR_DOC_NAMES = {
    "CONTRIBUTING.md",
    "CONTRIBUTING.rst",
    "DEVELOPMENT.md",
    "HACKING.md",
}

_SHELL_COMPLEX = re.compile(r"(?:&&|\|\||[|<>`]|\$\(|\$\{\{|\$[A-Za-z_])")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _read_at(repo: Path, commit: str, path: str) -> str | None:
    result = run(["git", "show", f"{commit}:{path}"], repo)
    if result["exit_code"] != 0:
        return None
    return result["stdout"]


def _exists_at(repo: Path, commit: str, path: str) -> bool:
    result = run(["git", "cat-file", "-e", f"{commit}:{path}"], repo)
    return result["exit_code"] == 0


def _quality_name(value: str) -> bool:
    value = value.casefold().replace("_", "-")
    return value in ACCEPTANCE_NAMES or any(
        token in value for token in ("verify", "check", "lint", "typecheck", "validate", "quality")
    )


def _looks_quality_like_text(text: str) -> bool:
    lower = text.casefold()
    return any(
        token in lower
        for token in (
            "pytest",
            "unittest",
            "ruff",
            "mypy",
            "pyright",
            "flake8",
            "black",
            "isort",
            "tox",
            "nox",
            "pre-commit",
            "verify",
            "typecheck",
            "lint",
            "validate",
            "make check",
            "make verify",
            "npm test",
            "npm run check",
            "npm run verify",
            "pnpm ",
            "yarn ",
            "cargo test",
            "go test",
        )
    )


def _safe_argv(text: str) -> tuple[list[str] | None, str | None]:
    text = text.strip()
    if text.startswith("$ "):
        text = text[2:].strip()
    if not text:
        return None, "empty"
    if "\n" in text or _SHELL_COMPLEX.search(text):
        return None, "shell_composition"
    try:
        argv = shlex.split(text)
    except ValueError:
        return None, "shell_parse"
    if not argv:
        return None, "empty"
    if argv[0] == "env":
        return None, "inline_environment"
    if _ENV_ASSIGNMENT.match(argv[0]):
        return None, "inline_environment"
    return argv, None


def _command_family(argv: list[str]) -> bool:
    if not argv:
        return False
    exe = Path(argv[0]).name.casefold()

    if exe in {"python", "python3", Path(sys.executable).name.casefold()}:
        index = 1
        while index < len(argv) and argv[index].startswith("-") and argv[index] != "-m":
            index += 1
        if index + 1 < len(argv) and argv[index] == "-m":
            return argv[index + 1].casefold() in PYTHON_QUALITY_MODULES
        if index < len(argv):
            return _quality_name(Path(argv[index]).stem)
        return False

    if exe == "make":
        return len(argv) >= 2 and _quality_name(argv[1])

    if exe in {"npm", "pnpm"}:
        if len(argv) >= 2 and argv[1] == "test":
            return True
        return len(argv) >= 3 and argv[1] in {"run", "run-script"} and _quality_name(argv[2])

    if exe == "yarn":
        if len(argv) >= 2 and argv[1] == "test":
            return True
        return len(argv) >= 2 and _quality_name(argv[1])

    if exe == "cargo":
        return len(argv) >= 2 and argv[1] in {"test", "clippy", "fmt"}

    if exe == "go":
        return len(argv) >= 2 and argv[1] in {"test", "vet"}

    if exe in {"hatch", "poe", "pdm", "tox", "nox", "pre-commit", "ruff", "mypy", "pyright", "flake8", "black", "isort"}:
        return True

    if exe == "uvx":
        # ``uvx`` is a runner, not acceptance evidence by itself. It only gains
        # acceptance authority when the command it wraps is already one of the
        # quality families Airlock knows how to recognize. Keep the original
        # argv for execution; this recursive check is classification only.
        return len(argv) >= 2 and _command_family([argv[1], *argv[2:]])

    if exe in {"uv", "poetry"}:
        if len(argv) >= 3 and argv[1] == "run":
            nested = [argv[2], *argv[3:]]
            return _command_family(nested)
        return False

    if argv[0].startswith(("./", "scripts/", "tools/")):
        return _quality_name(Path(argv[0]).stem)

    return exe in QUALITY_EXECUTABLES


def _direct_judge_paths(argv: list[str], tracked: set[str]) -> list[str]:
    paths: list[str] = []
    if not argv:
        return paths

    exe = Path(argv[0]).name.casefold()
    candidates: list[str] = []
    if exe in {"python", "python3", Path(sys.executable).name.casefold()}:
        index = 1
        while index < len(argv) and argv[index].startswith("-") and argv[index] != "-m":
            index += 1
        if index < len(argv) and argv[index] != "-m":
            candidates.append(argv[index])
    elif argv[0].startswith(("./", "scripts/", "tools/")):
        candidates.append(argv[0])

    for value in candidates:
        normalized = value[2:] if value.startswith("./") else value
        if normalized in tracked:
            paths.append(normalized)
    return paths


def _executable_available(argv: list[str], repo: Path, tracked: set[str]) -> bool:
    if not argv:
        return False
    executable = argv[0]
    if executable.startswith("./"):
        normalized = executable[2:]
        return normalized in tracked and (repo / normalized).exists()
    if "/" in executable and executable in tracked:
        return (repo / executable).exists()
    return shutil.which(executable) is not None


def _workflow_is_acceptance_surface(path: str, text: str) -> bool:
    """Recognize repository-owned PR acceptance evidence wherever the workflow puts it.

    Filename and top-level workflow names are useful hints, but they are not the
    acceptance contract. Repositories commonly put quality gates inside generic
    workflows such as ``python-app.yml`` under jobs or steps named "quality",
    "lint", "type check", and similar. A PR workflow therefore qualifies when
    either its outer metadata or its nested job/step/command content carries a
    quality signal.

    Non-PR workflows remain out of scope. Command replay still goes through the
    existing safe-argv and quality-command filters, so discovering a generic PR
    workflow does not authorize arbitrary shell execution.
    """
    if "pull_request" not in text:
        return False

    quality_tokens = {
        "ci",
        "test",
        "tests",
        "quality",
        "lint",
        "check",
        "checks",
        "verify",
        "validation",
        "typecheck",
        "typing",
        "mypy",
        "pyright",
        "ruff",
    }

    def label_is_quality(value: str) -> bool:
        normalized = value.strip().strip("'\"").casefold()
        words = set(re.findall(r"[a-z0-9]+", normalized))
        return bool(words & quality_tokens) or _quality_name(normalized)

    stem = Path(path).stem.casefold().replace("_", "-")
    if label_is_quality(stem):
        return True

    rows = text.splitlines()

    # The top-level workflow name is only one signal. A generic name such as
    # "Python application" must not stop discovery of a nested "Quality gates"
    # job later in the same PR workflow.
    for raw in rows:
        if raw.startswith("name:"):
            if label_is_quality(raw.split(":", 1)[1]):
                return True
            break

    # Job ids, job names, and step names are repository-owned evidence about
    # what the PR workflow is trying to establish.
    for raw in rows:
        if not raw.startswith((" ", "\t")):
            continue
        stripped = raw.strip()
        mapping = re.match(r"^([A-Za-z0-9_.-]+):\s*(?:#.*)?$", stripped)
        if mapping and label_is_quality(mapping.group(1)):
            return True
        if stripped.startswith("name:") and label_is_quality(stripped.split(":", 1)[1]):
            return True

    # Finally inspect the actual run steps. This catches quality gates nested
    # under generic job names without broadening execution: only commands
    # already recognized by the existing quality filters are replayed later.
    return any(
        _looks_quality_like_text(command_text)
        for command_text in _workflow_commands(text)
    )


def _workflow_commands(text: str) -> list[str]:
    rows = text.splitlines()
    found: list[str] = []
    i = 0
    while i < len(rows):
        raw = rows[i]
        match = re.match(r"^(\s*)(?:-\s*)?run:\s*(.*)$", raw)
        if not match:
            i += 1
            continue
        indent = len(match.group(1))
        value = match.group(2).strip()
        if value and value not in {"|", ">", "|-", ">-"}:
            found.append(value)
            i += 1
            continue
        i += 1
        while i < len(rows):
            child = rows[i]
            if child.strip() and len(child) - len(child.lstrip()) <= indent:
                break
            stripped = child.strip()
            if stripped and not stripped.startswith("#"):
                found.append(stripped)
            i += 1
    return found


def _workflow_job_commands(text: str) -> list[list[str]]:
    """Group GitHub Actions run commands by job while preserving order."""
    rows = text.splitlines()
    jobs_index = next((i for i, raw in enumerate(rows) if raw.strip() == "jobs:"), None)
    if jobs_index is None:
        commands = _workflow_commands(text)
        return [commands] if commands else []

    jobs_indent = len(rows[jobs_index]) - len(rows[jobs_index].lstrip())
    job_indent: int | None = None
    blocks: list[list[str]] = []
    current: list[str] | None = None
    mapping = re.compile(r"^[A-Za-z0-9_.-]+:\s*(?:#.*)?$")

    for raw in rows[jobs_index + 1 :]:
        if not raw.strip():
            if current is not None:
                current.append(raw)
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent <= jobs_indent:
            break
        if job_indent is None and mapping.match(raw.strip()):
            job_indent = indent
        if job_indent is not None and indent == job_indent and mapping.match(raw.strip()):
            if current is not None:
                blocks.append(current)
            current = [raw]
        elif current is not None:
            current.append(raw)

    if current is not None:
        blocks.append(current)
    return [commands for block in blocks if (commands := _workflow_commands("\n".join(block)))]


def _workflow_setup_family(argv: list[str]) -> bool:
    """Recognize the narrow setup class justified by REPO-EVIDENCE-004."""
    return bool(
        argv
        and Path(argv[0]).name.casefold() == "uv"
        and len(argv) >= 2
        and argv[1] == "sync"
    )


def _documented_commands(text: str) -> list[str]:
    found: list[str] = []
    in_fence = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        if stripped.startswith("$ "):
            found.append(stripped[2:])
        elif _looks_quality_like_text(stripped):
            found.append(stripped)
    return found


def _make_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw in text.splitlines():
        if not raw or raw.startswith(("\t", " ")):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", raw)
        if match and _quality_name(match.group(1)):
            targets.append(match.group(1))
    return targets


def _pyproject_commands(text: str) -> list[tuple[str, list[str]]]:
    try:
        data = tomllib.loads(text)
    except Exception:
        return []
    tool = data.get("tool") or {}
    found: list[tuple[str, list[str]]] = []

    hatch = ((tool.get("hatch") or {}).get("envs") or {})
    if isinstance(hatch, dict):
        for env_name, env in hatch.items():
            scripts = (env or {}).get("scripts") if isinstance(env, dict) else None
            if not isinstance(scripts, dict):
                continue
            for script_name in scripts:
                if _quality_name(str(script_name)):
                    found.append(
                        (f"hatch:{env_name}:{script_name}", ["hatch", "run", f"{env_name}:{script_name}"])
                    )

    poe = ((tool.get("poe") or {}).get("tasks") or {})
    if isinstance(poe, dict):
        for task_name in poe:
            if _quality_name(str(task_name)):
                found.append((f"poe:{task_name}", ["poe", str(task_name)]))

    pdm = ((tool.get("pdm") or {}).get("scripts") or {})
    if isinstance(pdm, dict):
        for script_name in pdm:
            if _quality_name(str(script_name)):
                found.append((f"pdm:{script_name}", ["pdm", "run", str(script_name)]))

    return found


def discover_acceptance_evidence(repo: Path, base_commit: str) -> dict[str, Any]:
    """Discover repo-owned acceptance evidence without asking a model to invent it."""
    tracked = set(tracked_files(repo, base_commit))
    raw_candidates: list[dict[str, Any]] = []

    def add(
        path: str,
        kind: str,
        command_text: str | None = None,
        argv: list[str] | None = None,
        setup_commands: list[list[str]] | None = None,
    ) -> None:
        raw_candidates.append(
            {
                "path": path,
                "kind": kind,
                "command_text": command_text,
                "argv": argv,
                "setup_commands": [list(row) for row in (setup_commands or [])],
            }
        )

    if "package.json" in tracked:
        text = _read_at(repo, base_commit, "package.json")
        if text:
            try:
                scripts = json.loads(text).get("scripts") or {}
            except Exception:
                scripts = {}
            if isinstance(scripts, dict):
                for name in sorted(scripts):
                    if _quality_name(str(name)):
                        argv = ["npm", "test"] if name == "test" else ["npm", "run", str(name)]
                        add("package.json", "package_script", argv=argv)

    for make_name in ("Makefile", "makefile", "GNUmakefile"):
        if make_name not in tracked:
            continue
        text = _read_at(repo, base_commit, make_name)
        if not text:
            continue
        for target in _make_targets(text):
            add(make_name, "make_target", argv=["make", target])

    if "pyproject.toml" in tracked:
        text = _read_at(repo, base_commit, "pyproject.toml")
        if text:
            for kind, argv in _pyproject_commands(text):
                add("pyproject.toml", kind, argv=argv)

    if ".pre-commit-config.yaml" in tracked or ".pre-commit-config.yml" in tracked:
        path = ".pre-commit-config.yaml" if ".pre-commit-config.yaml" in tracked else ".pre-commit-config.yml"
        add(path, "pre_commit", argv=["pre-commit", "run", "--all-files"])

    for path in sorted(
        p for p in tracked
        if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ):
        text = _read_at(repo, base_commit, path)
        if not text or not _workflow_is_acceptance_surface(path, text):
            continue
        for job_commands in _workflow_job_commands(text):
            setup_commands: list[list[str]] = []
            for command_text in job_commands:
                parsed, _ = _safe_argv(command_text)
                if parsed is not None and _workflow_setup_family(parsed):
                    setup_commands.append(parsed)
                    continue
                if _looks_quality_like_text(command_text):
                    add(
                        path,
                        "github_actions",
                        command_text=command_text,
                        setup_commands=setup_commands,
                    )

    for path in sorted(p for p in tracked if Path(p).name in CONTRIBUTOR_DOC_NAMES):
        text = _read_at(repo, base_commit, path)
        if not text:
            continue
        for command_text in _documented_commands(text):
            if _looks_quality_like_text(command_text):
                add(path, "contributor_docs", command_text=command_text)

    sources: list[dict[str, Any]] = []
    replayable_commands: list[list[str]] = []
    judge_paths: set[str] = set()
    seen_commands: set[tuple[str, ...]] = set()
    seen_sources: set[tuple[str, str, str]] = set()

    for row in raw_candidates:
        path = row["path"]
        judge_paths.add(path)
        argv = row.get("argv")
        parse_reason = None
        if argv is None:
            argv, parse_reason = _safe_argv(str(row.get("command_text") or ""))

        if argv is None:
            key = (path, row["kind"], str(row.get("command_text") or ""))
            if key in seen_sources:
                continue
            seen_sources.add(key)
            sources.append(
                {
                    "path": path,
                    "kind": row["kind"],
                    "status": "unresolved",
                    "reason": parse_reason or "cannot_replay",
                    "command_text": row.get("command_text"),
                }
            )
            continue

        if not _command_family(argv):
            continue

        for direct_path in _direct_judge_paths(argv, tracked):
            judge_paths.add(direct_path)
            root = direct_path.split("/", 1)[0]
            if root in {"scripts", "tools"}:
                judge_paths.update(
                    candidate for candidate in tracked
                    if candidate.startswith(root + "/")
                )

        setup_commands = [list(value) for value in row.get("setup_commands", [])]
        available = _executable_available(argv, repo, tracked)
        unavailable_setup = [
            value for value in setup_commands
            if not _executable_available(value, repo, tracked)
        ]
        replayable = available and not unavailable_setup
        source = {
            "path": path,
            "kind": row["kind"],
            "argv": argv,
            "setup_commands": setup_commands,
            "status": "replayable" if replayable else "unresolved",
        }
        if not available:
            source["reason"] = "command_unavailable"
        elif unavailable_setup:
            source["reason"] = "setup_command_unavailable"
            source["unavailable_setup_commands"] = unavailable_setup

        key = (path, row["kind"], shlex.join(argv))
        if key in seen_sources:
            continue
        seen_sources.add(key)
        sources.append(source)

        command_key = tuple(argv)
        if replayable and command_key not in seen_commands:
            seen_commands.add(command_key)
            replayable_commands.append(argv)

    unresolved = [row for row in sources if row.get("status") == "unresolved"]
    return {
        "schema": "airlock.repository-acceptance.v1",
        "base_commit": base_commit,
        "commands": replayable_commands,
        "sources": sources,
        "judge_paths": sorted(judge_paths),
        "unresolved": unresolved,
    }


def freeze_judge_files(worktree: Path, base_commit: str, evidence: dict[str, Any]) -> list[str]:
    """Restore repo-owned judge definitions from the base before executing them."""
    restored: list[str] = []
    for path in evidence.get("judge_paths", []):
        if not _exists_at(worktree, base_commit, path):
            continue
        result = run(["git", "show", f"{base_commit}:{path}"], worktree)
        if result["exit_code"] != 0:
            continue
        target = worktree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result["stdout"])
        restored.append(path)
    return restored


def project_control_change_check(worktree: Path, base_commit: str) -> dict[str, Any]:
    """Fail closed when a patch changes or introduces a file that can redefine its judge."""
    diff = run(["git", "diff", "--name-only", f"{base_commit}..HEAD"], worktree)
    if diff["exit_code"] != 0:
        return {
            "rule": "repository_acceptance",
            "status": "INSUFFICIENT",
            "basis": "cannot_inspect_project_control_changes",
            "touched": [],
        }

    touched = []
    for path in [line.strip() for line in diff["stdout"].splitlines() if line.strip()]:
        if Path(path).name in PROJECT_CONTROL_NAMES or path in PROJECT_CONTROL_NAMES:
            touched.append(path)

    return {
        "rule": "repository_acceptance",
        "status": "FAIL" if touched else "PASS",
        "basis": "project_control_file_changed" if touched else "project_control_unchanged",
        "touched": touched,
    }


def _setup_for_command(evidence: dict[str, Any], argv: list[str]) -> list[list[str]]:
    """Use the most explicit replayable same-job context for this command."""
    best: list[list[str]] = []
    for source in evidence.get("sources", []):
        if source.get("status") != "replayable" or source.get("argv") != argv:
            continue
        candidate = [list(row) for row in source.get("setup_commands", [])]
        if len(candidate) > len(best):
            best = candidate
    return best


def _run_setup(
    root: Path,
    setup_commands: list[list[str]],
    *,
    timeout: int,
    kind: str,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    records: list[dict[str, Any]] = []
    for argv in setup_commands:
        before = run(["git", "status", "--porcelain", "--untracked-files=no"], root)
        result = run(argv, root, env=worktree_env(root), timeout=timeout)
        after = run(["git", "status", "--porcelain", "--untracked-files=no"], root)
        compact = compact_result(result)
        compact["kind"] = kind
        compact["side_effect"] = before["stdout"] != after["stdout"]
        records.append(compact)
        if compact["side_effect"]:
            return False, records, "acceptance_setup_side_effect"
        if compact["exit_code"] != 0 or compact["timed_out"]:
            return False, records, "acceptance_setup_failed"
    return True, records, None


def _run_base_acceptance(
    worktree: Path,
    base_commit: str,
    commands: list[list[str]],
    evidence: dict[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    """Prove the frozen base already satisfies every replayable acceptance command."""
    if not commands:
        return {"status": "PASS", "commands": []}

    temp = Path(tempfile.mkdtemp(prefix="airlock-acceptance-base-"))
    temp.rmdir()
    add = run(["git", "worktree", "add", "--detach", "-f", str(temp), base_commit], worktree)
    if add["exit_code"] != 0:
        return {
            "status": "INSUFFICIENT",
            "basis": "acceptance_base_worktree_failed",
            "commands": [],
        }

    records = []
    completed_setup: set[tuple[tuple[str, ...], ...]] = set()
    try:
        for argv in commands:
            setup_commands = _setup_for_command(evidence, argv)
            setup_key = tuple(tuple(row) for row in setup_commands)
            if setup_commands and setup_key not in completed_setup:
                ok, setup_records, basis = _run_setup(
                    temp, setup_commands, timeout=timeout, kind="acceptance_baseline_setup"
                )
                records.extend(setup_records)
                if not ok:
                    return {
                        "status": "FAIL",
                        "basis": (
                            "acceptance_baseline_setup_side_effect"
                            if basis == "acceptance_setup_side_effect"
                            else "acceptance_baseline_setup_failed"
                        ),
                        "commands": records,
                    }
                completed_setup.add(setup_key)
            before = run(["git", "status", "--porcelain", "--untracked-files=no"], temp)
            result = run(argv, temp, env=worktree_env(temp), timeout=timeout)
            after = run(["git", "status", "--porcelain", "--untracked-files=no"], temp)
            compact = compact_result(result)
            compact["kind"] = "acceptance_baseline"
            compact["side_effect"] = before["stdout"] != after["stdout"]
            records.append(compact)
            if compact["exit_code"] != 0 or compact["timed_out"] or compact["side_effect"]:
                return {
                    "status": "FAIL",
                    "basis": "acceptance_baseline_not_green",
                    "commands": records,
                }
    finally:
        run(["git", "worktree", "remove", "-f", str(temp)], worktree)

    return {"status": "PASS", "commands": records}


def run_acceptance_commands(
    worktree: Path,
    base_commit: str,
    evidence: dict[str, Any],
    *,
    timeout: int,
    already_ran: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Execute the base repo's additional acceptance commands against the candidate."""
    already = {tuple(row) for row in (already_ran or [])}
    commands = [row for row in evidence.get("commands", []) if tuple(row) not in already]

    baseline = _run_base_acceptance(
        worktree,
        base_commit,
        commands,
        evidence,
        timeout=timeout,
    )
    if baseline["status"] != "PASS":
        return {
            "rule": "repository_acceptance",
            "status": "FAIL",
            "basis": baseline.get("basis", "acceptance_baseline_unresolved"),
            "commands": [],
            "baseline_commands": baseline.get("commands", []),
            "sources": evidence.get("sources", []),
            "restored_judge_paths": [],
        }

    restored = freeze_judge_files(worktree, base_commit, evidence)
    records = []
    completed_setup: set[tuple[tuple[str, ...], ...]] = set()

    for argv in commands:
        setup_commands = _setup_for_command(evidence, argv)
        setup_key = tuple(tuple(row) for row in setup_commands)
        if setup_commands and setup_key not in completed_setup:
            ok, setup_records, basis = _run_setup(
                worktree, setup_commands, timeout=timeout, kind="acceptance_setup"
            )
            records.extend(setup_records)
            if not ok:
                return {
                    "rule": "repository_acceptance",
                    "status": "FAIL",
                    "basis": basis or "acceptance_setup_failed",
                    "commands": records,
                    "sources": evidence.get("sources", []),
                    "restored_judge_paths": restored,
                    "baseline_commands": baseline.get("commands", []),
                }
            completed_setup.add(setup_key)
        before = run(["git", "status", "--porcelain", "--untracked-files=no"], worktree)
        result = run(argv, worktree, env=worktree_env(worktree), timeout=timeout)
        after = run(["git", "status", "--porcelain", "--untracked-files=no"], worktree)
        compact = compact_result(result)
        compact["kind"] = "acceptance"
        compact["side_effect"] = before["stdout"] != after["stdout"]
        records.append(compact)
        if compact["exit_code"] != 0 or compact["timed_out"] or compact["side_effect"]:
            return {
                "rule": "repository_acceptance",
                "status": "FAIL",
                "basis": (
                    "acceptance_command_side_effect"
                    if compact["side_effect"]
                    else "acceptance_command_failed"
                ),
                "commands": records,
                "sources": evidence.get("sources", []),
                "restored_judge_paths": restored,
                "baseline_commands": baseline.get("commands", []),
            }

    return {
        "rule": "repository_acceptance",
        "status": "PASS",
        "basis": (
            "repo_owned_acceptance_commands_passed"
            if commands
            else "no_additional_replayable_acceptance_commands"
        ),
        "commands": records,
        "sources": evidence.get("sources", []),
        "restored_judge_paths": restored,
        "baseline_commands": baseline.get("commands", []),
    }
