from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from .model import require_state

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY,
  repo TEXT NOT NULL,
  issue_number INTEGER NOT NULL,
  issue_title TEXT NOT NULL,
  submitter TEXT NOT NULL,
  source_repo TEXT NOT NULL,
  source_sha TEXT NOT NULL,
  base_sha TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  artifact_dir TEXT,
  delivery_id TEXT UNIQUE,
  detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_candidate_per_submitter_issue
ON submissions(repo, issue_number, submitter)
WHERE state IN ('RECEIVED','QUEUED','EVALUATING','SURVIVED');
CREATE INDEX IF NOT EXISTS submissions_state_created ON submissions(state, created_at);
CREATE INDEX IF NOT EXISTS submissions_submitter_created ON submissions(submitter, created_at);
"""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def daily_count(self, submitter: str, *, now: int | None = None) -> int:
        now = int(time.time() if now is None else now)
        since = now - 86400
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM submissions WHERE submitter=? AND created_at>=?",
            (submitter, since),
        ).fetchone()
        return int(row["n"])

    def active_count(self, repo: str | None = None) -> int:
        states = ("RECEIVED", "QUEUED", "EVALUATING", "SURVIVED")
        if repo:
            row = self.db.execute(
                "SELECT COUNT(*) AS n FROM submissions WHERE repo=? AND state IN (?,?,?,?)",
                (repo, *states),
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT COUNT(*) AS n FROM submissions WHERE state IN (?,?,?,?)",
                states,
            ).fetchone()
        return int(row["n"])

    def create(self, *, repo: str, issue_number: int, issue_title: str, submitter: str,
               source_repo: str, source_sha: str, base_sha: str, delivery_id: str | None = None,
               detail: dict | None = None, now: int | None = None) -> dict:
        now = int(time.time() if now is None else now)
        sid = "sub_" + uuid.uuid4().hex[:16]
        try:
            self.db.execute(
                """INSERT INTO submissions
                   (id,repo,issue_number,issue_title,submitter,source_repo,source_sha,base_sha,state,created_at,updated_at,delivery_id,detail_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, repo, int(issue_number), issue_title, submitter, source_repo, source_sha,
                 base_sha, "QUEUED", now, now, delivery_id, json.dumps(detail or {}, sort_keys=True)),
            )
            self.db.commit()
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "delivery_id" in message:
                raise RuntimeError("GitHub webhook delivery was already processed") from exc
            raise RuntimeError("one open Airlock candidate is already active for this submitter and issue") from exc
        return self.get(sid)

    def get(self, sid: str) -> dict:
        row = self.db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise KeyError(sid)
        obj = dict(row)
        obj["detail"] = json.loads(obj.pop("detail_json") or "{}")
        return obj

    def next_queued(self) -> dict | None:
        row = self.db.execute(
            "SELECT id FROM submissions WHERE state='QUEUED' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return self.get(row["id"]) if row else None

    def transition(self, sid: str, state: str, *, artifact_dir: str | None = None,
                   detail: dict | None = None, now: int | None = None) -> dict:
        require_state(state)
        now = int(time.time() if now is None else now)
        current = self.get(sid)
        merged = dict(current.get("detail") or {})
        if detail:
            merged.update(detail)
        self.db.execute(
            "UPDATE submissions SET state=?, updated_at=?, artifact_dir=COALESCE(?, artifact_dir), detail_json=? WHERE id=?",
            (state, now, artifact_dir, json.dumps(merged, sort_keys=True), sid),
        )
        self.db.commit()
        return self.get(sid)
