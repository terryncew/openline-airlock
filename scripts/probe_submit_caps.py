#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from airlock_submit.store import Store


def post(url: str, secret: str, payload: dict, delivery: str) -> tuple[int, dict]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GitHub-Event", "issue_comment")
    req.add_header("X-GitHub-Delivery", delivery)
    req.add_header("X-Hub-Signature-256", sig)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> int:
    ap = argparse.ArgumentParser(description="Live HTTP probe for Airlock's one-open-candidate spam control")
    ap.add_argument("--receiver", required=True, help="full webhook URL, e.g. http://127.0.0.1:8787/github/webhook")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--issue", required=True, type=int)
    ap.add_argument("--submitter", required=True)
    ap.add_argument("--source-repo", required=True)
    ap.add_argument("--source-sha", required=True)
    ap.add_argument("--secret-env", default="AIRLOCK_GITHUB_WEBHOOK_SECRET")
    ap.add_argument("--output", type=Path, default=Path("airlock-submit-cap-proof.json"))
    ap.add_argument("--cleanup-db", type=Path)
    args = ap.parse_args()

    secret = os.environ.get(args.secret_env, "")
    if not secret:
        raise SystemExit(f"{args.secret_env} is required")
    if len(args.source_sha) != 40:
        raise SystemExit("--source-sha must be a full 40-character commit SHA")

    payload = {
        "action": "created",
        "repository": {"full_name": args.repo},
        "issue": {"number": args.issue, "title": "Airlock live cap probe"},
        "sender": {"login": args.submitter},
        "comment": {"body": f"/airlock submit {args.source_repo}@{args.source_sha}"},
    }
    nonce = uuid.uuid4().hex
    first_status, first = post(args.receiver, secret, payload, f"airlock-cap-{nonce}-1")
    second_status, second = post(args.receiver, secret, payload, f"airlock-cap-{nonce}-2")

    passed = (
        first_status == 202
        and bool(first.get("submission_id"))
        and second_status == 422
        and "already active" in str(second.get("error", "")).lower()
    )
    proof = {
        "schema": "airlock.submit.cap-proof.v1",
        "probe": "one_open_candidate_per_submitter_issue",
        "receiver": args.receiver,
        "repo": args.repo,
        "issue": args.issue,
        "submitter": args.submitter,
        "source_repo": args.source_repo,
        "source_sha": args.source_sha,
        "first_status": first_status,
        "first_response": first,
        "second_status": second_status,
        "second_response": second,
        "passed": passed,
        "probed_at_unix": int(time.time()),
    }
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")

    if args.cleanup_db and first.get("submission_id"):
        store = Store(args.cleanup_db)
        try:
            row = store.get(first["submission_id"])
            if row["state"] == "QUEUED":
                store.transition(row["id"], "BLOCKED", detail={"cap_probe": True})
        finally:
            store.close()

    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
