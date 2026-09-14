from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Decision = Literal["ACCEPT", "REJECT"]
Action = Literal["CONTINUE", "CONFIRM", "PROMOTE", "STOP"]

MAX_RESEARCHER_CALLS = 12
MAX_DISCOVERY_EVALUATIONS = 12
MAX_CONFIRMATION_EVALUATIONS = 1


@dataclass
class ProtocolState:
    phase: str = "AWAITING_INHERITANCE"
    inherited_a_verified: bool = False
    inherited_a_commit: str | None = None
    researcher_calls: int = 0
    discovery_evaluations: int = 0
    confirmation_evaluations: int = 0
    open_researcher_call: int | None = None
    apparent_b_candidate: str | None = None
    terminal_verdict: str | None = None
    events: list[dict] = field(default_factory=list)


def record_inheritance(state: ProtocolState, a_commit: str) -> None:
    if state.phase != "AWAITING_INHERITANCE":
        raise RuntimeError(f"cannot record inheritance in phase {state.phase}")
    if not a_commit:
        raise RuntimeError("inherited A commit is required")
    state.inherited_a_verified = True
    state.inherited_a_commit = a_commit
    state.phase = "SEARCHING_B"
    state.events.append({"event": "INHERITED_A_VERIFIED", "commit": a_commit})


def begin_researcher_call(state: ProtocolState) -> int:
    if state.phase != "SEARCHING_B" or not state.inherited_a_verified:
        raise RuntimeError(f"cannot begin B-search call in phase {state.phase}")
    if state.open_researcher_call is not None:
        raise RuntimeError("researcher call already open")
    if state.researcher_calls >= MAX_RESEARCHER_CALLS:
        state.phase = "TERMINAL"
        state.terminal_verdict = "INHERITED_A_SEARCH_BUDGET_EXHAUSTED"
        raise RuntimeError("researcher-call budget exhausted")
    state.researcher_calls += 1
    state.open_researcher_call = state.researcher_calls
    state.events.append({"event": "RESEARCHER_CALL_BEGAN", "call": state.researcher_calls})
    return state.researcher_calls


def abandon_researcher_call(state: ProtocolState, reason: str) -> Action:
    if state.phase != "SEARCHING_B" or state.open_researcher_call is None:
        raise RuntimeError("no open researcher call to abandon")
    call = state.open_researcher_call
    state.events.append({"event": "RESEARCHER_CALL_ABANDONED", "call": call, "reason": reason})
    state.open_researcher_call = None
    if state.researcher_calls >= MAX_RESEARCHER_CALLS:
        state.phase = "TERMINAL"
        state.terminal_verdict = "INHERITED_A_SEARCH_BUDGET_EXHAUSTED"
        return "STOP"
    return "CONTINUE"


def record_discovery(state: ProtocolState, candidate: str, decision: Decision) -> Action:
    if state.phase != "SEARCHING_B":
        raise RuntimeError(f"cannot record discovery in phase {state.phase}")
    if state.open_researcher_call is None:
        raise RuntimeError("discovery requires a preregistered researcher call")
    if state.discovery_evaluations >= MAX_DISCOVERY_EVALUATIONS:
        raise RuntimeError("discovery-evaluation budget exhausted")
    if candidate == state.inherited_a_commit:
        raise RuntimeError("B candidate cannot equal inherited A")

    call = state.open_researcher_call
    state.open_researcher_call = None
    state.discovery_evaluations += 1
    state.events.append({
        "event": "B_DISCOVERY_DECISION",
        "call": call,
        "candidate": candidate,
        "decision": decision,
        "discovery_index": state.discovery_evaluations,
    })

    if decision == "ACCEPT":
        state.phase = "CONFIRMING_B"
        state.apparent_b_candidate = candidate
        return "CONFIRM"
    if decision != "REJECT":
        raise RuntimeError(f"unsupported discovery decision: {decision}")
    if state.discovery_evaluations >= MAX_DISCOVERY_EVALUATIONS:
        state.phase = "TERMINAL"
        state.terminal_verdict = "INHERITED_A_NO_CONFIRMED_B"
        return "STOP"
    return "CONTINUE"


def record_confirmation(state: ProtocolState, candidate: str, decision: Decision) -> Action:
    if state.phase != "CONFIRMING_B":
        raise RuntimeError(f"cannot confirm B in phase {state.phase}")
    if state.confirmation_evaluations >= MAX_CONFIRMATION_EVALUATIONS:
        raise RuntimeError("confirmation budget exhausted")
    if candidate != state.apparent_b_candidate:
        raise RuntimeError("confirmation candidate differs from first apparent B")

    state.confirmation_evaluations += 1
    state.events.append({
        "event": "B_CONFIRMATION_DECISION",
        "candidate": candidate,
        "decision": decision,
        "confirmation_index": state.confirmation_evaluations,
    })

    if decision == "ACCEPT":
        state.phase = "B_PROMOTION_AUTHORIZED"
        return "PROMOTE"
    if decision == "REJECT":
        state.phase = "TERMINAL"
        state.terminal_verdict = "APPARENT_B_NOT_CONFIRMED"
        return "STOP"
    raise RuntimeError(f"unsupported confirmation decision: {decision}")


def record_promotion(state: ProtocolState, candidate: str) -> None:
    if state.phase != "B_PROMOTION_AUTHORIZED":
        raise RuntimeError("B promotion is not authorized")
    if candidate != state.apparent_b_candidate:
        raise RuntimeError("promotion candidate differs from confirmed B")
    state.events.append({"event": "B_PROMOTED", "candidate": candidate})
    state.phase = "TERMINAL"
    state.terminal_verdict = "CUMULATIVE_GOVERNED_OPTIMIZATION_PROMOTED"


def to_dict(state: ProtocolState) -> dict:
    return {
        "phase": state.phase,
        "inherited_a_verified": state.inherited_a_verified,
        "inherited_a_commit": state.inherited_a_commit,
        "researcher_calls": state.researcher_calls,
        "discovery_evaluations": state.discovery_evaluations,
        "confirmation_evaluations": state.confirmation_evaluations,
        "open_researcher_call": state.open_researcher_call,
        "apparent_b_candidate": state.apparent_b_candidate,
        "terminal_verdict": state.terminal_verdict,
        "events": state.events,
    }


def from_dict(value: dict) -> ProtocolState:
    return ProtocolState(
        phase=value.get("phase", "AWAITING_INHERITANCE"),
        inherited_a_verified=bool(value.get("inherited_a_verified", False)),
        inherited_a_commit=value.get("inherited_a_commit"),
        researcher_calls=int(value.get("researcher_calls", 0)),
        discovery_evaluations=int(value.get("discovery_evaluations", 0)),
        confirmation_evaluations=int(value.get("confirmation_evaluations", 0)),
        open_researcher_call=value.get("open_researcher_call"),
        apparent_b_candidate=value.get("apparent_b_candidate"),
        terminal_verdict=value.get("terminal_verdict"),
        events=list(value.get("events", [])),
    )
