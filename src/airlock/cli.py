from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path

from . import __version__
from .adoption import install_github
from .autopilot import run_autopilot
from .config import load as load_config, save as save_config
from .discovery import discovery_metadata, discover_commands, protected_patterns, run_baseline
from .gitops import ensure_clean, root
from .providers import builtin_providers
from .runner import run_tournament
from .swarm import run_swarm
from .util import run
from .verification import ensure_key, verify_offline


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
        ".airlock/swarms/",
        ".airlock/autopilot/",
    ]
    missing = [row for row in entries if row not in existing.splitlines()]
    if missing:
        with path.open("a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n# OpenLine Airlock local artifacts\n")
            for row in missing:
                f.write(row + "\n")


def _configured_commands(config: dict) -> dict[str, list[list[str]]]:
    verification = config.get("verification", {})
    return {
        "static": verification.get("static_commands", []),
        "tests": verification.get("test_commands", []),
    }


def _has_commands(commands: dict[str, list[list[str]]]) -> bool:
    return bool(commands.get("static") or commands.get("tests"))


def _command_text(argv: list[str]) -> str:
    return shlex.join(str(part) for part in argv)


def _print_project(metadata: dict, *, baseline_green: bool = False) -> None:
    print("Project")
    runners = set(metadata["test_runners"])
    runner_for = {
        "Python": "pytest",
        "Node": "npm test",
        "Rust": "cargo test",
        "Go": "go test",
    }
    shown_runners: set[str] = set()
    if metadata["project_types"]:
        for project_type in metadata["project_types"]:
            runner = runner_for.get(project_type)
            if runner in runners:
                print(f"  ✓ {project_type} / {runner}")
                shown_runners.add(runner)
            else:
                print(f"  ✓ {project_type}")
    else:
        print("  • Project type not identified")
    for runner in metadata["test_runners"]:
        if runner not in shown_runners:
            print(f"  ✓ {runner}")
    if metadata["test_count"] is not None:
        noun = "test" if metadata["test_count"] == 1 else "tests"
        print(f"  ✓ {metadata['test_count']} {noun} found")
    for tool in metadata["quality_tools"]:
        print(f"  ✓ {tool}")
    if baseline_green:
        print("  ✓ Starting repo passes its checks")


def _print_no_checks(metadata: dict) -> None:
    print("Airlock couldn't find enough checks to run unattended.")
    print("I found:")
    if metadata["project_types"]:
        for project_type in metadata["project_types"]:
            print(f"  ✓ {project_type} project")
    else:
        print("  ✗ No supported project type")
    if metadata["test_runners"]:
        for runner in metadata["test_runners"]:
            print(f"  ✓ {runner}")
    else:
        print("  ✗ No test command")
    if metadata["quality_tools"]:
        for tool in metadata["quality_tools"]:
            print(f"  ✓ {tool}")
    else:
        print("  ✗ No lint or type check")
    print("\nStarter Rules draft saved to .airlock/config.json.")
    print("Add a check or edit .airlock/config.json, then run:")
    print("  airlock init")


def _print_failed_baseline(baseline: dict) -> None:
    print("Airlock found your Starter Rules, but the repo does not currently pass them.")
    print("Airlock won't start autonomous search from a broken starting point.")
    print("Failed:")
    failed = [
        row for row in baseline.get("commands", [])
        if row.get("exit_code") != 0 or row.get("timed_out") or row.get("side_effect")
    ]
    for row in failed:
        detail = ""
        if row.get("timed_out"):
            detail = " (timed out)"
        elif row.get("side_effect"):
            detail = " (changed tracked files while running)"
        elif row.get("exit_code") == 127:
            detail = " (could not run)"
        print(f"  ✗ {_command_text(row['argv'])}{detail}")
    print("Fix the starting repo and run airlock init again.")


