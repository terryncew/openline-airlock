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
    phase: str = "SEARCHING"
    researcher_calls: int = 0
    discovery_evaluations: int = 0
    confirmation_evaluations: int = 0
    open_researcher_call: int | None = None
    apparent_win_candidate: str | None = None
    terminal_verdict: str | None = None
    events: list[dict] = field(default_factory=list)


def begin_researcher_call(state: ProtocolState) -> int:
    if state.phase != "SEARCHING":
        raise RuntimeError(f"cannot begin researcher call in phase {state.phase}")
    if state.open_researcher_call is not None:
        raise RuntimeError("researcher call already open")
    if state.researcher_calls >= MAX_RESEARCHER_CALLS:
        state.phase = "TERMINAL"
        state.terminal_verdict = "WORKER_BUDGET_EXHAUSTED_NO_CONFIRMED_IMPROVEMENT"
        raise RuntimeError("researcher-call budget exhausted")
    state.researcher_calls += 1
    state.open_researcher_call = state.researcher_calls
    state.events.append({"event": "RESEARCHER_CALL_BEGAN", "call": state.researcher_calls})
    return state.researcher_calls


def abandon_researcher_call(state: ProtocolState, reason: str) -> Action:
    if state.phase != "SEARCHING" or state.open_researcher_call is None:
        raise RuntimeError("no open researcher call to abandon")
    call = state.open_researcher_call
    state.events.append({"event": "RESEARCHER_CALL_ABANDONED", "call": call, "reason": reason})
    state.open_researcher_call = None
    if state.researcher_calls >= MAX_RESEARCHER_CALLS:
        state.phase = "TERMINAL"
        state.terminal_verdict = "WORKER_BUDGET_EXHAUSTED_NO_CONFIRMED_IMPROVEMENT"
        return "STOP"
    return "CONTINUE"


def record_discovery(state: ProtocolState, candidate: str, decision: Decision) -> Action:
    if state.phase != "SEARCHING":
        raise RuntimeError(f"cannot record discovery in phase {state.phase}")
    if state.open_researcher_call is None:
        raise RuntimeError("discovery requires a preregistered researcher call")
    if state.discovery_evaluations >= MAX_DISCOVERY_EVALUATIONS:
        raise RuntimeError("discovery-evaluation budget exhausted")

    call = state.open_researcher_call
    state.open_researcher_call = None
    state.discovery_evaluations += 1
    state.events.append({
        "event": "DISCOVERY_DECISION",
        "call": call,
        "candidate": candidate,
        "decision": decision,
        "discovery_index": state.discovery_evaluations,
    })

    if decision == "ACCEPT":
        state.phase = "CONFIRMING"
        state.apparent_win_candidate = candidate
        return "CONFIRM"

    if decision != "REJECT":
        raise RuntimeError(f"unsupported discovery decision: {decision}")

    if state.discovery_evaluations >= MAX_DISCOVERY_EVALUATIONS:
        state.phase = "TERMINAL"
        state.terminal_verdict = "GOVERNANCE_PASS_NO_CONFIRMED_IMPROVEMENT"
        return "STOP"
    return "CONTINUE"


def record_confirmation(state: ProtocolState, candidate: str, decision: Decision) -> Action:
    if state.phase != "CONFIRMING":
        raise RuntimeError(f"cannot confirm in phase {state.phase}")
    if state.confirmation_evaluations >= MAX_CONFIRMATION_EVALUATIONS:
        raise RuntimeError("confirmation budget exhausted")
    if candidate != state.apparent_win_candidate:
        raise RuntimeError("confirmation candidate differs from first apparent winner")

    state.confirmation_evaluations += 1
    state.events.append({
        "event": "CONFIRMATION_DECISION",
        "candidate": candidate,
        "decision": decision,
        "confirmation_index": state.confirmation_evaluations,
    })

    if decision == "ACCEPT":
        state.phase = "PROMOTION_AUTHORIZED"
        return "PROMOTE"
    if decision == "REJECT":
        state.phase = "TERMINAL"
        state.terminal_verdict = "APPARENT_WIN_NOT_CONFIRMED"
        return "STOP"
    raise RuntimeError(f"unsupported confirmation decision: {decision}")


def record_promotion(state: ProtocolState, candidate: str) -> None:
    if state.phase != "PROMOTION_AUTHORIZED":
        raise RuntimeError("promotion is not authorized")
    if candidate != state.apparent_win_candidate:
        raise RuntimeError("promotion candidate differs from confirmed candidate")
    state.events.append({"event": "PROMOTED", "candidate": candidate})
    state.phase = "TERMINAL"
    state.terminal_verdict = "CONFIRMED_LIVE_IMPROVEMENT_PROMOTED"


def to_dict(state: ProtocolState) -> dict:
    return {
        "phase": state.phase,
        "researcher_calls": state.researcher_calls,
        "discovery_evaluations": state.discovery_evaluations,
        "confirmation_evaluations": state.confirmation_evaluations,
        "open_researcher_call": state.open_researcher_call,
        "apparent_win_candidate": state.apparent_win_candidate,
        "terminal_verdict": state.terminal_verdict,
        "events": state.events,
    }


def from_dict(value: dict) -> ProtocolState:
    return ProtocolState(
        phase=value.get("phase", "SEARCHING"),
        researcher_calls=int(value.get("researcher_calls", 0)),
        discovery_evaluations=int(value.get("discovery_evaluations", 0)),
        confirmation_evaluations=int(value.get("confirmation_evaluations", 0)),
        open_researcher_call=value.get("open_researcher_call"),
        apparent_win_candidate=value.get("apparent_win_candidate"),
        terminal_verdict=value.get("terminal_verdict"),
        events=list(value.get("events", [])),
    )
