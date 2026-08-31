from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .opener import open_pr
from .receiver import Receiver
from .worker import process_one


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="airlock-submit", description="Pre-PR gate for public coding-agent contributions")
    p.add_argument("--version", action="version", version="airlock-submit 0.1.2")
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="receive authenticated GitHub issue-comment submissions")
    serve.add_argument("--config", type=Path, default=Path(".airlock/submit.json"))
    serve.add_argument("--db", type=Path, default=Path(".airlock/submit.sqlite3"))
    serve.add_argument("--listen", default="127.0.0.1:8787")

    worker = sub.add_parser("worker", help="evaluate queued submissions in secretless Docker sandboxes")
    worker.add_argument("--config", type=Path, default=Path(".airlock/submit.json"))
    worker.add_argument("--db", type=Path, default=Path(".airlock/submit.sqlite3"))
    worker.add_argument("--data", type=Path, default=Path(".airlock/submit-data"))
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-seconds", type=float, default=2.0)

    op = sub.add_parser("open-pr", help="trusted process: open a PR from one sealed survivor")
    op.add_argument("submission_id")
    op.add_argument("--config", type=Path, default=Path(".airlock/submit.json"))
    op.add_argument("--db", type=Path, default=Path(".airlock/submit.sqlite3"))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        host, port = args.listen.rsplit(":", 1)
        Receiver(config_path=args.config, db_path=args.db, listen_host=host, listen_port=int(port)).serve()
        return 0
    if args.command == "worker":
        while True:
            row = process_one(config_path=args.config, db_path=args.db, data_dir=args.data)
            if row:
                print(json.dumps({"submission_id": row["id"], "state": row["state"]}))
            if args.once:
                return 0
            if not row:
                time.sleep(max(0.2, args.poll_seconds))
    if args.command == "open-pr":
        result = open_pr(submission_id=args.submission_id, config_path=args.config, db_path=args.db,
                         evaluation_key=os.environ.get("AIRLOCK_EVALUATION_KEY"))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