def command_init(args: argparse.Namespace) -> int:
    repo = root(Path(args.repo).resolve())
    ensure_clean(repo)
    config_path = repo / ".airlock" / "config.json"
    discovered = discover_commands(repo)
    detected_protected = protected_patterns(repo)
    detected_providers = builtin_providers()

    if config_path.exists():
        try:
            config = load_config(config_path)
        except Exception as exc:
            print("Airlock found .airlock/config.json, but couldn't read its Starter Rules.")
            print(f"  {exc}")
            print("Fix the file and run airlock init again.")
            return 2
        commands = _configured_commands(config)
        if not _has_commands(commands) and _has_commands(discovered):
            verification = config.setdefault("verification", {})
            verification["static_commands"] = discovered["static"]
            verification["test_commands"] = discovered["tests"]
            existing_protected = config.get("protected_paths", [])
            config["protected_paths"] = list(dict.fromkeys(existing_protected + detected_protected))
            commands = discovered
        providers = config.setdefault("providers", {})
        for name, provider in detected_providers.items():
            providers.setdefault(name, provider)
        protected = config.setdefault("protected_paths", detected_protected)
        timeout = int(config.get("verification", {}).get("timeout_seconds", args.timeout))
    else:
        commands = discovered
        protected = detected_protected
        timeout = args.timeout
        config = {
            "schema": "airlock.config.v1",
            "parallelism": 4,
            "protected_paths": protected,
            "verification": {
                "static_commands": commands["static"],
                "test_commands": commands["tests"],
                "target_commands": [],
                "timeout_seconds": timeout,
                "coverage_mode": "changed-module-reference",
            },
            "providers": detected_providers,
            "init_baseline": {},
        }

    baseline = run_baseline(repo, commands, timeout=timeout)
    config["init_baseline"] = baseline
    save_config(config_path, config)
    ensure_key(repo / ".airlock" / "verification.key")
    _update_local_exclude(repo)

    metadata = discovery_metadata(repo, discovered, baseline)
    if not _has_commands(commands):
        _print_no_checks(metadata)
        return 2
    if not baseline["green"]:
        _print_failed_baseline(baseline)
        return 2

    print("Airlock found your project and set up Starter Rules.")
    _print_project(metadata, baseline_green=True)
    print("Accepted patches cannot change")
    if protected:
        for pattern in protected:
            print(f"  • {pattern}")
    else:
        print("  • No paths configured")
    print("Before a patch can reach you, it must pass")
    for argv in commands["tests"] + commands["static"]:
        print(f"  • {_command_text(argv)}")
    print(f"Starter Rules saved to {config_path.relative_to(repo)}")
    print("You can change these rules whenever you want.")
    print("Next:")
    print('  airlock swarm "fix issue #417"')
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


