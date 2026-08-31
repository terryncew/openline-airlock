from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

SUBMIT_RE = re.compile(
    r"^\s*/airlock\s+submit\s+(?:https://github\.com/)?(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<sha>[0-9a-fA-F]{40})\s*$"
)


def verify_webhook_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def parse_submit_comment(body: str) -> tuple[str, str] | None:
    match = SUBMIT_RE.match(body or "")
    if not match:
        return None
    return match.group("repo"), match.group("sha").lower()


class GitHubReadClient:
    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com"):
        self.token = token
        self.api_base = api_base.rstrip("/")

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(self.api_base + path)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "openline-airlock-submit/0.1")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub API {exc.code} for {path}") from exc

    def user(self, login: str) -> dict:
        return self._get(f"/users/{login}")

    def repo(self, full_name: str) -> dict:
        return self._get(f"/repos/{full_name}")

    def branch_head(self, full_name: str, branch: str) -> str:
        obj = self._get(f"/repos/{full_name}/commits/{branch}")
        sha = str(obj.get("sha", ""))
        if len(sha) != 40:
            raise RuntimeError("GitHub did not return a full base commit SHA")
        return sha.lower()


def account_age_days(created_at: str, *, now: datetime | None = None) -> int:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    return max(0, (now - created).days)


def validate_submitter_and_fork(client: GitHubReadClient, config: dict, submitter: str, source_repo: str) -> dict:
    user = client.user(submitter)
    age = account_age_days(user["created_at"])
    if age < int(config["min_account_age_days"]):
        raise RuntimeError(f"GitHub account is too new for this Airlock ({age}d)")
    if int(user.get("public_repos") or 0) < int(config.get("min_public_repos", 0)):
        raise RuntimeError("GitHub account does not meet this repository's public-history floor")

    repo = client.repo(source_repo)
    if repo.get("private"):
        raise RuntimeError("submission source must be a public fork")
    if not repo.get("fork"):
        raise RuntimeError("submission source must be a public fork")
    parent = (repo.get("parent") or {}).get("full_name")
    if str(parent).casefold() != str(config["repo"]).casefold():
        raise RuntimeError("submission source is not a fork of this repository")
    if config.get("require_source_owner_matches_submitter", True):
        owner = ((repo.get("owner") or {}).get("login") or "")
        if owner.casefold() != submitter.casefold():
            raise RuntimeError("submission fork must be owned by the GitHub account that submitted it")
    return {"account_age_days": age, "public_repos": int(user.get("public_repos") or 0)}
