from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .verification import verify_offline


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"could not read Airlock record: {path}") from exc
    if not isinstance(obj, dict):
        raise RuntimeError(f"Airlock record is not an object: {path}")
    return obj


def _repo_path(repo: Path, value: str) -> Path:
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise RuntimeError(f"Airlock record points outside the repository: {value}") from exc
    return path


def _prompt_source(repo: Path, run_id: str | None) -> str | None:
    if not run_id:
        return None
    path = repo / ".airlock" / "runs" / run_id / "prompt.txt"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("Source: https://github.com/") and "/issues/" in stripped:
            return stripped.removeprefix("Source: ").strip()
    token = text.strip()
    if token.startswith("https://github.com/") and "/issues/" in token and "\n" not in token:
        return token
    return None


def _latest_ready_swarm(repo: Path) -> Path:
    root = repo / ".airlock" / "swarms"
    if not root.exists():
        raise RuntimeError("no READY Airlock swarm is available for review")
    for path in sorted(root.glob("*/swarm.json"), reverse=True):
        try:
            report = _read_json(path)
        except RuntimeError:
            continue
        if report.get("status") == "READY" and isinstance(report.get("verification_file"), str):
            return path
    raise RuntimeError("no READY Airlock swarm is available for review")


def _command_row(row: dict) -> dict:
    argv = row.get("argv")
    if not isinstance(argv, list):
        argv = []
    clean_argv = [str(part) for part in argv]
    return {
        "argv": clean_argv,
        "command": shlex.join(clean_argv),
        "kind": row.get("kind") if isinstance(row.get("kind"), str) else None,
        "exit_code": row.get("exit_code") if isinstance(row.get("exit_code"), int) else None,
        "timed_out": bool(row.get("timed_out", False)),
        "duration_seconds": row.get("duration_seconds") if isinstance(row.get("duration_seconds"), (int, float)) else None,
        "stdout_sha256": row.get("stdout_sha256") if isinstance(row.get("stdout_sha256"), str) else None,
        "stderr_sha256": row.get("stderr_sha256") if isinstance(row.get("stderr_sha256"), str) else None,
    }


