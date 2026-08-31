from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import save as save_config
from .discovery import discover_commands, protected_patterns, run_baseline
from .gitops import ensure_clean, root
from .providers import builtin_providers
from .verification import ensure_key, verify_offline
from .runner import run_tournament
from .util import write_json


def _update_local_exclude(repo: Path) -> None:
    # Keep generated verification files/keys out of git status without modifying the repo's tracked .gitignore.
    git_dir = repo / ".git"
    if not git_dir.is_dir():
        return
    path = git_dir / "info" / "exclude"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    entries = [
        ".airlock/runs/",
        ".airlock/records/",
        ".airlock/index.json",
        ".airlock/verification.key",
    ]
    missing = [row for row in entries if row not in existing.splitlines()]
    if missing:
        with path.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n# OpenLine Airlock local artifacts\n")
            for row in missing:
                f.write(row + "\n")


def command_init(args: argparse.Namespace) -> int:
    repo = root(Path(args.repo).resolve())
    ensure_clean(repo)
    commands = discover_commands(repo)
    protected = protected_patterns(repo)
    baseline = run_baseline(repo, commands, timeout=args.timeout)

    config = {
        "schema": "airlock.config.v1",
        "parallelism": 4,
        "protected_paths": protected,
        "verification": {
            "static_commands": commands["static"],
            "test_commands": commands["tests"],
            "target_commands": [],
            "timeout_seconds": args.timeout,
            "coverage_mode": "changed-module-reference",
        },
        "providers": builtin_providers(),
        "init_baseline": baseline,
    }
    config_path = repo / ".airlock" / "config.json"
    save_config(config_path, config)
    ensure_key(repo / ".airlock" / "verification.key")
    _update_local_exclude(repo)

    print("OpenLine Airlock")
    print(f"Repository: {repo}")
    print("\nFound checks:")
    rows = commands["static"] + commands["tests"]
    if rows:
        for argv in rows:
            print("  ✓ " + " ".join(argv))
    else:
        print("  none")
    print("\nProtected automatically:")
    for pattern in protected:
        print(f"  • {pattern}")
    print(f"\nBaseline: {'GREEN' if baseline['green'] else 'NOT GREEN'}")
    print(f"Config: {config_path.relative_to(repo)}")
    if config["providers"]:
        print("Agent adapters found: " + ", ".join(sorted(config["providers"])))
    else:
        print("Agent adapters found: none (add provider commands to .airlock/config.json)")

    if not rows:
        print("\nAirlock needs at least one test, lint, or typecheck command before it can run unattended.")
        return 2
    if not baseline["green"]:
        print("\nAirlock will not start a tournament from a failing baseline.")
        return 2
    return 0


def command_run(args: argparse.Namespace) -> int:
    repo = root(Path(args.repo).resolve())
    config_path = repo / ".airlock" / "config.json"
    if not config_path.exists():
        print("ERROR: .airlock/config.json is missing; run `airlock init` first", file=sys.stderr)
        return 2
    models = [item.strip() for item in (args.models or "").split(",") if item.strip()]
    try:
        report = run_tournament(
            repo,
            args.issue_or_prompt,
            agents=args.agents,
            models=models,
            budget=args.budget,
            open_pr=not args.no_pr,
            config_path=config_path,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0 if report.get("status") == "READY" else 3


def command_verify(args: argparse.Namespace) -> int:
    repo = root(Path(args.repo).resolve())
    verification_path = Path(args.verification_file)
    if not verification_path.is_absolute():
        verification_path = (repo / verification_path).resolve()
    key_path = repo / ".airlock" / "verification.key"
    if not key_path.exists():
        print("ERROR: local verification key missing", file=sys.stderr)
        return 2
    try:
        result = verify_offline(repo, verification_path, key_path)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("AIRLOCK RECORD: " + ("VALID" if result["valid"] else "INVALID"))
    for row in result["checks"]:
        print(f"  {'✓' if row['ok'] else '✗'} {row['check']}")
    print(f"Verification file SHA-256: {result['record_sha256']}")
    return 0 if result["valid"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock",
        description="Run more coding agents than you could ever review. Only verified patches get through.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Find your repo checks, protect tests/config, and confirm the baseline is green.")
    init.add_argument("--repo", default=".")
    init.add_argument("--timeout", type=int, default=1200)
    init.set_defaults(func=command_init)

    runp = sub.add_parser("run", help="Run the same task across multiple coding agents and block patches that fail your repo checks.")
    runp.add_argument("issue_or_prompt")
    runp.add_argument("--repo", default=".")
    runp.add_argument("--agents", "-n", type=int, default=12)
    runp.add_argument("--models", help="Comma-separated provider aliases from .airlock/config.json")
    runp.add_argument("--budget", type=float, help="Recorded swarm budget; passed per-agent as AIRLOCK_BUDGET_USD")
    runp.add_argument("--no-pr", action="store_true", help="Keep the surviving branch local instead of attempting a GitHub PR.")
    runp.set_defaults(func=command_run)

    verify = sub.add_parser("verify", help="Verify an Airlock verification record offline.")
    verify.add_argument("verification_file")
    verify.add_argument("--repo", default=".")
    verify.set_defaults(func=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
