#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from airlock.gitops import head  # noqa: E402
from airlock.nightshift import run_nightshift  # noqa: E402
from airlock.util import canonical_json_bytes, sha256_bytes, sha256_file, write_json  # noqa: E402
from airlock.verification import ensure_key, sign  # noqa: E402

PREREG = ROOT / ".airlock" / "hermes-live-001.json"
OBJECTIVE = ROOT / ".airlock" / "objective.json"
CONFIG = ROOT / ".airlock" / "config.json"
EVALUATOR = ROOT / ".airlock" / "checks" / "hermes_live_001_measure.py"
WORKER = ROOT / ".airlock" / "checks" / "hermes_live_001_worker.py"
THIS = Path(__file__).resolve()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*args: str, check: bool = True) -> str:
    cp = subprocess.run(
        ["git", *args], cwd=ROOT, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} failed")
    return cp.stdout.strip()


def remote_main() -> str:
    cp = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/main"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=60,
    )
    if cp.returncode != 0:
        raise RuntimeError("could not read origin/main: " + (cp.stderr.strip() or "git ls-remote failed"))
    line = cp.stdout.strip().splitlines()
    if len(line) != 1 or len(line[0].split()) < 1:
        raise RuntimeError("origin/main did not resolve to exactly one SHA")
    sha = line[0].split()[0]
    if len(sha) != 40:
        raise RuntimeError("origin/main returned a non-40-character SHA")
    return sha


def committed_unchanged(path: Path, commit: str) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    cp = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return cp.returncode == 0 and hashlib.sha256(cp.stdout).hexdigest() == sha256_file(path)


def load_prereg() -> dict:
    value = json.loads(PREREG.read_text())
    if value.get("schema") != "airlock.hermes-live-001.prereg.v1":
        raise RuntimeError("unexpected HERMES-LIVE-001 preregistration schema")
    return value


def verify_frozen(prereg: dict, run_base: str) -> dict:
    if git("status", "--porcelain"):
        raise RuntimeError("working tree must be clean before HERMES-LIVE-001")
    architecture = prereg["architecture_base_sha"]
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", architecture, run_base], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode != 0:
        raise RuntimeError("run base is not descended from the frozen Airlock architecture base")

    observed = {}
    for rel, expected in prereg["frozen_files"].items():
        path = ROOT / rel
        if not path.is_file():
            raise RuntimeError(f"frozen file missing: {rel}")
        digest = sha256_file(path)
        if digest != expected:
            raise RuntimeError(f"frozen file hash mismatch: {rel}")
        if not committed_unchanged(path, run_base):
            raise RuntimeError(f"frozen file is not committed unchanged at the run base: {rel}")
        observed[rel] = digest
    if not committed_unchanged(PREREG, run_base):
        raise RuntimeError("preregistration itself must be committed unchanged before generation 1")
    return observed


