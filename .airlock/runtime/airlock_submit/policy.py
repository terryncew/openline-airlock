from __future__ import annotations

import fnmatch
import json
import posixpath
import unicodedata
from pathlib import Path

HARD_PROTECTED = [".github/**", ".airlock/**"]


def load_submit_config(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    if data.get("schema") != "airlock.submit.v1":
        raise ValueError("unsupported submit config schema")
    required = ["repo", "base_branch", "container_image"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise ValueError("missing submit config field(s): " + ", ".join(missing))
    data.setdefault("min_account_age_days", 7)
    data.setdefault("min_public_repos", 0)
    data.setdefault("max_daily_submissions_per_user", 5)
    data.setdefault("max_active_submissions", 10)
    data.setdefault("max_patch_files", 60)
    data.setdefault("max_patch_bytes", 2_000_000)
    data.setdefault("evaluation_timeout_seconds", 1200)
    data.setdefault("memory", "2g")
    data.setdefault("cpus", "2")
    data.setdefault("pids_limit", 512)
    data.setdefault("require_source_owner_matches_submitter", True)
    return data


def canonical_repo_path(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("empty repository path")
    value = unicodedata.normalize("NFC", path)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("control character in repository path")
    if "\\" in value:
        raise ValueError("backslash in repository path")
    if value.startswith("/"):
        raise ValueError("absolute repository path")
    normalized = posixpath.normpath(value)
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("path traversal in repository path")
    return normalized


def _match(path: str, pattern: str) -> bool:
    p = path.casefold()
    pat = pattern.casefold()
    if pat.endswith("/**"):
        root = pat[:-3].rstrip("/")
        if p == root or p.startswith(root + "/"):
            return True
    return fnmatch.fnmatch(p, pat) or p == pat.rstrip("/")


def protected_touches(changed_paths: list[str], protected_patterns: list[str]) -> list[str]:
    patterns = list(dict.fromkeys(HARD_PROTECTED + list(protected_patterns)))
    touched = []
    for raw in changed_paths:
        path = canonical_repo_path(raw)
        if any(_match(path, pat) for pat in patterns):
            touched.append(path)
    return sorted(set(touched))


def enforce_submission_limits(store, config: dict, submitter: str) -> None:
    if store.active_count(config["repo"]) >= int(config["max_active_submissions"]):
        raise RuntimeError("Airlock queue is full for this repository")
    if store.daily_count(submitter) >= int(config["max_daily_submissions_per_user"]):
        raise RuntimeError("daily Airlock submission limit reached")
