from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .config import load as load_config
from .harness import HERMES_HARNESS_SCHEMA, fingerprint_harness_set
from .improvement import run_improvement_loop
from .providers import resolve_provider
from .runner import run_tournament
from .util import canonical_json_bytes, sha256_bytes, sha256_file, write_json
from .verification import ensure_key, sign


NIGHTSHIFT_CONTEXT_SCHEMA = "airlock.nightshift.context.v1"
WORKER_CONTACT_SCHEMA = "airlock.nightshift.worker-contact.v1"


def _profiles(values: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        for item in str(raw).split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def nightshift_models(agents: int, profiles: Iterable[str] | None = None) -> tuple[list[str], list[str]]:
    """Bind one Hermes worker identity to each candidate attempt."""
    if agents < 1:
        raise ValueError("--agents must be >= 1")
    chosen = _profiles(profiles)
    if agents == 1:
        if len(chosen) > 1:
            raise ValueError("one Hermes attempt accepts at most one profile")
        return (["hermes"] if not chosen else [f"hermes@{chosen[0]}"], chosen)

    if len(chosen) != agents:
        raise ValueError(
            "parallel Hermes competition requires one explicitly isolated profile per attempt; "
            "pass --profiles profile1,profile2,..."
        )
    if len(set(chosen)) != len(chosen):
        raise ValueError("parallel Hermes competition requires distinct profiles; shared writable state fakes independence")
    return ([f"hermes@{profile}" for profile in chosen], chosen)


def _receipt_path(repo: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo / path


def _read_generation_payload(repo: Path, row: dict) -> tuple[Path | None, dict]:
    path = _receipt_path(repo, row.get("receipt"))
    if path is None or not path.is_file():
        return path, {}
    try:
        record = json.loads(path.read_text())
    except Exception:
        return path, {}
    payload = record.get("payload", {})
    return path, payload if isinstance(payload, dict) else {}


def _worker_provenance(row: dict) -> dict:
    model = row.get("model")
    profile = None
    if isinstance(model, str) and model.startswith("hermes@"):
        profile = model.split("@", 1)[1]
    return {
        "model": model,
        "hermes_profile": profile,
        "agent_execution": row.get("agent_execution"),
        "agent_report": row.get("agent_report", {}),
        "harness": row.get("controller_harness"),
        "model_route": row.get("controller_model_route"),
    }




def _attempt_model_route(row: dict, harness: dict) -> dict:
    report = row.get("agent_report") or {}
    effective = report.get("model") if isinstance(report, dict) else None
    if not isinstance(effective, str) or not effective.strip():
        effective = None
    requested = (harness.get("routing") or {}).get("requested_model")
    return {
        "requested_model": requested,
        "requested_model_source": (harness.get("routing") or {}).get("requested_model_source"),
        "effective_model_observed": effective,
        "effective_model_observation": "agent_report.model" if effective is not None else "UNAVAILABLE",
        "matches_requested": None if effective is None or requested is None else effective == requested,
        "routing_fingerprint_sha256": (harness.get("routing") or {}).get("fingerprint_sha256"),
        "tool_registry_fingerprint_sha256": ((harness.get("routing") or {}).get("tool_registry") or {}).get("fingerprint_sha256"),
    }


def _contact_candidates(tournament: dict) -> list[dict]:
    contacts = []
    for row in tournament.get("candidates", []) or []:
        contacts.append({
            "candidate_id": row.get("candidate_id"),
            "commit": row.get("commit"),
            "disposition": "INELIGIBLE" if row.get("disposition") != "SURVIVED" else row.get("disposition"),
            "reason": row.get("reason", "WORKER_CONTACT_ONLY"),
            "tournament_disposition": row.get("disposition"),
            "changed_paths": row.get("changed_paths", []),
            "worker": _worker_provenance(row),
        })
    return contacts


def _retain_controller_contact(
    repo: Path,
    result: dict,
    captured_tournaments: list[dict],
) -> dict:
    """Keep real worker-contact evidence readable after a zero-patch generation.

    The improvement loop already signs ordinary generation receipts. HERMES-LIVE-001
    exposed a seam where the terminal controller could receive STOPPED_NO_IMPROVEMENT
    without being able to recover the worker provenance from that generation. This
    function does not grant candidate standing and does not change selection. It only
    guarantees that a signed controller-facing receipt exists when a tournament
    actually observed a worker contact.
    """
    generations = result.get("generations") or []
    if not generations:
        return result

    first = generations[0]
    existing_path, existing_payload = _read_generation_payload(repo, first)
    existing_candidates = existing_payload.get("candidates")
    if isinstance(existing_candidates, list) and existing_candidates:
        # Remove any relative-path ambiguity for the frozen terminal controller.
        if existing_path is not None:
            first["receipt"] = str(existing_path.resolve())
        return result

    if not captured_tournaments:
        return result
    tournament = captured_tournaments[0]
    contacts = _contact_candidates(tournament)
    if not contacts:
        return result

    run_id = str(result.get("run_id") or "unknown")
    generation_number = int(first.get("generation") or 1)
    output_dir = repo / ".airlock" / "improvements" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"worker-contact-source-{generation_number:02d}.json"
    write_json(raw_path, tournament)
    raw_sha = sha256_file(raw_path)

    payload = dict(existing_payload)
    payload.update({
        "schema": payload.get("schema") or "airlock.improvement.generation.v1",
        "run_id": payload.get("run_id") or run_id,
        "generation": payload.get("generation") or generation_number,
        "base_commit": payload.get("base_commit") or first.get("base_commit"),
        "candidates": contacts,
        "worker_contact_supplement": {
            "schema": WORKER_CONTACT_SCHEMA,
            "source_tournament_run_id": tournament.get("run_id"),
            "source_tournament_sha256": raw_sha,
            "source_tournament_payload_sha256": sha256_bytes(canonical_json_bytes(tournament)),
            "standing_granted": False,
            "selection_changed": False,
            "reason": "Retain worker execution and authority audit even when no candidate earns standing.",
        },
    })

    contact_path = output_dir / f"worker-contact-{generation_number:02d}.json"
    signed = sign(payload, ensure_key(repo / ".airlock" / "verification.key"))
    write_json(contact_path, signed)

    # The frozen HERMES-LIVE controller reads the receipt path from the returned
    # Nightshift report. Point that read at the signed supplemental receipt while
    # leaving the ordinary signed improvement report on disk untouched.
    first["receipt"] = str(contact_path.resolve())
    first["controller_contact_receipt_sha256"] = sha256_file(contact_path)
    result["controller_contact_receipt"] = str(contact_path.relative_to(repo))
    result["controller_contact_receipt_sha256"] = sha256_file(contact_path)
    return result


def run_nightshift(
    repo: Path,
    *,
    objective_path: str | Path = ".airlock/objective.json",
    generations: int | None = None,
    agents: int = 1,
    profiles: Iterable[str] | None = None,
    budget: float | None = None,
    config_path: Path | None = None,
    tournament_runner=None,
    command_runner=None,
) -> dict:
    """Run Hermes as a persistent proposer behind Airlock's independent improvement gate.

    A Hermes profile may retain memory/skills between generations. That mutable worker state
    never becomes the source of the objective, evaluator, or promotion decision.
    """
    repo = repo.resolve()
    config_path = (config_path or repo / ".airlock" / "config.json").resolve()
    config = load_config(config_path)
    models, chosen_profiles = nightshift_models(agents, profiles)

    # Preflight every worker identity before measuring or spending. This also enforces
    # the bounded Hermes credential rule and the direct-command requirement for
    # profile isolation.
    providers = [resolve_provider(config, model) for model in models]
    commands = [provider["command"] for provider in providers]
    pass_env = [provider.get("pass_env", []) for provider in providers]

    starting_harness = fingerprint_harness_set(models, providers)
    run_context = {
        "schema": NIGHTSHIFT_CONTEXT_SCHEMA,
        "worker": "hermes",
        "scripted_interface": "-z",
        "models": models,
        "profiles": chosen_profiles or ["default"],
        "attempts_per_generation": agents,
        "commands": commands,
        "pass_env": pass_env,
        "persistent_worker_state": True,
        "worker_state_controls_objective": False,
        "worker_state_controls_evaluator": False,
        "worker_state_controls_promotion": False,
        "harness_fingerprint_schema": HERMES_HARNESS_SCHEMA,
        "starting_harness": starting_harness,
        "harness_lineage": [],
        "harness_lineage_complete": True,
        "parallel_profile_rule": (
            "one distinct Hermes profile per candidate" if agents > 1 else "single worker identity"
        ),
        "authority_boundary": (
            "Hermes may mutate its own profile and candidate worktree; Airlock keeps the committed objective, "
            "repository checks, signed receipts, harness fingerprinting, and promotion decision outside that mutable worker state."
        ),
        "time_boundary": (
            "This software gate covers measured candidate standing and repository-state promotion. "
            "It is not a sub-second live feasibility controller for physical actuators."
        ),
    }

    captured_tournaments: list[dict] = []
    base_tournament_runner = tournament_runner or run_tournament
    previous_after = starting_harness

    def capturing_tournament_runner(*args, **kwargs):
        nonlocal previous_after
        before = fingerprint_harness_set(models, providers)
        expected_parent = previous_after["fingerprint_sha256"]
        if before["fingerprint_sha256"] != expected_parent:
            raise RuntimeError(
                "Hermes harness changed outside an observed Nightshift transition; "
                "refusing to spend against an unbound worker state"
            )

        report = base_tournament_runner(*args, **kwargs)
        after = fingerprint_harness_set(models, providers)
        workers_by_model = {row["airlock_model"]: row for row in before["workers"]}
        attempts = []
        for row in report.get("candidates", []) or []:
            model = row.get("model")
            if isinstance(model, str) and model in workers_by_model:
                harness = workers_by_model[model]
                route = _attempt_model_route(row, harness)
                row["controller_harness"] = harness
                row["controller_model_route"] = route
                attempts.append({
                    "candidate_id": row.get("candidate_id"),
                    "airlock_model": model,
                    "harness_fingerprint_sha256": harness["fingerprint_sha256"],
                    "model_route": route,
                })

        transition = {
            "generation": len(run_context["harness_lineage"]) + 1,
            "parent_harness_fingerprint_sha256": expected_parent,
            "before_fingerprint_sha256": before["fingerprint_sha256"],
            "worker_fingerprints_before": {
                row["airlock_model"]: row["fingerprint_sha256"]
                for row in before["workers"]
            },
            "after": after,
            "after_fingerprint_sha256": after["fingerprint_sha256"],
            "changed": before["fingerprint_sha256"] != after["fingerprint_sha256"],
            "continuity_from_prior": True,
            "source_tournament_run_id": report.get("run_id"),
            "attempts": attempts,
            "effective_model_observation_complete": bool(attempts) and all(
                row["model_route"]["effective_model_observed"] is not None for row in attempts
            ),
        }
        run_context["harness_lineage"].append(transition)
        previous_after = after
        captured_tournaments.append(report)
        return report

    kwargs = {"tournament_runner": capturing_tournament_runner}
    if command_runner is not None:
        kwargs["command_runner"] = command_runner

    result = run_improvement_loop(
        repo,
        objective_path=objective_path,
        generations=generations,
        agents=agents,
        models=models,
        budget=budget,
        config_path=config_path,
        run_context=run_context,
        **kwargs,
    )
    return _retain_controller_contact(repo, result, captured_tournaments)
