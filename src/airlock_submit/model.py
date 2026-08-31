from __future__ import annotations

ACTIVE_STATES = {"RECEIVED", "QUEUED", "EVALUATING", "SURVIVED"}
FINAL_STATES = {"BLOCKED", "NEEDS_EVIDENCE", "PR_OPENED", "ERROR"}
VALID_STATES = ACTIVE_STATES | FINAL_STATES


def require_state(value: str) -> str:
    if value not in VALID_STATES:
        raise ValueError(f"invalid submission state: {value}")
    return value
