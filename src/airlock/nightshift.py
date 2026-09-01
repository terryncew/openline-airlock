from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .config import load as load_config
from .improvement import run_improvement_loop
from .providers import resolve_provider


NIGHTSHIFT_CONTEXT_SCHEMA = "airlock.nightshift.context.v1"


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
        "parallel_profile_rule": (
            "one distinct Hermes profile per candidate" if agents > 1 else "single worker identity"
        ),
        "authority_boundary": (
            "Hermes may mutate its own profile and candidate worktree; Airlock keeps the committed objective, "
            "repository checks, signed receipts, and promotion decision outside that mutable worker state."
        ),
        "time_boundary": (
            "This software gate covers measured candidate standing and repository-state promotion. "
            "It is not a sub-second live feasibility controller for physical actuators."
        ),
    }

    kwargs = {}
    if tournament_runner is not None:
        kwargs["tournament_runner"] = tournament_runner
    if command_runner is not None:
        kwargs["command_runner"] = command_runner

    return run_improvement_loop(
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
