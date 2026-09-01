#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from airlock.gitops import head
from airlock.improvement import run_improvement_loop
from airlock.nightshift import run_nightshift

PYTHON = sys.executable


def sh(*args: str, cwd: Path) -> str:
    cp = subprocess.run(
        list(args), cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return cp.stdout.strip()


def make_fixture() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="airlock-hermes-live-001-measure-"))
    repo = tmp / "repo"
    repo.mkdir()
    sh("git", "init", "-q", str(repo), cwd=tmp)
    sh("git", "config", "user.name", "Airlock Measure", cwd=repo)
    sh("git", "config", "user.email", "measure@example.invalid", cwd=repo)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / ".airlock" / "checks").mkdir(parents=True)
    (repo / "src" / "value.py").write_text("VALUE = 0\n")
    (repo / "tests" / "check.py").write_text(
        "from src.value import VALUE\n"
        "raise SystemExit(0 if isinstance(VALUE, int) and VALUE >= 0 else 1)\n"
    )
    measure = repo / ".airlock" / "checks" / "measure_value.py"
    measure.write_text(
        "import json\n"
        "from src.value import VALUE\n"
        "print(json.dumps({'value': VALUE}))\n"
    )
    objective = {
        "schema": "airlock.objective.v1",
        "name": "fixture value",
        "goal": "Increase the fixture value.",
        "measure": {
            "command": [PYTHON, ".airlock/checks/measure_value.py"],
            "direction": "maximize",
            "unit": "points",
            "repeats": 1,
            "timeout_seconds": 30,
            "pass_env": [],
            "protected_evaluator_paths": [".airlock/checks/measure_value.py"],
        },
        "bounds": {"max_generations": 2, "max_changed_files": 2, "max_changed_lines": 20},
        "selection": {
            "minimum_gain": "1",
            "complexity_penalty_per_changed_line": "0",
            "minimum_score_gap": "0",
        },
    }
    (repo / ".airlock" / "objective.json").write_text(json.dumps(objective, indent=2) + "\n")
    config = {
        "schema": "airlock.config.v1",
        "parallelism": 1,
        "protected_paths": ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"],
        "verification": {
            "static_commands": [],
            "test_commands": [[PYTHON, "tests/check.py"]],
            "target_commands": [[PYTHON, "tests/check.py"]],
            "timeout_seconds": 30,
            "coverage_mode": "changed-module-reference",
        },
        "providers": {
            "hermes": {
                "command": ["hermes", "-z", "{prompt}"],
                "pass_env": ["HERMES_HOME"],
                "timeout_seconds": 30,
            }
        },
        "init_baseline": {"green": True},
    }
    (repo / ".airlock" / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (repo / ".gitignore").write_text(
        ".airlock/runs/\n.airlock/records/\n.airlock/improvements/\n"
        ".airlock/verification.key\n.airlock/index.json\n"
    )
    sh("git", "add", ".", cwd=repo)
    sh("git", "commit", "-qm", "base", cwd=repo)
    return tmp, repo


def no_patch_tournament(repo: Path, *_args, **kwargs) -> dict:
    base = head(repo)
    model = (kwargs.get("models") or ["hermes"])[0]
    return {
        "run_id": "measure-no-patch",
        "status": "NO_PATCH_READY",
        "requested_agents": 1,
        "models": [model],
        "survivor_count": 0,
        "cost": {"complete": False, "unknown_candidates": 1, "reported_cost_usd_total": "0"},
        "elapsed_seconds": 0.01,
        "candidates": [{
            "candidate_id": "candidate-01",
            "model": model,
            "branch": "measure/no-patch",
            "commit": base,
            "changed_paths": [],
            "disposition": "BLOCKED",
            "reason": "NO_PATCH",
            "agent_execution": {"exit_code": 0, "timed_out": False},
            "agent_report": {},
        }],
    }


def sequence_tournament():
    calls = {"count": 0}

    def runner(repo: Path, *_args, **kwargs) -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            return no_patch_tournament(repo, *_args, **kwargs)
        base = head(repo)
        model = (kwargs.get("models") or ["hermes"])[0]
        (repo / "src" / "value.py").write_text("VALUE = 1\n")
        sh("git", "add", "src/value.py", cwd=repo)
        sh("git", "commit", "-qm", "candidate", cwd=repo)
        candidate = head(repo)
        return {
            "run_id": "measure-candidate",
            "status": "READY",
            "requested_agents": 1,
            "models": [model],
            "survivor_count": 1,
            "cost": {"complete": False, "unknown_candidates": 1, "reported_cost_usd_total": "0"},
            "elapsed_seconds": 0.01,
            "candidates": [{
                "candidate_id": "candidate-01",
                "model": model,
                "branch": "measure/candidate",
                "commit": candidate,
                "changed_paths": ["src/value.py"],
                "disposition": "SURVIVED",
                "reason": "ALL_CONFIGURED_CHECKS_PASSED",
                "agent_execution": {"exit_code": 0, "timed_out": False},
                "agent_report": {},
            }],
        }

    return runner


def main() -> int:
    tmp, repo = make_fixture()
    try:
        starting = head(repo)
        night = run_nightshift(
            repo,
            objective_path=".airlock/objective.json",
            generations=2,
            agents=1,
            profiles=[],
            budget=None,
            tournament_runner=sequence_tournament(),
        )
        night_ok = (
            night.get("attempted_generations") == 2
            and night.get("accepted_generations") == 1
            and len(night.get("generations", [])) == 2
            and night["generations"][0].get("base_commit") == starting
            and night["generations"][0].get("promoted_commit") is None
            and night["generations"][1].get("base_commit") == starting
            and night["generations"][1].get("promoted_commit") is not None
            and head(repo) == starting
        )

        improve = run_improvement_loop(
            repo,
            objective_path=".airlock/objective.json",
            generations=2,
            agents=1,
            models=["hermes"],
            budget=None,
            tournament_runner=no_patch_tournament,
        )
        improve_ok = (
            improve.get("attempted_generations") == 1
            and improve.get("accepted_generations") == 0
            and head(repo) == starting
        )
        value = 1 if night_ok and improve_ok else 0
        print(json.dumps({
            "value": value,
            "nightshift_retry_after_zero_standing": night_ok,
            "ordinary_improve_still_stops": improve_ok,
        }, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
