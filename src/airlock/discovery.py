from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from .gitops import add_worktree, head, remove_worktree, tracked_files
from .util import compact_result, run, sha256_bytes, worktree_env

PROTECTED_CONFIG_NAMES = {
    "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "mypy.ini", "ruff.toml",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "tsconfig.json",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "Makefile", "uv.lock", "poetry.lock",
}

TEST_PATTERNS = ["tests/**", "test/**", "spec/**", "__tests__/**"]
ALWAYS_PROTECTED = [".github/**", ".airlock/**"]


def _package_scripts(repo: Path) -> dict:
    path = repo / "package.json"
    if not path.exists():
        return {}
    try:
        scripts = json.loads(path.read_text()).get("scripts", {})
        return scripts if isinstance(scripts, dict) else {}
    except Exception:
        return {}


def _looks_like_pytest_repo(repo: Path) -> bool:
    if (repo / "pytest.ini").exists():
        return True
    pyproject = repo / "pyproject.toml"
    if pyproject.exists() and "pytest" in pyproject.read_text(errors="ignore"):
        return True
    for root_name in ("tests", "test"):
        root = repo / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                return True
    return False


def _looks_like_python_repo(repo: Path) -> bool:
    if any((repo / name).exists() for name in ("pyproject.toml", "pytest.ini", "setup.py", "setup.cfg")):
        return True
    if any(repo.glob("*.py")):
        return True
    for root_name in ("src", "tests", "test"):
        root = repo / root_name
        if root.exists() and next(root.rglob("*.py"), None) is not None:
            return True
    return False


def discover_commands(repo: Path) -> dict[str, list[list[str]]]:
    static: list[list[str]] = []
    tests: list[list[str]] = []

    has_python = _looks_like_python_repo(repo)
    if has_python and (shutil.which("pytest") or _looks_like_pytest_repo(repo)):
        tests.append(["pytest", "-q"])
    if shutil.which("ruff") and ((repo / "ruff.toml").exists() or (repo / "pyproject.toml").exists()):
        static.append(["ruff", "check", "."])
    if shutil.which("mypy") and ((repo / "mypy.ini").exists() or (repo / "pyproject.toml").exists()):
        static.append(["mypy", "."])

    scripts = _package_scripts(repo)
    if (repo / "package.json").exists() and shutil.which("npm"):
        if "lint" in scripts:
            static.append(["npm", "run", "lint", "--if-present"])
        if "typecheck" in scripts:
            static.append(["npm", "run", "typecheck", "--if-present"])
        if "test" in scripts:
            tests.append(["npm", "test"])

    if (repo / "Cargo.toml").exists() and shutil.which("cargo"):
        tests.append(["cargo", "test", "--all-targets"])
    if (repo / "go.mod").exists() and shutil.which("go"):
        tests.append(["go", "test", "./..."])

    # Stable dedupe while preserving order.
    def dedupe(rows: list[list[str]]) -> list[list[str]]:
        seen = set(); out = []
        for row in rows:
            key = tuple(row)
            if key not in seen:
                seen.add(key); out.append(row)
        return out

    return {"static": dedupe(static), "tests": dedupe(tests)}


def _is_command(argv: list[str], *prefix: str) -> bool:
    return len(argv) >= len(prefix) and tuple(argv[:len(prefix)]) == prefix


