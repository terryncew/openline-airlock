from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .gitops import add_worktree, head, remove_worktree, tracked_files
from .util import compact_result, run, sha256_bytes

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
        return json.loads(path.read_text()).get("scripts", {})
    except Exception:
        return {}


def discover_commands(repo: Path) -> dict[str, list[list[str]]]:
    static: list[list[str]] = []
    tests: list[list[str]] = []

    has_python = (repo / "pyproject.toml").exists() or (repo / "pytest.ini").exists() or (repo / "tests").exists()
    pyproject_mentions_pytest = False
    if (repo / "pyproject.toml").exists():
        pyproject_mentions_pytest = "pytest" in (repo / "pyproject.toml").read_text(errors="ignore")
    if has_python and (shutil.which("pytest") or pyproject_mentions_pytest):
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


def protected_patterns(repo: Path) -> list[str]:
    patterns = list(ALWAYS_PROTECTED)
    tracked = set(tracked_files(repo))
    for pattern in TEST_PATTERNS:
        root_name = pattern.split("/")[0]
        if any(path == root_name or path.startswith(root_name + "/") for path in tracked):
            patterns.append(pattern)
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
                result = run(argv, temp, timeout=timeout)
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