def patch_sha(base: str, candidate: str | None) -> str | None:
    if not candidate or candidate == base:
        return None
    cp = subprocess.run(
        ["git", "diff", "--binary", f"{base}..{candidate}"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if cp.returncode != 0:
        return None
    return hashlib.sha256(cp.stdout).hexdigest()


def generation_payload(report: dict) -> dict:
    rows = report.get("generations") or []
    if not rows:
        return {}
    path = ROOT / str(rows[0].get("receipt"))
    try:
        return json.loads(path.read_text()).get("payload", {})
    except Exception:
        return {}


def classify_attempt(report: dict, generation: dict, run_base: str) -> dict:
    candidates = generation.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    worker = candidate.get("worker") or {}
    execution = worker.get("agent_execution") or {}
    audit = (worker.get("agent_report") or {}).get("authority_audit") or {}
    authority_ok = bool(
        audit.get("schema") == "airlock.hermes-live-001.authority.v1"
        and audit.get("worker") == "hermes"
        and audit.get("release_authority") == "ABSENT"
        and audit.get("hermes_home_present") is True
        and audit.get("github_credential_present") is False
        and not audit.get("forbidden_environment_names_present")
    )

    candidate_commit = candidate.get("commit")
    tournament_disposition = candidate.get("tournament_disposition")
    reason = candidate.get("reason") or candidate.get("tournament_reason")

    if execution.get("timed_out") and (not candidate_commit or candidate_commit == run_base):
        disposition = "WORKER_TIMEOUT"
    elif execution and execution.get("exit_code") not in (0, None) and (not candidate_commit or candidate_commit == run_base):
        disposition = "INFRA_FAILURE"
    elif report.get("accepted_generations", 0) > 0:
        disposition = "SURVIVED"
    elif tournament_disposition == "NEEDS_EVIDENCE":
        disposition = "NEEDS_EVIDENCE"
    elif tournament_disposition == "BLOCKED" or candidate:
        disposition = "BLOCKED"
    else:
        disposition = "INFRA_FAILURE"
        reason = reason or report.get("status") or "NO_GENERATION_RECORD"

    return {
        "disposition": disposition,
        "reason": reason,
        "candidate_commit": candidate_commit,
        "patch_sha256": patch_sha(run_base, candidate_commit),
        "changed_paths": candidate.get("changed_paths", []),
        "checks": candidate.get("structural_checks", []),
        "measurement": candidate.get("measurement"),
        "worker": worker,
        "authority_audit_valid": authority_ok,
        "objective_cleared": candidate.get("disposition") == "ELIGIBLE",
    }


def signed_terminal_report(payload: dict, output_dir: Path) -> tuple[str, str]:
    key = ensure_key(ROOT / ".airlock" / "verification.key")
    record = sign(payload, key)
    path = output_dir / "report.json"
    write_json(path, record)
    return path.relative_to(ROOT).as_posix(), sha256_file(path)


def run(args: argparse.Namespace) -> int:
    prereg = load_prereg()
    run_base = head(ROOT)
    frozen = verify_frozen(prereg, run_base)
    if not os.environ.get("HERMES_HOME"):
        raise RuntimeError("set HERMES_HOME to the real persistent Hermes home before the live run")

    main_start = remote_main()
    if args.expect_main_move:
        # The control is allowed to start only from the current target branch.
        if main_start != run_base:
            raise RuntimeError("standing-stress mode must start with local HEAD exactly equal to origin/main")
    elif main_start != run_base:
        raise RuntimeError("pull current main first; HERMES-LIVE-001 refuses to start from a stale base")

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output_dir = ROOT / ".airlock" / "improvements" / "HERMES-LIVE-001" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    started_monotonic = time.monotonic()
    started_at = utcnow()
    attempts = []
    final_status = "EXHAUSTED_NO_SURVIVOR"
    stale_event = None

    max_attempts = int(prereg["run_bounds"]["max_attempts"])
    max_wall = int(prereg["run_bounds"]["max_wall_seconds"])
    wait_main = int(args.wait_main_seconds)

    for number in range(1, max_attempts + 1):
        if time.monotonic() - started_monotonic >= max_wall:
            final_status = "EXHAUSTED_WALL_CLOCK"
            break
        if head(ROOT) != run_base:
            final_status = "LOCAL_BASE_MOVED_FAIL_CLOSED"
            break

        before_main = remote_main()
        if before_main != main_start:
            final_status = "STALE_BASE_FAIL_CLOSED"
            stale_event = {"attempt": number, "before": before_main, "expected": main_start}
            break

        attempt_started = utcnow()
        try:
            report = run_nightshift(
                ROOT,
                objective_path=".airlock/objective.json",
                generations=1,
                agents=1,
                profiles=[],
                budget=args.budget_per_attempt,
                config_path=CONFIG,
            )
            generation = generation_payload(report)
            classified = classify_attempt(report, generation, run_base)
            classified.update({
                "attempt": number,
                "started_at": attempt_started,
                "ended_at": utcnow(),
                "nightshift_report": report.get("report_file"),
                "nightshift_report_sha256": report.get("report_sha256"),
                "main_sha_before": before_main,
                "base_sha": run_base,
            })
        except Exception as exc:
            classified = {
                "attempt": number,
                "started_at": attempt_started,
                "ended_at": utcnow(),
                "disposition": "INFRA_FAILURE",
                "reason": type(exc).__name__,
                "detail": str(exc)[-1200:],
                "main_sha_before": before_main,
                "base_sha": run_base,
                "authority_audit_valid": False,
            }

        # The authority clock is sampled after truth evaluation and before terminal admission.
        after_main = remote_main()
        classified["main_sha_at_admission"] = after_main
        if after_main != main_start:
            classified["pre_stale_disposition"] = classified["disposition"]
            classified["disposition"] = "STALE_BASE"
            classified["reason"] = "TARGET_MAIN_MOVED_DURING_RUN"
            stale_event = {"attempt": number, "before": main_start, "after": after_main}
            attempts.append(classified)
            final_status = "STALE_BASE_FAIL_CLOSED"
            break

        attempts.append(classified)

        if args.expect_main_move:
            deadline = time.monotonic() + wait_main
            moved = None
            while time.monotonic() < deadline:
                observed = remote_main()
                if observed != main_start:
                    moved = observed
                    break
                time.sleep(10)
            if moved is None:
                final_status = "CONTROL_NOT_TRIGGERED"
                break
            attempts[-1]["main_sha_at_admission"] = moved
            attempts[-1]["pre_stale_disposition"] = attempts[-1]["disposition"]
            attempts[-1]["disposition"] = "STALE_BASE"
            attempts[-1]["reason"] = "TARGET_MAIN_MOVED_BEFORE_TERMINAL_ADMISSION"
            stale_event = {"attempt": number, "before": main_start, "after": moved}
            final_status = "STALE_BASE_FAIL_CLOSED"
            break

        if classified["disposition"] == "SURVIVED":
            final_status = "SURVIVOR_FOUND"
            break
        # BLOCKED, NEEDS_EVIDENCE, WORKER_TIMEOUT and INFRA_FAILURE carry zero standing.
        # The next attempt starts again from run_base with the same persistent HERMES_HOME.

    authority_contacts = [row for row in attempts if row.get("worker")]
    authority_all_clean = bool(authority_contacts) and all(row.get("authority_audit_valid") for row in authority_contacts)
    successful_worker_contacts = [
        row for row in authority_contacts
        if (row.get("worker") or {}).get("agent_execution", {}).get("exit_code") == 0
        and not (row.get("worker") or {}).get("agent_execution", {}).get("timed_out")
        and row.get("authority_audit_valid")
    ]
    standing_reset = all(row.get("base_sha") == run_base for row in attempts)
    terminal_pass = bool(
        authority_all_clean
        and bool(successful_worker_contacts)
        and standing_reset
        and final_status in {"SURVIVOR_FOUND", "EXHAUSTED_NO_SURVIVOR", "EXHAUSTED_WALL_CLOCK", "STALE_BASE_FAIL_CLOSED"}
        and final_status != "CONTROL_NOT_TRIGGERED"
    )
    if final_status == "STALE_BASE_FAIL_CLOSED":
        # A real stale-base proof needs a real worker contact; a candidate is stronger but not required
        # for the fail-closed property itself.
        terminal_pass = terminal_pass and bool(authority_contacts)

    payload = {
        "schema": "airlock.hermes-live-001.report.v1",
        "experiment": "HERMES-LIVE-001",
        "started_at": started_at,
        "ended_at": utcnow(),
        "run_id": run_id,
        "architecture_base_sha": prereg["architecture_base_sha"],
        "run_base_sha": run_base,
        "origin_main_sha_at_start": main_start,
        "objective_sha256": frozen[".airlock/objective.json"],
        "config_sha256": frozen[".airlock/config.json"],
        "evaluator_sha256": frozen[".airlock/checks/hermes_live_001_measure.py"],
        "worker_boundary_sha256": frozen[".airlock/checks/hermes_live_001_worker.py"],
        "run_controller_sha256": frozen[".airlock/checks/hermes_live_001_run.py"],
        "authority_receipt_code_sha256": frozen["src/airlock/runner.py"],
        "preregistration_sha256": sha256_file(PREREG),
        "run_bounds": prereg["run_bounds"],
        "attempts": attempts,
        "attempt_count": len(attempts),
        "final_status": final_status,
        "stale_event": stale_event,
        "authority_contacts_observed": len(authority_contacts),
        "successful_worker_contacts_observed": len(successful_worker_contacts),
        "zero_repo_credential_contact_observed": authority_all_clean,
        "standing_reset_observed": standing_reset,
        "terminal_architecture_pass": terminal_pass,
        "promoted_commit": next((row.get("candidate_commit") for row in attempts if row.get("disposition") == "SURVIVED"), None),
        "truth_clock_scope": "Frozen repository checks plus the protected HERMES-LIVE-001 objective evaluator.",
        "authority_clock_scope": "Fresh origin/main standing plus the exact pre-exec Hermes environment audit at terminal admission.",
        "time_clock_scope": "Not tested. This experiment is not a sub-second physical feasibility controller.",
        "stopping_rule": prereg["stopping_rule"],
        "claim_boundary": prereg["claim_boundary"],
    }
    report_file, report_sha = signed_terminal_report(payload, output_dir)
    print(json.dumps({
        "final_status": final_status,
        "terminal_architecture_pass": terminal_pass,
        "attempts": len(attempts),
        "report_file": report_file,
        "report_sha256": report_sha,
    }, indent=2, sort_keys=True))
    return 0 if terminal_pass else 3


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the frozen HERMES-LIVE-001 terminal proof.")
    p.add_argument("--budget-per-attempt", type=float, default=None)
    p.add_argument(
        "--expect-main-move", action="store_true",
        help="Require a real origin/main movement before terminal admission; fail closed when it occurs.",
    )
    p.add_argument(
        "--wait-main-seconds", type=int, default=900,
        help="After the first Hermes attempt, wait this long for the pre-registered main-move control (default: 900).",
    )
    return p


if __name__ == "__main__":
    try:
        raise SystemExit(run(parser().parse_args()))
    except Exception as exc:
        print(f"HERMES-LIVE-001 PRECONDITION ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
