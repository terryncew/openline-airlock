from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from typing import Callable

from .config import load as load_config
from .gitops import (
    add_worktree,
    changed_paths,
    ensure_clean,
    git,
    head,
    remove_worktree,
    sanitize_branch,
)
from .runner import run_tournament
from .util import (
    canonical_json_bytes,
    compact_result,
    matches_any,
    run,
    scrub_agent_env,
    sha256_bytes,
    sha256_file,
    worktree_env,
    write_json,
)
from .verification import ensure_key, sign, verify_signature


OBJECTIVE_SCHEMA = "airlock.objective.v1"
GENERATION_SCHEMA = "airlock.improvement.generation.v1"
REPORT_SCHEMA = "airlock.improvement.v1"


class ObjectiveError(ValueError):
    pass


def _decimal(value: object, name: str, *, minimum: Decimal | None = None) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ObjectiveError(f"{name} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ObjectiveError(f"{name} must be a finite decimal")
    if minimum is not None and parsed < minimum:
        raise ObjectiveError(f"{name} must be >= {minimum}")
    return parsed


def _integer(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObjectiveError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ObjectiveError(f"{name} must be between {minimum} and {maximum}")
    return value


def _command(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(part, str) and part for part in value):
        raise ObjectiveError(f"{name} must be a non-empty argv array")
    return list(value)


def load_objective(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise ObjectiveError(f"could not read objective: {path}") from exc
    if not isinstance(value, dict) or value.get("schema") != OBJECTIVE_SCHEMA:
        raise ObjectiveError(f"objective schema must be {OBJECTIVE_SCHEMA}")
    for name in ("name", "goal"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ObjectiveError(f"objective {name} must be a non-empty string")

    measure = value.get("measure")
    if not isinstance(measure, dict):
        raise ObjectiveError("objective measure must be an object")
    _command(measure.get("command"), "measure.command")
    if measure.get("direction") not in {"maximize", "minimize"}:
        raise ObjectiveError("measure.direction must be maximize or minimize")
    _integer(measure.get("repeats", 3), "measure.repeats", minimum=1, maximum=21)
    _integer(measure.get("timeout_seconds", 300), "measure.timeout_seconds", minimum=1, maximum=7200)
    pass_env = measure.get("pass_env", [])
    if not isinstance(pass_env, list) or not all(isinstance(item, str) and item for item in pass_env):
        raise ObjectiveError("measure.pass_env must be an array of environment-variable names")
    evaluator_paths = measure.get("protected_evaluator_paths", [])
    if not isinstance(evaluator_paths, list) or not all(
        isinstance(item, str) and item for item in evaluator_paths
    ):
        raise ObjectiveError("measure.protected_evaluator_paths must be an array of repository paths")

    bounds = value.get("bounds")
    if not isinstance(bounds, dict):
        raise ObjectiveError("objective bounds must be an object")
    _integer(bounds.get("max_generations", 10), "bounds.max_generations", minimum=1, maximum=50)
    _integer(bounds.get("max_changed_files", 5), "bounds.max_changed_files", minimum=1, maximum=1000)
    _integer(bounds.get("max_changed_lines", 200), "bounds.max_changed_lines", minimum=1, maximum=1_000_000)
    selection = value.get("selection")
    if not isinstance(selection, dict):
        raise ObjectiveError("objective selection must be an object")
    _decimal(selection.get("minimum_gain", "0"), "selection.minimum_gain", minimum=Decimal("0"))
    _decimal(
        selection.get("complexity_penalty_per_changed_line", "0"),
        "selection.complexity_penalty_per_changed_line",
        minimum=Decimal("0"),
    )
    _decimal(selection.get("minimum_score_gap", "0"), "selection.minimum_score_gap", minimum=Decimal("0"))
    return value


def _objective_path(repo: Path, value: str | Path) -> tuple[Path, str]:
    path = Path(value)
    path = path if path.is_absolute() else repo / path
    path = path.resolve()
    try:
        relative = path.relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise ObjectiveError("objective must live inside the repository") from exc
    if not relative.startswith(".airlock/"):
        raise ObjectiveError("objective must live under .airlock/ so agents cannot own it")
    return path, relative


def _evaluator_fingerprint(
    repo: Path,
    objective: dict,
    objective_relative_path: str,
    protected_paths: list[str],
) -> dict:
    candidates = [objective_relative_path, *objective["measure"].get("protected_evaluator_paths", [])]
    for part in objective["measure"]["command"]:
        if part.startswith("-"):
            continue
        possible = (repo / part).resolve()
        try:
            relative = possible.relative_to(repo.resolve()).as_posix()
        except ValueError:
            continue
        if possible.is_file():
            candidates.append(relative)

    files = []
    for relative in sorted(set(candidates)):
        path = (repo / relative).resolve()
        try:
            normalized = path.relative_to(repo.resolve()).as_posix()
        except ValueError as exc:
            raise ObjectiveError(f"evaluator path escapes repository: {relative}") from exc
        if not path.is_file():
            raise ObjectiveError(f"evaluator path does not exist: {normalized}")
        if not matches_any(normalized, protected_paths):
            raise ObjectiveError(f"evaluator path is not protected: {normalized}")
        files.append({"path": normalized, "sha256": sha256_file(path)})
    return {
        "files": files,
        "root_sha256": sha256_bytes(canonical_json_bytes(files)),
    }


def _require_frozen_paths(repo: Path, commit: str, paths: list[str]) -> None:
    for relative in sorted(set(paths)):
        try:
            committed = git(repo, "rev-parse", f"{commit}:{relative}")
            working = git(repo, "hash-object", relative)
        except RuntimeError as exc:
            raise ObjectiveError(f"operator-owned file must be committed before the run: {relative}") from exc
        if committed != working:
            raise ObjectiveError(f"operator-owned file must be committed unchanged before the run: {relative}")


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _parse_metric(stdout: str) -> Decimal:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError("measurement command produced no output")
    try:
        value = json.loads(lines[-1], parse_float=Decimal, parse_int=Decimal)
    except Exception as exc:
        raise ValueError("last measurement line must be JSON") from exc
    if not isinstance(value, dict) or "value" not in value:
        raise ValueError('measurement JSON must contain a numeric "value"')
    measured = _decimal(value["value"], "measurement value")
    return measured


def measure_commit(
    repo: Path,
    commit: str,
    objective: dict,
    *,
    command_runner: Callable[..., dict] = run,
) -> dict:
    """Measure one frozen commit without giving the measurement process release authority."""
    measure = objective["measure"]
    argv = _command(measure["command"], "measure.command")
    repeats = _integer(measure.get("repeats", 3), "measure.repeats", minimum=1, maximum=21)
    timeout = _integer(
        measure.get("timeout_seconds", 300),
        "measure.timeout_seconds",
        minimum=1,
        maximum=7200,
    )
    temp = Path(tempfile.mkdtemp(prefix="airlock-measure-"))
    temp.rmdir()
    add_worktree(repo, temp, commit=commit)
    records: list[dict] = []
    values: list[Decimal] = []
    try:
        before = git(temp, "status", "--porcelain", "--untracked-files=all")
        for index in range(repeats):
            home = Path(tempfile.mkdtemp(prefix="airlock-measure-home-"))
            try:
                env = scrub_agent_env(
                    measure.get("pass_env", []),
                    home=home,
                    extra={
                        "AIRLOCK_MEASUREMENT": "1",
                        "AIRLOCK_RELEASE_AUTHORITY": "ABSENT",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                result = command_runner(argv, temp, env=worktree_env(temp, env), timeout=timeout)
            finally:
                shutil.rmtree(home, ignore_errors=True)
            compact = compact_result(result)
            compact["repeat"] = index + 1
            records.append(compact)
            if result["exit_code"] != 0 or result.get("timed_out"):
                return {
                    "status": "ERROR",
                    "reason": "MEASUREMENT_COMMAND_FAILED",
                    "commit": commit,
                    "command_sha256": sha256_bytes(canonical_json_bytes(argv)),
                    "records": records,
                }
            try:
                values.append(_parse_metric(result["stdout"]))
            except ValueError as exc:
                return {
                    "status": "ERROR",
                    "reason": "INVALID_MEASUREMENT_OUTPUT",
                    "detail": str(exc),
                    "commit": commit,
                    "command_sha256": sha256_bytes(canonical_json_bytes(argv)),
                    "records": records,
                }
        after = git(temp, "status", "--porcelain", "--untracked-files=all")
        if before != after:
            return {
                "status": "ERROR",
                "reason": "MEASUREMENT_SIDE_EFFECT",
                "commit": commit,
                "command_sha256": sha256_bytes(canonical_json_bytes(argv)),
                "records": records,
            }
        return {
            "status": "MEASURED",
            "commit": commit,
            "direction": measure["direction"],
            "unit": str(measure.get("unit") or "utility"),
            "values": [format(value, "f") for value in values],
            "median": format(_median(values), "f"),
            "minimum": format(min(values), "f"),
            "maximum": format(max(values), "f"),
            "command_sha256": sha256_bytes(canonical_json_bytes(argv)),
            "records": records,
        }
    finally:
        remove_worktree(repo, temp)


def _diff_stats(repo: Path, base: str, candidate: str) -> dict:
    output = git(repo, "diff", "--numstat", f"{base}..{candidate}")
    added = 0
    deleted = 0
    binary_files = 0
    rows = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        rows += 1
        before, after, *_ = line.split("\t")
        if before == "-" or after == "-":
            binary_files += 1
            continue
        added += int(before)
        deleted += int(after)
    return {
        "changed_files": rows,
        "lines_added": added,
        "lines_deleted": deleted,
        "changed_lines": added + deleted,
        "binary_files": binary_files,
    }


def _conservative_gain(baseline: dict, candidate: dict, direction: str) -> Decimal:
    if direction == "maximize":
        return Decimal(candidate["minimum"]) - Decimal(baseline["maximum"])
    return Decimal(baseline["minimum"]) - Decimal(candidate["maximum"])


def _candidate_cost(row: dict) -> Decimal | None:
    raw = row.get("agent_report", {}).get("reported_cost_usd")
    if raw is None:
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value >= 0 else None


def _candidate_provenance(row: dict) -> dict:
    """Keep worker identity and bounded execution evidence in the signed generation receipt."""
    model = row.get("model")
    profile = None
    if isinstance(model, str) and model.startswith("hermes@"):
        profile = model.split("@", 1)[1]
    return {
        "model": model,
        "hermes_profile": profile,
        "agent_execution": row.get("agent_execution"),
        "agent_report": row.get("agent_report", {}),
    }


def evaluate_survivor(
    repo: Path,
    *,
    base: str,
    row: dict,
    baseline: dict,
    objective: dict,
    protected_paths: list[str],
    objective_relative_path: str,
    command_runner: Callable[..., dict] = run,
) -> dict:
    candidate_id = str(row.get("candidate_id") or "unknown")
    candidate = row.get("commit")
    result = {
        "candidate_id": candidate_id,
        "commit": candidate,
        "disposition": "INELIGIBLE",
        "reason": "NOT_A_STRUCTURAL_SURVIVOR",
        "reported_cost_usd": None,
        "worker": _candidate_provenance(row),
    }
    if row.get("disposition") != "SURVIVED" or not isinstance(candidate, str):
        return result
    ancestor = run(["git", "merge-base", "--is-ancestor", base, candidate], repo)
    if ancestor["exit_code"] != 0 or candidate == base:
        result["reason"] = "CANDIDATE_NOT_DESCENDED_FROM_BASE"
        return result
    try:
        actual_paths = changed_paths(repo, base, candidate)
    except Exception:
        result["reason"] = "CANDIDATE_COMMIT_UNREADABLE"
        return result
    if actual_paths != row.get("changed_paths"):
        result["reason"] = "CHANGED_PATH_BINDING_MISMATCH"
        return result
    protected_touched = [path for path in actual_paths if matches_any(path, protected_paths)]
    if objective_relative_path in actual_paths or protected_touched:
        result.update({"reason": "PROTECTED_FILES_CHANGED", "protected_touched": protected_touched})
        return result

    stats = _diff_stats(repo, base, candidate)
    result["diff"] = stats
    bounds = objective["bounds"]
    if stats["binary_files"]:
        result["reason"] = "BINARY_CHANGE_OUTSIDE_REVERSIBILITY_MODEL"
        return result
    if stats["changed_files"] > int(bounds["max_changed_files"]):
        result["reason"] = "CHANGED_FILE_LIMIT"
        return result
    if stats["changed_lines"] > int(bounds["max_changed_lines"]):
        result["reason"] = "CHANGED_LINE_LIMIT"
        return result

    cost = _candidate_cost(row)
    result["reported_cost_usd"] = None if cost is None else format(cost, "f")
    measurement = measure_commit(repo, candidate, objective, command_runner=command_runner)
    result["measurement"] = measurement
    if measurement.get("status") != "MEASURED":
        result["reason"] = measurement.get("reason", "MEASUREMENT_FAILED")
        return result
    selection = objective["selection"]
    gain = _conservative_gain(baseline, measurement, objective["measure"]["direction"])
    minimum_gain = Decimal(str(selection["minimum_gain"]))
    result["conservative_gain"] = format(gain, "f")
    if gain < minimum_gain:
        result["reason"] = "MINIMUM_GAIN_NOT_CLEARED"
        return result

    complexity_penalty = Decimal(str(selection["complexity_penalty_per_changed_line"]))
    score = gain - complexity_penalty * stats["changed_lines"]
    result["net_gain_score"] = format(score, "f")
    if score <= 0:
        result["reason"] = "NONPOSITIVE_NET_GAIN"
        return result
    result.update({"disposition": "ELIGIBLE", "reason": "OBJECTIVE_CLEARED"})
    return result


def select_unique_winner(candidates: list[dict], minimum_score_gap: Decimal) -> dict:
    eligible = [row for row in candidates if row.get("disposition") == "ELIGIBLE"]
    if not eligible:
        return {"status": "NO_IMPROVEMENT", "winner": None, "eligible": 0}
    ordered = sorted(
        eligible,
        key=lambda row: (
            Decimal(row["net_gain_score"]),
            Decimal(row["conservative_gain"]),
            -int(row["diff"]["changed_lines"]),
            str(row.get("candidate_id")),
        ),
        reverse=True,
    )
    if len(ordered) == 1:
        return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": 1}
    top = Decimal(ordered[0]["net_gain_score"])
    second = Decimal(ordered[1]["net_gain_score"])
    if top - second <= minimum_score_gap:
        return {
            "status": "AMBIGUOUS",
            "winner": None,
            "eligible": len(ordered),
            "top_score": format(top, "f"),
            "second_score": format(second, "f"),
        }
    return {"status": "UNIQUE_WINNER", "winner": ordered[0], "eligible": len(ordered)}


def _prompt(objective: dict, baseline: dict, generation: int) -> str:
    bounds = objective["bounds"]
    return (
        f"Airlock bounded improvement generation {generation}.\n\n"
        f"Operator-owned objective: {objective['name']}\n"
        f"Goal: {objective['goal']}\n"
        f"Current measured utility: {baseline['median']} {baseline['unit']}\n"
        f"Direction: {objective['measure']['direction']}\n\n"
        "Propose and implement one small, reversible improvement. "
        f"Touch at most {bounds['max_changed_files']} files and {bounds['max_changed_lines']} lines. "
        "Do not edit tests, workflows, Airlock rules, the objective, or evaluator configuration. "
        "Airlock will run repository checks and the operator-owned measurement independently. "
        "You do not decide whether this change is promoted."
    )


def _delete_airlock_branch(repo: Path, branch: object, keep: str) -> None:
    if not isinstance(branch, str) or branch == keep or not branch.startswith("airlock/"):
        return
    try:
        git(repo, "branch", "-D", branch)
    except RuntimeError:
        pass


def _copy_verification(loop_repo: Path, root_repo: Path, report: dict) -> str | None:
    relative = report.get("verification_file")
    if not isinstance(relative, str):
        return None
    source = loop_repo / relative
    if not source.exists():
        return None
    destination = root_repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return sha256_file(destination)


def run_improvement_loop(
    repo: Path,
    *,
    objective_path: str | Path,
    generations: int | None,
    agents: int,
    models: list[str],
    budget: float | None,
    config_path: Path | None = None,
    tournament_runner: Callable[..., dict] = run_tournament,
    command_runner: Callable[..., dict] = run,
    run_context: dict | None = None,
) -> dict:
    """Compound only uniquely evidenced improvements on an isolated Airlock branch."""
    repo = repo.resolve()
    ensure_clean(repo)
    if agents < 1:
        raise ValueError("--agents must be >= 1")
    if budget is not None and (not math.isfinite(budget) or budget < 0):
        raise ValueError("--budget must be a finite value >= 0")

    objective_file, objective_relative = _objective_path(repo, objective_path)
    objective = load_objective(objective_file)
    objective_sha = sha256_file(objective_file)
    config_path = (config_path or repo / ".airlock" / "config.json").resolve()
    config = load_config(config_path)
    start_commit = head(repo)
    try:
        config_relative = config_path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ObjectiveError("config must live inside the repository") from exc
    protected = list(config.get("protected_paths", []))
    if not matches_any(config_relative, protected):
        raise ObjectiveError("Airlock config must be covered by the repository's protected paths")
    if not matches_any(objective_relative, protected):
        raise ObjectiveError("objective path must be covered by the repository's protected paths")
    evaluator_fingerprint = _evaluator_fingerprint(
        repo,
        objective,
        objective_relative,
        protected,
    )
    _require_frozen_paths(
        repo,
        start_commit,
        [config_relative, *[row["path"] for row in evaluator_fingerprint["files"]]],
    )
    config_sha = sha256_file(config_path)

    configured_max = int(objective["bounds"]["max_generations"])
    generation_limit = configured_max if generations is None else generations
    if generation_limit < 1 or generation_limit > configured_max:
        raise ObjectiveError(f"generations must be between 1 and the objective limit ({configured_max})")

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    improvement_branch = sanitize_branch(f"airlock/improve/{run_id}")
    output_dir = repo / ".airlock" / "improvements" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    loop_dir = Path(tempfile.mkdtemp(prefix=f"airlock-improve-{run_id}-"))
    loop_dir.rmdir()
    add_worktree(repo, loop_dir, branch=improvement_branch, commit=start_commit)
    key_path = repo / ".airlock" / "verification.key"
    key = ensure_key(key_path)
    loop_key = loop_dir / ".airlock" / "verification.key"
    loop_key.parent.mkdir(parents=True, exist_ok=True)
    loop_key.write_bytes(key)
    try:
        os.chmod(loop_key, 0o600)
    except OSError:
        pass

    accepted = 0
    generation_records: list[dict] = []
    worker_usage: list[dict] = []
    previous_receipt_sha: str | None = None
    status = "COMPLETED_LIMIT"
    per_generation_budget = None if budget is None else budget / generation_limit

    try:
        for number in range(1, generation_limit + 1):
            base = head(loop_dir)
            baseline = measure_commit(repo, base, objective, command_runner=command_runner)
            if baseline.get("status") != "MEASURED":
                status = "STOPPED_BASELINE_MEASUREMENT"
                payload = {
                    "schema": GENERATION_SCHEMA,
                    "run_id": run_id,
                    "generation": number,
                    "base_commit": base,
                    "objective_sha256": objective_sha,
                    "evaluator_fingerprint": evaluator_fingerprint,
                    "config_sha256": config_sha,
                    "run_context": run_context,
                    "baseline": baseline,
                    "tournament": None,
                    "candidates": [],
                    "selection": {"status": status, "winner": None, "eligible": 0},
                    "decision": status,
                    "promoted_commit": None,
                    "parent_generation_receipt_sha256": previous_receipt_sha,
                    "what_this_record_means": "The frozen starting commit could not be measured, so no agents ran.",
                }
                signed_generation = sign(payload, key)
                generation_path = output_dir / f"generation-{number:02d}.json"
                write_json(generation_path, signed_generation)
                previous_receipt_sha = sha256_file(generation_path)
                generation_records.append({
                    "generation": number,
                    "base_commit": base,
                    "decision": status,
                    "promoted_commit": None,
                    "receipt": str(generation_path.relative_to(repo)),
                    "receipt_sha256": previous_receipt_sha,
                })
                break

            tournament = tournament_runner(
                loop_dir,
                _prompt(objective, baseline, number),
                agents=agents,
                models=models,
                budget=per_generation_budget,
                open_pr=False,
                config_path=loop_dir / config_path.relative_to(repo),
            )
            candidates: list[dict] = []
            seen_trees: dict[str, dict] = {}
            for row in tournament.get("candidates", []):
                if row.get("disposition") != "SURVIVED" or not isinstance(row.get("commit"), str):
                    candidates.append({
                        "candidate_id": row.get("candidate_id"),
                        "commit": row.get("commit"),
                        "disposition": "INELIGIBLE",
                        "reason": row.get("reason", "NOT_A_STRUCTURAL_SURVIVOR"),
                        "worker": _candidate_provenance(row),
                    })
                    continue
                try:
                    tree = git(repo, "rev-parse", f"{row['commit']}^{{tree}}")
                except RuntimeError:
                    candidates.append({
                        "candidate_id": row.get("candidate_id"),
                        "commit": row.get("commit"),
                        "disposition": "INELIGIBLE",
                        "reason": "CANDIDATE_COMMIT_UNREADABLE",
                        "worker": _candidate_provenance(row),
                    })
                    continue
                if tree in seen_trees:
                    seen_trees[tree].setdefault("equivalent_candidate_ids", []).append(row.get("candidate_id"))
                    continue
                evaluated = evaluate_survivor(
                    repo,
                    base=base,
                    row=row,
                    baseline=baseline,
                    objective=objective,
                    protected_paths=protected,
                    objective_relative_path=objective_relative,
                    command_runner=command_runner,
                )
                evaluated["tree"] = tree
                evaluated["equivalent_candidate_ids"] = [row.get("candidate_id")]
                seen_trees[tree] = evaluated
                candidates.append(evaluated)

            selection = select_unique_winner(
                candidates,
                Decimal(str(objective["selection"]["minimum_score_gap"])),
            )
            winner = selection.get("winner")
            decision = selection["status"]
            verification_sha = _copy_verification(loop_dir, repo, tournament)
            payload = {
                "schema": GENERATION_SCHEMA,
                "run_id": run_id,
                "generation": number,
                "base_commit": base,
                "objective_sha256": objective_sha,
                "evaluator_fingerprint": evaluator_fingerprint,
                "config_sha256": config_sha,
                "run_context": run_context,
                "baseline": baseline,
                "tournament": {
                    "run_id": tournament.get("run_id"),
                    "status": tournament.get("status"),
                    "requested_agents": tournament.get("requested_agents"),
                    "models": tournament.get("models"),
                    "survivor_count": tournament.get("survivor_count"),
                    "reported_cost": tournament.get("cost"),
                    "elapsed_seconds": tournament.get("elapsed_seconds"),
                    "verification_sha256": verification_sha,
                },
                "candidates": candidates,
                "selection": selection,
                "decision": decision,
                "promoted_commit": None if winner is None else winner["commit"],
                "parent_generation_receipt_sha256": previous_receipt_sha,
                "what_this_record_means": (
                    "The operator-owned objective, repository checks, and bounded scoring rule "
                    "either identified one compounding candidate or stopped the loop."
                ),
            }
            signed_generation = sign(payload, key)
            generation_path = output_dir / f"generation-{number:02d}.json"
            write_json(generation_path, signed_generation)
            previous_receipt_sha = sha256_file(generation_path)
            generation_records.append({
                "generation": number,
                "decision": decision,
                "base_commit": base,
                "promoted_commit": payload["promoted_commit"],
                "receipt": str(generation_path.relative_to(repo)),
                "receipt_sha256": previous_receipt_sha,
            })
            worker_usage.append({
                "generation": number,
                "run_id": tournament.get("run_id"),
                "models": tournament.get("models"),
                "requested_agents": tournament.get("requested_agents"),
                "reported_cost": tournament.get("cost"),
                "elapsed_seconds": tournament.get("elapsed_seconds"),
            })

            for row in tournament.get("candidates", []):
                _delete_airlock_branch(repo, row.get("branch"), improvement_branch)
            _delete_airlock_branch(repo, tournament.get("ready_branch"), improvement_branch)

            if winner is None:
                status = "STOPPED_AMBIGUOUS" if decision == "AMBIGUOUS" else "STOPPED_NO_IMPROVEMENT"
                break
            git(loop_dir, "reset", "--hard", winner["commit"])
            accepted += 1

        final_commit = head(loop_dir)
        final_measurement = measure_commit(repo, final_commit, objective, command_runner=command_runner)
        if status == "COMPLETED_LIMIT" and final_measurement.get("status") != "MEASURED":
            status = "STOPPED_FINAL_MEASUREMENT"
    finally:
        remove_worktree(repo, loop_dir)

    report_payload = {
        "schema": REPORT_SCHEMA,
        "run_id": run_id,
        "status": status,
        "objective": {
            "name": objective["name"],
            "goal": objective["goal"],
            "path": objective_relative,
            "sha256": objective_sha,
            "evaluator_fingerprint": evaluator_fingerprint,
        },
        "start_commit": start_commit,
        "final_commit": final_commit,
        "improvement_branch": improvement_branch,
        "generation_limit": generation_limit,
        "attempted_generations": len(generation_records),
        "accepted_generations": accepted,
        "run_context": run_context,
        "worker_usage": worker_usage,
        "budget_usd": budget,
        "per_generation_budget_usd": per_generation_budget,
        "generations": generation_records,
        "final_measurement": final_measurement,
        "latest_generation_receipt_sha256": previous_receipt_sha,
        "starting_ref_updated_by_airlock": False,
        "claim_boundary": (
            "This local run shows which exact commits cleared the configured checks and objective. "
            "It does not prove the objective represents total product value or authorize deployment."
        ),
    }
    signed_report = sign(report_payload, key)
    report_path = output_dir / "report.json"
    write_json(report_path, signed_report)
    report_payload["report_file"] = str(report_path.relative_to(repo))
    report_payload["report_sha256"] = sha256_file(report_path)
    return report_payload


def verify_improvement_report(report_path: Path, key_path: Path) -> dict:
    try:
        record = json.loads(report_path.read_text())
        key = key_path.read_bytes()
    except Exception as exc:
        return {"valid": False, "reason": "READ_ERROR", "detail": str(exc)}
    if not verify_signature(record, key):
        return {"valid": False, "reason": "SIGNATURE"}
    payload = record.get("payload", {})
    if payload.get("schema") != REPORT_SCHEMA:
        return {"valid": False, "reason": "SCHEMA"}
    report_dir = report_path.parent
    previous: str | None = None
    expected_base = payload.get("start_commit")
    for row in payload.get("generations", []):
        receipt_name = Path(str(row.get("receipt", ""))).name
        generation_path = report_dir / receipt_name
        if not generation_path.exists() or sha256_file(generation_path) != row.get("receipt_sha256"):
            return {"valid": False, "reason": "GENERATION_HASH"}
        generation = json.loads(generation_path.read_text())
        if not verify_signature(generation, key):
            return {"valid": False, "reason": "GENERATION_SIGNATURE"}
        generation_payload = generation.get("payload", {})
        if generation_payload.get("schema") != GENERATION_SCHEMA:
            return {"valid": False, "reason": "GENERATION_SCHEMA"}
        if generation_payload.get("run_id") != payload.get("run_id"):
            return {"valid": False, "reason": "GENERATION_RUN_ID"}
        if generation_payload.get("generation") != row.get("generation"):
            return {"valid": False, "reason": "GENERATION_NUMBER"}
        if generation_payload.get("base_commit") != expected_base:
            return {"valid": False, "reason": "GENERATION_BASE_CHAIN"}
        if generation_payload.get("parent_generation_receipt_sha256") != previous:
            return {"valid": False, "reason": "GENERATION_CHAIN"}
        previous = row["receipt_sha256"]
        if generation_payload.get("promoted_commit"):
            expected_base = generation_payload["promoted_commit"]
    if payload.get("latest_generation_receipt_sha256") != previous:
        return {"valid": False, "reason": "CHAIN_HEAD"}
    if payload.get("final_commit") != expected_base:
        return {"valid": False, "reason": "FINAL_COMMIT_CHAIN"}
    return {
        "valid": True,
        "schema": REPORT_SCHEMA,
        "run_id": payload.get("run_id"),
        "status": payload.get("status"),
        "accepted_generations": payload.get("accepted_generations"),
        "report_sha256": sha256_file(report_path),
    }