def build_review(repo: Path, *, swarm_file: str | None = None) -> dict:
    """Build a read-only human review packet from a READY swarm and its signed record."""
    repo = repo.resolve()
    swarm_path = _repo_path(repo, swarm_file) if swarm_file else _latest_ready_swarm(repo)
    swarm = _read_json(swarm_path)
    if swarm.get("status") != "READY":
        raise RuntimeError(f"Airlock swarm is not READY: {swarm_path}")

    verification_value = swarm.get("verification_file")
    if not isinstance(verification_value, str) or not verification_value:
        raise RuntimeError(f"READY swarm has no verification record: {swarm_path}")
    verification_path = _repo_path(repo, verification_value)
    if not verification_path.is_file():
        raise RuntimeError(f"verification record is missing: {verification_path}")

    key_path = repo / ".airlock" / "verification.key"
    if not key_path.is_file():
        raise RuntimeError("local verification key is missing")

    verified = verify_offline(repo, verification_path, key_path)
    if not verified.get("valid"):
        failed = [row.get("check") for row in verified.get("checks", []) if not row.get("ok")]
        suffix = ", ".join(str(name) for name in failed if name) or "unknown verification failure"
        raise RuntimeError(f"verification record is invalid: {suffix}")

    signed = _read_json(verification_path)
    payload = signed.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("verification record has no payload")
    if payload.get("schema") != "airlock.verification.v1" or payload.get("decision") != "READY_FOR_REVIEW":
        raise RuntimeError("verification record is not a READY_FOR_REVIEW Airlock record")

    final_run_id = swarm.get("final_run_id")
    if isinstance(final_run_id, str) and payload.get("run_id") != final_run_id:
        raise RuntimeError("swarm and verification record disagree on run id")
    ready_branch = swarm.get("ready_branch")
    if isinstance(ready_branch, str) and payload.get("candidate_branch") != ready_branch:
        raise RuntimeError("swarm and verification record disagree on candidate branch")
    ready_candidate = swarm.get("ready_candidate_id")
    if isinstance(ready_candidate, str) and payload.get("source_candidate_id") != ready_candidate:
        raise RuntimeError("swarm and verification record disagree on candidate id")

    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    command_records = evidence.get("commands") if isinstance(evidence.get("commands"), list) else []
    commands = [_command_row(row) for row in command_records if isinstance(row, dict)]
    pr = swarm.get("pull_request") if isinstance(swarm.get("pull_request"), dict) else {}
    pr_url = pr.get("url") if pr.get("status") == "CREATED" and isinstance(pr.get("url"), str) else None

    changed_paths = payload.get("changed_paths")
    if not isinstance(changed_paths, list) or not all(isinstance(path, str) for path in changed_paths):
        raise RuntimeError("verification record has invalid changed paths")

    return {
        "schema": "airlock.review.v1",
        "receipt_valid": True,
        "issue": _prompt_source(repo, final_run_id if isinstance(final_run_id, str) else None),
        "pr_url": pr_url,
        "swarm_id": swarm.get("swarm_id"),
        "run_id": payload.get("run_id"),
        "base_commit": payload.get("base_commit"),
        "candidate_commit": payload.get("candidate_commit"),
        "candidate_branch": payload.get("candidate_branch"),
        "model": payload.get("model"),
        "changed_paths": changed_paths,
        "commands": commands,
        "coverage_check": evidence.get("coverage_check"),
        "config_sha256": payload.get("config_sha256"),
        "prompt_sha256": payload.get("prompt_sha256"),
        "verification_record": str(verification_path.relative_to(repo)),
        "verification_record_sha256": verified.get("record_sha256"),
        "verification_checks": verified.get("checks", []),
        "reported_cost_usd": payload.get("reported_cost"),
        "what_this_review_means": (
            "This is a read-only reduction of the signed Airlock survivor record. "
            "Review does not rerun candidate code, choose between candidates, or merge anything."
        ),
    }


def _short(value: object) -> str:
    return str(value)[:12] if value else "unknown"


def render_review(report: dict) -> str:
    lines = ["Airlock review", "Receipt: VALID"]
    if report.get("issue"):
        lines.append(f"Issue: {report['issue']}")
    if report.get("pr_url"):
        lines.append(f"PR: {report['pr_url']}")
    lines.extend([
        f"Base: {_short(report.get('base_commit'))}",
        f"Candidate: {_short(report.get('candidate_commit'))}",
        "Changed",
    ])
    changed = report.get("changed_paths", [])
    if changed:
        lines.extend(f"  • {path}" for path in changed)
    else:
        lines.append("  • none")

    lines.append("Checks")
    commands = report.get("commands", [])
    if commands:
        for row in commands:
            ok = row.get("exit_code") == 0 and not row.get("timed_out")
            duration = row.get("duration_seconds")
            suffix = f" ({duration:.2f}s)" if isinstance(duration, (int, float)) else ""
            lines.append(f"  {'✓' if ok else '✗'} {row.get('command') or '<unknown command>'}{suffix}")
    else:
        lines.append("  • no command records")

    lines.extend([
        "Evidence",
        f"  config {_short(report.get('config_sha256'))}",
        f"  record {_short(report.get('verification_record_sha256'))}",
    ])
    if report.get("reported_cost_usd") is not None:
        lines.append(f"Reported cost: ${report['reported_cost_usd']}")
    else:
        lines.append("Reported cost: unknown")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airlock review",
        description="Reduce one signed Airlock survivor into the evidence a human needs to review it.",
    )
    parser.add_argument("swarm_file", nargs="?", help="Optional .airlock/swarms/.../swarm.json; defaults to latest READY swarm.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true", help="Print the review packet as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_review(Path(args.repo), swarm_file=args.swarm_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_review(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
