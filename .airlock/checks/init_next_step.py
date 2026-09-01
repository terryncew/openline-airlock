from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from airlock import cli


def git(repo: Path, *args: str) -> None:
    cp = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} failed")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="airlock-init-next-step-") as td:
        repo = Path(td)
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.name", "Airlock check")
        git(repo, "config", "user.email", "airlock-check@example.invalid")

        (repo / ".airlock").mkdir()
        config = {
            "schema": "airlock.config.v1",
            "parallelism": 1,
            "protected_paths": [],
            "verification": {
                "static_commands": [],
                "test_commands": [["python", "-c", "pass"]],
                "target_commands": [],
                "timeout_seconds": 30,
                "coverage_mode": "changed-module-reference",
            },
            "providers": {},
            "init_baseline": {},
        }
        (repo / ".airlock" / "config.json").write_text(
            json.dumps(config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "fixture")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.command_init(argparse.Namespace(repo=str(repo), timeout=30))
        output = buf.getvalue()

        if rc != 0:
            print(output, file=sys.stderr)
            print(f"airlock init returned {rc}", file=sys.stderr)
            return 1
        if "  airlock solve 417" not in output:
            print(output, file=sys.stderr)
            print("expected init to recommend: airlock solve 417", file=sys.stderr)
            return 1
        if 'airlock swarm "fix issue #417"' in output:
            print(output, file=sys.stderr)
            print("init still recommends the old swarm path", file=sys.stderr)
            return 1

    print("init next-step check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
