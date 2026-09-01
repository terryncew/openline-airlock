from __future__ import annotations

from decimal import Decimal
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from airlock.cli import _build_improve_parser
from airlock.gitops import add_worktree, commit_all, git, head, remove_worktree
from airlock.improvement import (
    ObjectiveError,
    _conservative_gain,
    _evaluator_fingerprint,
    _objective_path,
    evaluate_survivor,
    load_objective,
    measure_commit,
    run_improvement_loop,
    select_unique_winner,
    verify_improvement_report,
)


PYTHON = sys.executable


def sh(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


class ImprovementFixture:
    def __init__(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="airlock-improvement-test-"))
        self.repo = self.temp / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", cwd=self.repo)
        sh("git", "config", "user.name", "Airlock Test", cwd=self.repo)
        sh("git", "config", "user.email", "test@example.invalid", cwd=self.repo)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "value.txt").write_text("0\n")
        objective_dir = self.repo / ".airlock" / "objectives"
        objective_dir.mkdir(parents=True)
        (objective_dir / "measure.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            "print(json.dumps({'value': int(Path('src/value.txt').read_text())}))\n"
        )
        self.objective = self.repo / ".airlock" / "objective.json"
        self.objective.write_text(json.dumps({
            "schema": "airlock.objective.v1",
            "name": "fixture utility",
            "goal": "increase the integer in src/value.txt",
            "measure": {
                "command": [PYTHON, ".airlock/objectives/measure.py"],
                "direction": "maximize",
                "unit": "points",
                "repeats": 1,
                "timeout_seconds": 30,
                "pass_env": [],
            },
            "bounds": {
                "max_generations": 10,
                "max_changed_files": 1,
                "max_changed_lines": 2,
            },
            "selection": {
                "minimum_gain": "1",
                "complexity_penalty_per_changed_line": "0",
                "minimum_score_gap": "0",
            },
        }, indent=2) + "\n")
        (self.repo / ".airlock" / "config.json").write_text(json.dumps({
            "schema": "airlock.config.v1",
            "parallelism": 1,
            "protected_paths": [".airlock/**", "tests/**"],
            "verification": {
                "static_commands": [],
                "test_commands": [[PYTHON, "-c", "raise SystemExit(0)"]],
                "target_commands": [[PYTHON, "-c", "raise SystemExit(0)"]],
                "timeout_seconds": 30,
                "coverage_mode": "changed-module-reference",
            },
            "providers": {"fake": {"command": [PYTHON, "-c", "pass"], "pass_env": []}},
            "init_baseline": {"green": True},
        }, indent=2) + "\n")
        (self.repo / ".gitignore").write_text(
            ".airlock/improvements/\n.airlock/records/\n.airlock/runs/\n"
            ".airlock/verification.key\n.airlock/index.json\n"
        )
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "base", cwd=self.repo)
        self.base = head(self.repo)
        self.generation = 0

    def close(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def fake_tournament(self, repo: Path, prompt: str, **kwargs: object) -> dict:
        self.generation += 1
        base = head(repo)
        branch = f"airlock/fake/{self.generation}"
        worktree = self.temp / f"candidate-{self.generation}"
        add_worktree(repo, worktree, branch=branch, commit=base)
        try:
            current = int((worktree / "src" / "value.txt").read_text())
            (worktree / "src" / "value.txt").write_text(f"{current + 1}\n")
            commit = commit_all(worktree, f"improvement {self.generation}")
        finally:
            remove_worktree(repo, worktree)
        return {
            "schema": "airlock.run.v1",
            "run_id": f"fake-{self.generation}",
            "status": "READY",
            "requested_agents": kwargs["agents"],
            "survivor_count": 1,
            "cost": {
                "reported_cost_usd_total": "0.10",
                "known_candidates": 1,
                "unknown_candidates": 0,
                "complete": True,
            },
            "candidates": [{
                "candidate_id": "candidate-01",
                "branch": branch,
                "commit": commit,
                "changed_paths": ["src/value.txt"],
                "disposition": "SURVIVED",
                "reason": "ALL_CONFIGURED_CHECKS_PASSED",
                "agent_report": {"reported_cost_usd": "0.10"},
            }],
        }


class ObjectiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = ImprovementFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_objective_is_operator_owned_and_validated(self) -> None:
        objective = load_objective(self.fx.objective)
        self.assertEqual(objective["measure"]["direction"], "maximize")
        path, relative = _objective_path(self.fx.repo, ".airlock/objective.json")
        self.assertEqual(path, self.fx.objective)
        self.assertEqual(relative, ".airlock/objective.json")
        with self.assertRaisesRegex(ObjectiveError, "under .airlock"):
            _objective_path(self.fx.repo, "objective.json")

    def test_cli_defaults_are_bounded_by_the_objective(self) -> None:
        args = _build_improve_parser().parse_args([])
        self.assertEqual(args.objective, ".airlock/objective.json")
        self.assertEqual(args.agents, 4)
        self.assertIsNone(args.generations)
        self.assertIsNone(args.budget)

    def test_repo_owned_evaluator_file_must_be_protected(self) -> None:
        exposed = self.fx.repo / "measure.py"
        exposed.write_text("print('{\"value\": 0}')\n")
        objective = load_objective(self.fx.objective)
        objective["measure"]["command"] = [PYTHON, "measure.py"]
        with self.assertRaisesRegex(ObjectiveError, "evaluator path is not protected"):
            _evaluator_fingerprint(
                self.fx.repo,
                objective,
                ".airlock/objective.json",
                [".airlock/**"],
            )

    def test_measurement_repeats_are_bound_and_side_effects_fail_closed(self) -> None:
        objective = load_objective(self.fx.objective)
        measured = measure_commit(self.fx.repo, self.fx.base, objective)
        self.assertEqual(measured["status"], "MEASURED")
        self.assertEqual(measured["median"], "0")

        mutator = self.fx.repo / ".airlock" / "objectives" / "mutate.py"
        mutator.write_text(
            "import json\n"
            "from pathlib import Path\n"
            "Path('src/value.txt').write_text('99\\n')\n"
            "print(json.dumps({'value': 99}))\n"
        )
        sh("git", "add", str(mutator.relative_to(self.fx.repo)), cwd=self.fx.repo)
        sh("git", "commit", "-qm", "add mutating metric", cwd=self.fx.repo)
        commit = head(self.fx.repo)
        objective["measure"]["command"] = [PYTHON, ".airlock/objectives/mutate.py"]
        rejected = measure_commit(self.fx.repo, commit, objective)
        self.assertEqual(rejected["status"], "ERROR")
        self.assertEqual(rejected["reason"], "MEASUREMENT_SIDE_EFFECT")

    def test_conservative_gain_requires_separation_from_measurement_noise(self) -> None:
        baseline = {"minimum": "10", "maximum": "12"}
        overlap = {"minimum": "12", "maximum": "14"}
        separated = {"minimum": "13", "maximum": "15"}
        self.assertEqual(_conservative_gain(baseline, overlap, "maximize"), Decimal("0"))
        self.assertEqual(_conservative_gain(baseline, separated, "maximize"), Decimal("1"))

    def test_ambiguous_scores_stop_instead_of_inventing_a_winner(self) -> None:
        candidates = [
            {
                "candidate_id": "one",
                "disposition": "ELIGIBLE",
                "net_gain_score": "2",
                "conservative_gain": "2",
                "diff": {"changed_lines": 1},
                "reported_cost_usd": "0.01",
            },
            {
                "candidate_id": "two",
                "disposition": "ELIGIBLE",
                "net_gain_score": "2",
                "conservative_gain": "2",
                "diff": {"changed_lines": 1},
                "reported_cost_usd": "99.00",
            },
        ]
        selected = select_unique_winner(candidates, Decimal("0"))
        self.assertEqual(selected["status"], "AMBIGUOUS")
        self.assertIsNone(selected["winner"])

    def test_candidate_cannot_smuggle_a_changed_objective_through_a_survivor_record(self) -> None:
        branch = "airlock/fake/objective-tamper"
        worktree = self.fx.temp / "tamper"
        add_worktree(self.fx.repo, worktree, branch=branch, commit=self.fx.base)
        try:
            (worktree / ".airlock" / "objective.json").write_text("{}\n")
            commit = commit_all(worktree, "tamper")
        finally:
            remove_worktree(self.fx.repo, worktree)
        objective = load_objective(self.fx.objective)
        baseline = measure_commit(self.fx.repo, self.fx.base, objective)
        result = evaluate_survivor(
            self.fx.repo,
            base=self.fx.base,
            row={
                "candidate_id": "evil",
                "commit": commit,
                "changed_paths": [".airlock/objective.json"],
                "disposition": "SURVIVED",
                "agent_report": {"reported_cost_usd": "0.01"},
            },
            baseline=baseline,
            objective=objective,
            protected_paths=[".airlock/**"],
            objective_relative_path=".airlock/objective.json",
        )
        self.assertEqual(result["disposition"], "INELIGIBLE")
        self.assertEqual(result["reason"], "PROTECTED_FILES_CHANGED")


class ImprovementLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = ImprovementFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_ten_generations_compound_off_main_and_form_a_verifiable_chain(self) -> None:
        report = run_improvement_loop(
            self.fx.repo,
            objective_path=self.fx.objective,
            generations=10,
            agents=1,
            models=["fake"],
            budget=1.00,
            tournament_runner=self.fx.fake_tournament,
        )
        self.assertEqual(report["status"], "COMPLETED_LIMIT")
        self.assertEqual(report["accepted_generations"], 10)
        self.assertEqual(report["attempted_generations"], 10)
        self.assertEqual(report["final_measurement"]["median"], "10")
        self.assertEqual(head(self.fx.repo), self.fx.base)
        branch_value = sh("git", "show", f"{report['improvement_branch']}:src/value.txt", cwd=self.fx.repo)
        self.assertEqual(branch_value, "10")
        verified = verify_improvement_report(
            self.fx.repo / report["report_file"],
            self.fx.repo / ".airlock" / "verification.key",
        )
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["accepted_generations"], 10)

    def test_generation_limit_cannot_exceed_operator_contract(self) -> None:
        with self.assertRaisesRegex(ObjectiveError, "objective limit"):
            run_improvement_loop(
                self.fx.repo,
                objective_path=self.fx.objective,
                generations=11,
                agents=1,
                models=["fake"],
                budget=None,
                tournament_runner=self.fx.fake_tournament,
            )

    def test_unmeasurable_base_stops_before_agent_spend_and_still_leaves_a_valid_receipt(self) -> None:
        def failed_measurement(argv, cwd, **kwargs):
            return {
                "argv": argv,
                "exit_code": 1,
                "stdout": "",
                "stderr": "metric unavailable",
                "duration_seconds": 0.01,
                "timed_out": False,
            }

        def should_not_run(*args, **kwargs):
            raise AssertionError("agents must not run when the base cannot be measured")

        report = run_improvement_loop(
            self.fx.repo,
            objective_path=self.fx.objective,
            generations=1,
            agents=1,
            models=["fake"],
            budget=None,
            tournament_runner=should_not_run,
            command_runner=failed_measurement,
        )
        self.assertEqual(report["status"], "STOPPED_BASELINE_MEASUREMENT")
        self.assertEqual(report["accepted_generations"], 0)
        verified = verify_improvement_report(
            self.fx.repo / report["report_file"],
            self.fx.repo / ".airlock" / "verification.key",
        )
        self.assertTrue(verified["valid"])

    def test_uncommitted_objective_change_cannot_redefine_better_at_run_time(self) -> None:
        value = json.loads(self.fx.objective.read_text())
        value["selection"]["minimum_gain"] = "0"
        self.fx.objective.write_text(json.dumps(value, indent=2) + "\n")
        with (
            mock.patch("airlock.improvement.ensure_clean"),
            self.assertRaisesRegex(ObjectiveError, "committed unchanged"),
        ):
            run_improvement_loop(
                self.fx.repo,
                objective_path=self.fx.objective,
                generations=1,
                agents=1,
                models=["fake"],
                budget=None,
                tournament_runner=self.fx.fake_tournament,
            )

    def test_tampered_generation_breaks_report_verification(self) -> None:
        report = run_improvement_loop(
            self.fx.repo,
            objective_path=self.fx.objective,
            generations=1,
            agents=1,
            models=["fake"],
            budget=None,
            tournament_runner=self.fx.fake_tournament,
        )
        report_path = self.fx.repo / report["report_file"]
        generation_path = report_path.parent / "generation-01.json"
        value = json.loads(generation_path.read_text())
        value["payload"]["decision"] = "NO_IMPROVEMENT"
        generation_path.write_text(json.dumps(value))
        verified = verify_improvement_report(
            report_path,
            self.fx.repo / ".airlock" / "verification.key",
        )
        self.assertFalse(verified["valid"])
        self.assertEqual(verified["reason"], "GENERATION_HASH")


if __name__ == "__main__":
    unittest.main()
