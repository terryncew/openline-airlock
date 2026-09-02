#!/usr/bin/env python3
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from airlock.runner import run_tournament

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONFIG = ROOT / ".airlock" / "self-001" / "config.json"
REGISTRY = ROOT / ".airlock" / "self-001" / "scope_registry.json"
EVALUATOR = ROOT / ".airlock" / "self-001" / "evaluator.py"
PREREG = ROOT / ".airlock" / "self-001" / "preregistration.json"

AUTONOMOUS_PROMPT = "Improve this repository. Find the highest-value small, reversible change you can justify."
DIRECTED_PROMPT = (
    "Improve experiments/airlock-self-001/office_ops.py. "
    "Reduce unnecessary work in first_over_budget without changing its return value for any input. "
    "Keep the change small and reversible."
)


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} failed")
    return cp.stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(repo: Path, base: str, commit: str) -> dict:
    cp = subprocess.run(
        [sys.executable, str(EVALUATOR), "--repo", str(repo), "--base", base, "--candidate", commit],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        data = json.loads(cp.stdout)
    except Exception:
        return {
            "candidate_commit": commit,
            "disposition": "REJECT",
            "reason": "EVALUATOR_ERROR",
            "stderr_tail": cp.stderr[-1000:],
            "stdout_tail": cp.stdout[-1000:],
        }
    data["evaluator_exit_code"] = cp.returncode
    return data


def cost_summary(tournament: dict) -> dict:
    total = Decimal("0")
    known = 0
    unknown = 0
    for row in tournament.get("candidates", []):
        raw = (row.get("agent_report") or {}).get("reported_cost_usd")
        if raw is None:
            unknown += 1
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            unknown += 1
            continue
        if value < 0:
            unknown += 1
            continue
        total += value
        known += 1
    return {
        "provider_reported_cost_usd": format(total, "f"),
        "known_candidates": known,
        "unknown_candidates": unknown,
        "complete": unknown == 0,
    }


def select(rows: list[dict], minimum_gap: float) -> dict:
    eligible = [r for r in rows if r.get("disposition") == "ACCEPT"]
    if not eligible:
        return {"status": "NO_WINNER", "winner": None, "eligible": 0}
    ordered = sorted(
        eligible,
        key=lambda r: (float(r["net_gain_score"]), -int(r["diff"]["changed_lines"]), r["candidate_commit"]),
        reverse=True,
    )
    if len(ordered) == 1:
        return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": 1}
    gap = float(ordered[0]["net_gain_score"]) - float(ordered[1]["net_gain_score"])
    if gap <= minimum_gap:
        return {"status": "AMBIGUOUS", "winner": None, "eligible": len(ordered), "score_gap": gap}
    return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": len(ordered), "score_gap": gap}


def infrastructure_status(tournament: dict) -> dict:
    status = tournament.get("status")
    if status == "BASELINE_NOT_GREEN":
        return {
            "valid": False,
            "reason": "BASELINE_NOT_GREEN",
            "baseline": tournament.get("baseline"),
        }

    candidates = tournament.get("candidates") or []
    if not candidates:
        return {
            "valid": False,
            "reason": "NO_CANDIDATE_RECORDS",
            "baseline": tournament.get("baseline"),
        }

    completed = [
        row for row in candidates
        if (row.get("agent_execution") or {}).get("exit_code") == 0
        and not (row.get("agent_execution") or {}).get("timed_out")
    ]
    if not completed:
        return {
            "valid": False,
            "reason": "WORKER_EXECUTION_FAILED",
            "baseline": tournament.get("baseline"),
            "worker_executions": [
                {
                    "candidate_id": row.get("candidate_id"),
                    "agent_execution": row.get("agent_execution"),
                    "agent_report": row.get("agent_report", {}),
                }
                for row in candidates
            ],
        }

    return {
        "valid": True,
        "reason": "WORKER_EXECUTION_COMPLETED",
        "baseline": tournament.get("baseline"),
        "completed_worker_executions": len(completed),
    }


def run_arm(repo: Path, base: str, *, name: str, prompt: str, agents: int, model: str, budget: float | None) -> dict:
    tournament = run_tournament(
        repo,
        prompt,
        agents=agents,
        models=[model],
        budget=budget,
        open_pr=False,
        config_path=CONFIG,
    )
    evaluated = []
    seen = set()
    for row in tournament.get("candidates", []):
        commit = row.get("commit")
        if row.get("disposition") != "SURVIVED" or not isinstance(commit, str) or commit == base:
            evaluated.append({
                "candidate_id": row.get("candidate_id"),
                "candidate_commit": commit,
                "disposition": "REJECT",
                "reason": f"STRUCTURAL_{row.get('reason', row.get('disposition', 'UNKNOWN'))}",
                "agent_execution": row.get("agent_execution"),
                "agent_report": row.get("agent_report", {}),
            })
            continue
        tree = git(repo, "rev-parse", f"{commit}^{{tree}}")
        if tree in seen:
            evaluated.append({
                "candidate_id": row.get("candidate_id"),
                "candidate_commit": commit,
                "disposition": "REJECT",
                "reason": "DUPLICATE_TREE",
            })
            continue
        seen.add(tree)
        score = evaluate(repo, base, commit)
        score["candidate_id"] = row.get("candidate_id")
        score["model"] = row.get("model")
        score["agent_report"] = row.get("agent_report", {})
        evaluated.append(score)

    registry = json.loads(REGISTRY.read_text())
    selection = select(evaluated, float(registry["minimum_score_gap"]))
    return {
        "arm": name,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "tournament_status": tournament.get("status"),
        "tournament_run_id": tournament.get("run_id"),
        "infrastructure": infrastructure_status(tournament),
        "evaluated_candidates": evaluated,
        "selection": selection,
        "cost": cost_summary(tournament),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--agents", type=int, default=2)
    parser.add_argument("--model", default="hermes")
    parser.add_argument("--budget", type=float)
    parser.add_argument("--output")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if args.agents < 1:
        raise SystemExit("--agents must be >= 1")
    if git(repo, "status", "--porcelain"):
        raise SystemExit("SELF-001 requires a clean repository")

    base = git(repo, "rev-parse", "HEAD")
    prereg = json.loads(PREREG.read_text())
    frozen = {
        "base_commit": base,
        "config_sha256": sha256(CONFIG),
        "scope_registry_sha256": sha256(REGISTRY),
        "evaluator_sha256": sha256(EVALUATOR),
        "preregistration_sha256": sha256(PREREG),
    }

    # Freeze the common base before either arm contacts a worker.
    per_arm_budget = None if args.budget is None else args.budget / 2
    autonomous = run_arm(
        repo, base,
        name="AUTONOMOUS",
        prompt=AUTONOMOUS_PROMPT,
        agents=args.agents,
        model=args.model,
        budget=per_arm_budget,
    )
    directed = run_arm(
        repo, base,
        name="MAINTAINER_DIRECTED",
        prompt=DIRECTED_PROMPT,
        agents=args.agents,
        model=args.model,
        budget=per_arm_budget,
    )

    infrastructure_valid = bool(
        autonomous["infrastructure"]["valid"]
        and directed["infrastructure"]["valid"]
    )
    auto_yes = autonomous["selection"]["status"] == "UNIQUE_WINNER"
    directed_yes = directed["selection"]["status"] == "UNIQUE_WINNER"

    if not infrastructure_valid:
        conclusion = "EXPERIMENT_NOT_RUN"
        earned = False
    elif directed_yes and auto_yes:
        conclusion = "AUTONOMOUS_IMPROVEMENT_EARNED"
        earned = True
    elif directed_yes and not auto_yes:
        conclusion = "SEARCH_GAP"
        earned = False
    elif not directed_yes:
        conclusion = "POSITIVE_CONTROL_NOT_EARNED"
        earned = False
    else:
        conclusion = "INCONCLUSIVE"
        earned = False

    result = {
        "schema": "airlock.self001.result.v2",
        "experiment": "AIRLOCK-SELF-001",
        "frozen": frozen,
        "claim_under_test": prereg["claim_under_test"],
        "autonomous": autonomous,
        "maintainer_directed": directed,
        "valid_experiment": infrastructure_valid,
        "conclusion": conclusion,
        "earned": earned,
        "interpretation": {
            "EXPERIMENT_NOT_RUN": "The repository baseline or worker runtime failed before both preregistered arms completed. This is an infrastructure result and says nothing about autonomous search or the positive control.",
            "AUTONOMOUS_IMPROVEMENT_EARNED": "The broad worker found and earned a scoped, regression-protected improvement under the same frozen gate as the directed positive control.",
            "SEARCH_GAP": "The gate was reachable for a maintainer-directed worker, but the broad worker did not find an admissible improvement. Zero survivors is therefore evidence about search/selection, not an impossible gate.",
            "POSITIVE_CONTROL_NOT_EARNED": "The directed arm failed to earn a yes, so an autonomous zero cannot be interpreted as a worker/search failure.",
            "INCONCLUSIVE": "The preregistered comparison did not resolve.",
        }[conclusion],
        "claim_boundary": prereg["claim_boundary"],
    }

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = Path(args.output) if args.output else repo / ".airlock" / "self-001-results" / run_id / "report.json"
    if not output.is_absolute():
        output = repo / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.parent / "report.sha256").write_text(digest + "  report.json\n")

    print(json.dumps({
        "conclusion": conclusion,
        "earned": earned,
        "report": str(output),
        "report_sha256": digest,
        "autonomous_selection": autonomous["selection"]["status"],
        "directed_selection": directed["selection"]["status"],
    }, indent=2, sort_keys=True))
    if not infrastructure_valid:
        return 2
    return 0 if earned else 3


if __name__ == "__main__":
    raise SystemExit(main())
