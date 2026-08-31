from __future__ import annotations

import tempfile
from pathlib import Path

from .gitops import add_worktree, remove_worktree


class WorktreeSandbox:
    def __init__(self, repo: Path, commit: str, branch: str | None = None, prefix: str = "airlock-"):
        self.repo = repo
        self.commit = commit
        self.branch = branch
        self.path = Path(tempfile.mkdtemp(prefix=prefix))
        # git worktree expects a non-existent path
        self.path.rmdir()

    def __enter__(self) -> Path:
        add_worktree(self.repo, self.path, branch=self.branch, commit=self.commit)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        remove_worktree(self.repo, self.path)