def _is_pytest(argv: list[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name
    return executable in {"pytest", "py.test"} or (
        len(argv) >= 3 and argv[1:3] == ["-m", "pytest"]
    )


def _pytest_count(baseline: dict | None) -> int | None:
    """Return an exact count only when one successful pytest run reports it."""
    if not baseline:
        return None
    rows = [
        row for row in baseline.get("commands", [])
        if row.get("kind") == "tests"
        and _is_pytest(row.get("argv", []))
        and row.get("exit_code") == 0
        and not row.get("timed_out")
        and not row.get("side_effect")
    ]
    if len(rows) != 1:
        return None
    output = "\n".join((rows[0].get("stdout_tail", ""), rows[0].get("stderr_tail", "")))
    for line in reversed(output.splitlines()):
        counts = re.findall(r"\b(\d+)\s+(passed|skipped|xfailed|xpassed)\b", line)
        if counts and re.search(r"\bin\s+\d", line):
            return sum(int(count) for count, _ in counts)
    return None


def discovery_metadata(
    repo: Path,
    commands: dict[str, list[list[str]]],
    baseline: dict | None = None,
) -> dict:
    """Describe reliable, human-readable facts behind discovered Starter Rules."""
    static = commands.get("static", [])
    tests = commands.get("tests", [])

    project_types: list[str] = []
    if _looks_like_python_repo(repo):
        project_types.append("Python")
    if (repo / "package.json").exists():
        project_types.append("Node")
    if (repo / "Cargo.toml").exists():
        project_types.append("Rust")
    if (repo / "go.mod").exists():
        project_types.append("Go")

    test_runners: list[str] = []
    if any(_is_pytest(argv) for argv in tests):
        test_runners.append("pytest")
    if any(_is_command(argv, "npm", "test") for argv in tests):
        test_runners.append("npm test")
    if any(_is_command(argv, "cargo", "test") for argv in tests):
        test_runners.append("cargo test")
    if any(_is_command(argv, "go", "test") for argv in tests):
        test_runners.append("go test")

    quality_tools: list[str] = []
    if any(_is_command(argv, "ruff", "check") for argv in static):
        quality_tools.append("Ruff")
    if any(argv and Path(argv[0]).name == "mypy" for argv in static):
        quality_tools.append("mypy")
    if any(_is_command(argv, "npm", "run", "lint") for argv in static):
        quality_tools.append("npm lint")
    if any(_is_command(argv, "npm", "run", "typecheck") for argv in static):
        quality_tools.append("npm typecheck")

    return {
        "project_types": project_types,
        "test_runners": test_runners,
        "quality_tools": quality_tools,
        "test_count": _pytest_count(baseline),
    }


def protected_patterns(repo: Path) -> list[str]:
    patterns: list[str] = []
    tracked = set(tracked_files(repo))
    for pattern in TEST_PATTERNS:
        root_name = pattern.split("/")[0]
        if any(path == root_name or path.startswith(root_name + "/") for path in tracked):
            patterns.append(pattern)
    patterns.extend(ALWAYS_PROTECTED)
    for name in sorted(PROTECTED_CONFIG_NAMES):
        if name in tracked:
            patterns.append(name)
    return patterns


def run_baseline(repo: Path, commands: dict[str, list[list[str]]], timeout: int = 1200) -> dict:
    commit = head(repo)
    records = []
    temp = Path(tempfile.mkdtemp(prefix="airlock-baseline-"))
    temp.rmdir()
    add_worktree(repo, temp, commit=commit)
    try:
        for kind in ("static", "tests"):
            for argv in commands[kind]:
                before = run(["git", "status", "--porcelain", "--untracked-files=no"], temp)
                result = run(argv, temp, env=worktree_env(temp), timeout=timeout)
                after = run(["git", "status", "--porcelain", "--untracked-files=no"], temp)
                compact = compact_result(result)
                compact["kind"] = kind
                compact["side_effect"] = bool(before["stdout"].strip() or after["stdout"].strip())
                records.append(compact)
    finally:
        remove_worktree(repo, temp)
    return {
        "commit": commit,
        "commands": records,
        "green": bool(records) and all(
            row["exit_code"] == 0 and not row["timed_out"] and not row["side_effect"] for row in records
        ),
    }


def protected_fingerprint(repo: Path, commit: str, patterns: list[str]) -> dict:
    import fnmatch
    files = []
    aggregate = []
    for path in tracked_files(repo, commit):
        if any(fnmatch.fnmatch(path, pattern) or path == pattern.rstrip("/") for pattern in patterns):
            result = run(["git", "show", f"{commit}:{path}"], repo)
            if result["exit_code"] != 0:
                continue
            digest = sha256_bytes(result["stdout"].encode())
            files.append({"path": path, "sha256": digest})
            aggregate.append(path + ":" + digest)
    return {
        "files": files,
        "root_sha256": sha256_bytes("\n".join(aggregate).encode()),
    }
