from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .github_api import (
    GitHubReadClient,
    parse_submit_comment,
    validate_submitter_and_fork,
    verify_webhook_signature,
)
from .policy import enforce_submission_limits, load_submit_config
from .store import Store


def handle_webhook(*, body: bytes, headers: dict[str, str], config: dict, store: Store,
                   webhook_secret: str, github_client: GitHubReadClient) -> tuple[int, dict]:
    if not verify_webhook_signature(webhook_secret, body, headers.get("x-hub-signature-256")):
        return 401, {"ok": False, "error": "invalid_webhook_signature"}
    if headers.get("x-github-event") != "issue_comment":
        return 202, {"ok": True, "ignored": "event_type"}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return 400, {"ok": False, "error": "invalid_json"}
    if payload.get("action") != "created":
        return 202, {"ok": True, "ignored": "action"}
    repo = ((payload.get("repository") or {}).get("full_name") or "")
    if repo.casefold() != str(config["repo"]).casefold():
        return 403, {"ok": False, "error": "repository_not_allowed"}
    issue = payload.get("issue") or {}
    if issue.get("pull_request"):
        return 202, {"ok": True, "ignored": "pr_comment"}
    parsed = parse_submit_comment(((payload.get("comment") or {}).get("body") or ""))
    if not parsed:
        return 202, {"ok": True, "ignored": "not_airlock_submit"}

    source_repo, source_sha = parsed
    submitter = ((payload.get("sender") or {}).get("login") or "").strip()
    if not submitter:
        return 400, {"ok": False, "error": "missing_submitter"}
    try:
        enforce_submission_limits(store, config, submitter)
        identity = validate_submitter_and_fork(github_client, config, submitter, source_repo)
        base_sha = github_client.branch_head(config["repo"], config["base_branch"])
        row = store.create(
            repo=config["repo"],
            issue_number=int(issue["number"]),
            issue_title=str(issue.get("title") or f"Issue #{issue['number']}"),
            submitter=submitter,
            source_repo=source_repo,
            source_sha=source_sha,
            base_sha=base_sha,
            delivery_id=headers.get("x-github-delivery"),
            detail={"identity": identity},
        )
    except (RuntimeError, ValueError, KeyError) as exc:
        return 429 if "limit" in str(exc).lower() or "queue" in str(exc).lower() else 422, {
            "ok": False, "error": str(exc)
        }
    return 202, {"ok": True, "submission_id": row["id"], "state": row["state"]}


class Receiver:
    def __init__(self, *, config_path: Path, db_path: Path, listen_host: str, listen_port: int):
        self.config = load_submit_config(config_path)
        self.store = Store(db_path)
        self.secret = os.environ.get("AIRLOCK_GITHUB_WEBHOOK_SECRET", "")
        if not self.secret:
            raise RuntimeError("AIRLOCK_GITHUB_WEBHOOK_SECRET is required")
        self.client = GitHubReadClient(os.environ.get("GITHUB_READ_TOKEN"))
        self.listen_host = listen_host
        self.listen_port = listen_port

    def serve(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/github/webhook":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                headers = {k.lower(): v for k, v in self.headers.items()}
                code, response = handle_webhook(
                    body=body,
                    headers=headers,
                    config=outer.config,
                    store=outer.store,
                    webhook_secret=outer.secret,
                    github_client=outer.client,
                )
                data = json.dumps(response).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer((self.listen_host, self.listen_port), Handler)
        try:
            server.serve_forever()
        finally:
            self.store.close()