def command_swarm(args: argparse.Namespace) -> int:
    repo = root(Path(args.repo).resolve())
    config_path = repo / ".airlock" / "config.json"
    if not config_path.exists():
        print("ERROR: .airlock/config.json is missing; run `airlock init` first", file=sys.stderr)
        return 2
    models = [item.strip() for item in (args.models or "").split(",") if item.strip()]
    try:
        report = run_swarm(
            repo,
            args.issue_or_prompt,
            agents=args.agents,
            rounds=args.rounds,
            models=models,
            budget=args.budget,
            open_pr=not args.no_pr,
            config_path=config_path,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0 if report.get("status") == "READY" else 3


def _resolve_solve_target(repo: Path, issue_or_prompt: str) -> str:
    """Turn a local GitHub issue number into a URL; leave URLs/prompts untouched."""
    token = issue_or_prompt.strip()
    number = token[1:] if token.startswith("#") else token
    if not number.isdigit():
        return issue_or_prompt
    if not shutil.which("gh"):
        raise RuntimeError(
            "`airlock solve 417` needs the GitHub CLI to resolve the issue. "
            "Pass the full GitHub issue URL or a prompt instead."
        )
    result = run(["gh", "issue", "view", number, "--json", "url"], repo, timeout=30)
    if result["exit_code"] != 0:
        detail = result.get("stderr", "").strip()[-500:]
        raise RuntimeError(f"could not resolve GitHub issue #{number}: {detail or 'gh issue view failed'}")
    try:
        url = json.loads(result["stdout"]).get("url")
    except Exception as exc:
        raise RuntimeError(f"could not parse GitHub issue #{number}") from exc
    if not isinstance(url, str) or not url.startswith("https://github.com/") or "/issues/" not in url:
        raise RuntimeError(f"GitHub did not return a usable URL for issue #{number}")
    return url


def command_solve(args: argparse.Namespace) -> int:
    """One-command path: establish Starter Rules if needed, search, then expose only a survivor."""
    repo = root(Path(args.repo).resolve())
    config_path = repo / ".airlock" / "config.json"

    if not config_path.exists():
        print("No Starter Rules yet. Airlock will inspect the repo first.\n")
        init_rc = command_init(argparse.Namespace(repo=str(repo), timeout=args.timeout))
        if init_rc != 0:
            return init_rc
        print("")

    try:
        target = _resolve_solve_target(repo, args.issue_or_prompt)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    models = [item.strip() for item in (args.models or "").split(",") if item.strip()]
    if not models:
        try:
            configured = load_config(config_path).get("providers", {})
        except Exception:
            configured = {}
        if not configured:
            models = list(builtin_providers())
    try:
        report = run_swarm(
            repo,
            target,
            agents=args.agents,
            rounds=args.rounds,
            models=models,
            budget=args.budget,
            open_pr=not args.no_pr,
            config_path=config_path,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    status = report.get("status")
    if status == "READY":
        pr = report.get("pull_request") or {}
        if pr.get("status") == "CREATED" and pr.get("url"):
            print(f"\nAirlock survivor opened for review: {pr['url']}")
        else:
            print("\nOne patch survived. Airlock left it ready for review.")
        return 0
    if status == "MULTIPLE_SURVIVORS":
        print("\nSeveral patches survived. Airlock refused to invent a winner.")
    elif status == "NO_PATCH_READY":
        print("\nNo patch earned review.")
    elif status == "BASELINE_NOT_GREEN":
        print("\nThe starting repository is red. Airlock did not spend agent attempts on it.")
    return 3


def command_autopilot(args: argparse.Namespace) -> int:
    """Work a bounded snapshot of maintainer-labeled GitHub issues without changing Starter Rules."""
    repo = root(Path(args.repo).resolve())
    _update_local_exclude(repo)

    def solve_issue(url: str, per_issue_budget: float | None) -> int:
        return command_solve(argparse.Namespace(
            issue_or_prompt=url,
            repo=str(repo),
            agents=args.agents,
            rounds=args.rounds,
            models=args.models,
            budget=per_issue_budget,
            timeout=args.timeout,
            no_pr=args.no_pr,
        ))

    try:
        report = run_autopilot(
            repo,
            label=args.label,
            max_issues=args.max_issues,
            budget=args.budget,
            retry_unchanged=args.retry_unchanged,
            solve_issue=solve_issue,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if report["attempted"] == 0:
        if report["queue_size"] == 0:
            print(f"No open issues carry the `{args.label}` label.")
        else:
            print("No changed labeled issues need another attempt.")
        return 0

    ready = sum(row["status"] == "READY" for row in report["results"])
    no_review = sum(row["status"] == "NO_REVIEW_READY" for row in report["results"])
    print("\nAirlock autopilot summary")
    print(f"Attempted: {report['attempted']}")
    print(f"Ready: {ready}")
    print(f"No review ready: {no_review}")
    print(f"Skipped unchanged: {report['skipped_unchanged']}")
    print(f"State: {report['state_file']}")
    if report["stopped_on_error"]:
        print("Stopped after an environment/setup error before spending on the rest of the queue.")
        return 2
    return 0


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


def command_install_github(args: argparse.Namespace) -> int:
    repo = root(Path(args.repo).resolve())
    try:
        result = install_github(
            repo,
            github_repo=args.github_repo,
            base_branch=args.base_branch,
            force=args.force,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("OpenLine Airlock — GitHub Actions installed")
    print(f"Repository: {result['repo']}")
    print("Mode: GitHub Actions only (no webhook service)")
    print("Workflow: .github/workflows/airlock.yml")
    print("Contribution instructions: CONTRIBUTING.md")
    print(f"Install manifest: {result['manifest']}")
    print("\nCommit these files. After merge, contributors can submit a fork commit on an issue with:")
    print("  /airlock submit USER/FORK@FULL_40_CHARACTER_COMMIT_SHA")
    return 0


def _build_solve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock solve",
        description=(
            "Give Airlock a GitHub issue or prompt. It sets up Starter Rules when needed, "
            "lets several agents search, and exposes only a surviving patch."
        ),
    )
    parser.add_argument("issue_or_prompt", help="GitHub issue number/URL or a plain-English task")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--agents", "-n", type=int, default=4, help="Agent attempts per round (default: 4).")
    parser.add_argument("--rounds", type=int, default=2, help="Search rounds (default: 2).")
    parser.add_argument("--models", help="Comma-separated provider aliases; installed adapters are used when omitted.")
    parser.add_argument("--budget", type=float, help="Recorded provider budget hint; enforcement remains provider-side.")
    parser.add_argument("--timeout", type=int, default=1200, help="Starter Rules command timeout when auto-initializing.")
    parser.add_argument("--no-pr", action="store_true", help="Keep a survivor local instead of attempting a GitHub PR.")
    parser.set_defaults(func=command_solve)
    return parser


def _build_autopilot_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock autopilot",
        description=(
            "Work a bounded queue of maintainer-labeled GitHub issues. The label chooses the work; "
            "Starter Rules still decide which patches can reach review."
        ),
    )
    parser.add_argument("--repo", default=".")
    parser.add_argument("--label", default="airlock", help="Open-issue label that authorizes work (default: airlock).")
    parser.add_argument("--max-issues", type=int, default=3, help="Maximum issues to attempt in one run (default: 3).")
    parser.add_argument("--agents", "-n", type=int, default=4, help="Agent attempts per round for each issue (default: 4).")
    parser.add_argument("--rounds", type=int, default=2, help="Search rounds for each issue (default: 2).")
    parser.add_argument("--models", help="Comma-separated provider aliases; installed adapters are used when omitted.")
    parser.add_argument("--budget", type=float, help="Total provider budget hint for this queue snapshot, divided across selected issues.")
    parser.add_argument("--timeout", type=int, default=1200, help="Starter Rules command timeout when the first issue auto-initializes.")
    parser.add_argument("--retry-unchanged", action="store_true", help="Retry issues even when their GitHub updatedAt value has not changed.")
    parser.add_argument("--no-pr", action="store_true", help="Keep survivors local instead of attempting GitHub PRs.")
    parser.set_defaults(func=command_autopilot)
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock",
        description="Spend machine attempts on software problems without turning every attempt into human review work.",
        epilog="Shortcuts: `airlock solve 417` works one issue; `airlock autopilot --label airlock` works a bounded issue queue.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Set up editable Starter Rules from the checks Airlock finds in your repo.")
    init.add_argument("--repo", default=".")
    init.add_argument("--timeout", type=int, default=1200)
    init.set_defaults(func=command_init)

    swarm = sub.add_parser(
        "swarm",
        help="Spend more agent attempts on one issue, share discoveries across rounds, and review only what survives.",
    )
    swarm.add_argument("issue_or_prompt")
    swarm.add_argument("--repo", default=".")
    swarm.add_argument("--agents", "-n", type=int, default=8, help="Agent attempts per round.")
    swarm.add_argument("--rounds", type=int, default=2, help="Search rounds; later rounds receive bounded notes from earlier ones.")
    swarm.add_argument("--models", help="Comma-separated provider aliases from .airlock/config.json")
    swarm.add_argument("--budget", type=float, help="Total recorded swarm budget hint, split evenly across rounds and attempts.")
    swarm.add_argument("--no-pr", action="store_true", help="Keep the final survivor local instead of attempting a GitHub PR.")
    swarm.set_defaults(func=command_swarm)

    runp = sub.add_parser("run", help="Run independent agent attempts once and block patches that fail your repo checks.")
    runp.add_argument("issue_or_prompt")
    runp.add_argument("--repo", default=".")
    runp.add_argument("--agents", "-n", type=int, default=12)
    runp.add_argument("--models", help="Comma-separated provider aliases from .airlock/config.json")
    runp.add_argument("--budget", type=float, help="Recorded run budget hint; passed per-agent as AIRLOCK_BUDGET_USD")
    runp.add_argument("--no-pr", action="store_true", help="Keep the surviving branch local instead of attempting a GitHub PR.")
    runp.set_defaults(func=command_run)

    verify = sub.add_parser("verify", help="Verify an Airlock verification record offline.")
    verify.add_argument("verification_file")
    verify.add_argument("--repo", default=".")
    verify.set_defaults(func=command_verify)

    install = sub.add_parser("install-github", help="Install the infrastructure-free GitHub Actions contribution gate.")
    install.add_argument("--repo", default=".")
    install.add_argument("--github-repo", help="GitHub repository in owner/name form; inferred from origin when omitted.")
    install.add_argument("--base-branch", default="main")
    install.add_argument("--force", action="store_true", help="Regenerate the maintainer-owned check-runner Dockerfile.")
    install.set_defaults(func=command_install_github)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "solve":
        args = _build_solve_parser().parse_args(raw[1:])
        return args.func(args)
    if raw and raw[0] == "autopilot":
        args = _build_autopilot_parser().parse_args(raw[1:])
        return args.func(args)
    args = build_parser().parse_args(raw)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
