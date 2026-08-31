from __future__ import annotations

from decimal import Decimal, InvalidOperation
import time
import uuid
from pathlib import Path

from .blackboard import DEFAULT_ROLES, collect_round_entries, merge_entries, render_blackboard
from .gitops import git, root
from .runner import run_tournament
from .util import write_json


def _aggregate_cost(round_reports: list[dict]) -> dict:
    total = Decimal("0")
    unknown = 0
    known = 0
    for report in round_reports:
        cost = report.get("cost", {})
        raw = cost.get("reported_cost_usd_total")
        if raw is not None:
            try:
                total += Decimal(str(raw))
            except (InvalidOperation, ValueError):
                pass
        known += int(cost.get("known_candidates", 0) or 0)
        unknown += int(cost.get("unknown_candidates", 0) or 0)
    return {
        "reported_cost_usd_total": format(total, "f"),
        "known_candidates": known,
        "unknown_candidates": unknown,
        "complete": unknown == 0,
    }


def _delete_branch(repo: Path, branch: str | None) -> bool:
    if not branch:
        return False
    try:
        git(repo, "branch", "-D", branch)
    except RuntimeError:
        return False
    return True


def _cleanup_search_branches(repo: Path, round_reports: list[dict]) -> int:
    """Remove failed search branches after later rounds no longer need them."""
    removed = 0
    if not round_reports:
        return removed

    for report in round_reports[:-1]:
        for row in report.get("candidates", []):
            removed += int(_delete_branch(repo, row.get("branch")))
        removed += int(_delete_branch(repo, report.get("ready_branch")))

    final = round_reports[-1]
    final_status = final.get("status")
    for row in final.get("candidates", []):
        keep = final_status == "MULTIPLE_SURVIVORS" and row.get("disposition") == "SURVIVED"
        if not keep:
            removed += int(_delete_branch(repo, row.get("branch")))
    return removed


def run_swarm(
    repo: Path,
    issue_or_prompt: str,
    *,
    agents: int,
    rounds: int,
    models: list[str],
    budget: float | None,
    open_pr: bool,
    config_path: Path,
) -> dict:
    """Run cooperative search rounds while leaving admission to run_tournament."""
    repo = root(repo.resolve())
    if agents < 1:
        raise ValueError("--agents must be >= 1")
    if rounds < 1:
        raise ValueError("--rounds must be >= 1")
    if budget is not None and budget < 0:
        raise ValueError("--budget must be >= 0")

    swarm_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    swarm_dir = repo / ".airlock" / "swarms" / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=False)
    board: list[dict] = []
    round_reports: list[dict] = []
    round_budget = None if budget is None else budget / rounds

    for round_number in range(1, rounds + 1):
        coordination = {
            "schema": "airlock.swarm.coordination.v1",
            "swarm_id": swarm_id,
            "round": round_number,
            "rounds": rounds,
            "roles": list(DEFAULT_ROLES),
            "blackboard": render_blackboard(board),
        }
        report = run_tournament(
            repo,
            issue_or_prompt,
            agents=agents,
            models=models,
            budget=round_budget,
            open_pr=open_pr and round_number == rounds,
            config_path=config_path,
            coordination=coordination,
        )
        round_reports.append(report)
        board = merge_entries(board, collect_round_entries(report, round_number))
        write_json(
            swarm_dir / "blackboard.json",
            {
                "schema": "airlock.blackboard.v1",
                "swarm_id": swarm_id,
                "entries": board,
            },
        )
        if report.get("status") == "BASELINE_NOT_GREEN":
            break

    removed = _cleanup_search_branches(repo, round_reports)
    final = round_reports[-1] if round_reports else {"status": "NO_RUN"}
    finding_kinds: dict[str, int] = {}
    for row in board:
        if row.get("source") != "agent_finding":
            continue
        kind = row.get("finding", {}).get("kind")
        if kind:
            finding_kinds[kind] = finding_kinds.get(kind, 0) + 1
    agent_findings = sum(finding_kinds.values())
    attempts = sum(int(row.get("requested_agents", 0) or 0) for row in round_reports)
    candidate_rows = [row for report in round_reports for row in report.get("candidates", [])]
    generated_patches = sum(1 for row in candidate_rows if row.get("reason") != "NO_PATCH")
    blocked = sum(1 for row in candidate_rows if row.get("disposition") == "BLOCKED")
    needs_evidence = sum(1 for row in candidate_rows if row.get("disposition") == "NEEDS_EVIDENCE")
    survived_any_round = sum(1 for row in candidate_rows if row.get("disposition") == "SURVIVED")
    cost = _aggregate_cost(round_reports)

    report = {
        "schema": "airlock.swarm.v1",
        "swarm_id": swarm_id,
        "status": final.get("status"),
        "requested_agents_per_round": agents,
        "requested_rounds": rounds,
        "completed_rounds": len(round_reports),
        "attempts": attempts,
        "models": models,
        "budget_usd": budget,
        "round_budget_usd": round_budget,
        "roles": list(DEFAULT_ROLES),
        "shared_findings": agent_findings,
        "finding_kinds": finding_kinds,
        "generated_patches": generated_patches,
        "blocked_attempts": blocked,
        "needs_evidence_attempts": needs_evidence,
        "survived_attempts_across_rounds": survived_any_round,
        "blackboard_entries": len(board),
        "search_branches_removed": removed,
        "round_run_ids": [row.get("run_id") for row in round_reports],
        "final_run_id": final.get("run_id"),
        "final_survivor_count": final.get("survivor_count", 0),
        "ready_candidate_id": final.get("ready_candidate_id"),
        "ready_branch": final.get("ready_branch"),
        "verification_file": final.get("verification_file"),
        "pull_request": final.get("pull_request"),
        "cost": cost,
        "blackboard_file": str((swarm_dir / "blackboard.json").relative_to(repo)),
        "what_this_run_means": (
            "Agents may share bounded search notes across rounds, but those notes never alter Airlock's protected paths, "
            "verification commands, sufficiency rules, or admission decisions. Zero survivors remains a valid result."
        ),
    }
    write_json(swarm_dir / "swarm.json", report)

    print("\nAirlock swarm summary")
    print(f"Attempts: {attempts}")
    print(f"Rounds completed: {len(round_reports)}")
    print(f"Shared findings: {agent_findings}")
    if finding_kinds:
        print("Findings: " + ", ".join(f"{key}={finding_kinds[key]}" for key in sorted(finding_kinds)))
    print(f"Generated patches: {generated_patches}")
    print(f"Blocked attempts: {blocked}")
    print(f"Needs evidence: {needs_evidence}")
    print(f"Survived across rounds: {survived_any_round}")
    print(f"Final survivors: {report['final_survivor_count']}")
    print(f"Failed search branches removed: {removed}")
    if report.get("ready_branch"):
        print(f"Ready for review: {report['ready_branch']}")
    else:
        print("Ready for review: 0")
    if cost["complete"]:
        print(f"Reported spend: ${cost['reported_cost_usd_total']}")
    else:
        print(
            f"Known reported spend: ${cost['reported_cost_usd_total']} "
            f"({cost['unknown_candidates']} attempt(s) unknown)"
        )
    print(f"Swarm report: {(swarm_dir / 'swarm.json').relative_to(repo)}")
    return report
