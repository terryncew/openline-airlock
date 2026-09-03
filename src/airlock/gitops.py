from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .util import run


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = run(["git", *args], repo, env=env)
    if result["exit_code"] != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result['stderr'].strip()}")
    return result["stdout"].strip()


def root(start: Path) -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], start)
    if result["exit_code"] != 0:
        raise RuntimeError("Airlock must run inside a Git repository")
    return Path(result["stdout"].strip()).resolve()


def ensure_clean(repo: Path) -> None:
    # Do not route porcelain output through ``git()``: that helper strips
    # leading whitespace, but the first two columns of porcelain status are
    # semantic. In particular, `` M .airlock/config.json`` would become
    # ``M .airlock/config.json`` and the path parser would lose the leading
    # dot, falsely treating receiver-local metadata as ordinary repo dirt.
    result = run(["git", "status", "--porcelain", "--untracked-files=all"], repo)
    if result["exit_code"] != 0:
        raise RuntimeError(f"git status failed: {result['stderr'].strip()}")
    rows = [line for line in result["stdout"].splitlines() if line.strip()]

    # .airlock/ is receiver-local metadata and is hashed separately into each run.
    dirty = []
    for line in rows:
        path = line[3:].strip() if len(line) >= 4 else line.strip()
        if path.startswith(".airlock/"):
            continue
        dirty.append(line)
    if dirty:
        raise RuntimeError("working tree is dirty; Airlock refuses to freeze a moving base")


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def sanitize_branch(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", value).strip("-/")
    if not cleaned or ".." in cleaned or cleaned.startswith("-"):
        raise ValueError("unsafe branch name")
    return cleaned


def add_worktree(repo: Path, dest: Path, *, branch: str | None = None, commit: str | None = None) -> None:
    if branch and commit:
        git(repo, "worktree", "add", "-f", "-b", branch, str(dest), commit)
    elif commit:
        git(repo, "worktree", "add", "--detach", "-f", str(dest), commit)
    else:
        raise ValueError("commit is required")


def remove_worktree(repo: Path, dest: Path) -> None:
    result = run(["git", "worktree", "remove", "-f", str(dest)], repo)
    if result["exit_code"] != 0:
        shutil.rmtree(dest, ignore_errors=True)
        run(["git", "worktree", "prune"], repo)


def commit_all(worktree: Path, message: str) -> str:
    if git(worktree, "status", "--porcelain"):
        git(worktree, "add", "-A")
        env = os.environ.copy()
        env.setdefault("GIT_AUTHOR_NAME", "Airlock Candidate")
        env.setdefault("GIT_AUTHOR_EMAIL", "candidate@airlock.local")
        env.setdefault("GIT_COMMITTER_NAME", "Airlock Candidate")
        env.setdefault("GIT_COMMITTER_EMAIL", "candidate@airlock.local")
        result = run(["git", "commit", "-m", message], worktree, env=env)
        if result["exit_code"] != 0:
            raise RuntimeError(f"candidate commit failed: {result['stderr'].strip()}")
    return git(worktree, "rev-parse", "HEAD")


def changed_paths(repo: Path, base: str, commit: str) -> list[str]:
    out = git(repo, "diff", "--name-only", f"{base}..{commit}")
    return [line for line in out.splitlines() if line.strip()]


def tracked_files(repo: Path, commit: str = "HEAD") -> list[str]:
    out = git(repo, "ls-tree", "-r", "--name-only", commit)
    return [line for line in out.splitlines() if line.strip()]


def blob_bytes(repo: Path, commit: str, path: str) -> bytes:
    result = run(["git", "show", f"{commit}:{path}"], repo)
    if result["exit_code"] != 0:
        raise RuntimeError(f"cannot read {path} at {commit}")
    return result["stdout"].encode()
