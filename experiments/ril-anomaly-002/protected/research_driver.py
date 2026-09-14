#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EXPERIMENT = "RIL-ANOMALY-002"
ALLOWED_TOOLS = {
    "Gemini conversational reasoning",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_response(packet: dict[str, Any], response: dict[str, Any], *, require_anomaly_method: bool) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if response.get("experiment") != EXPERIMENT:
        issues.append("experiment mismatch")
    if response.get("session_id") != packet.get("session_id"):
        issues.append("session_id mismatch")
    if response.get("round") != packet.get("round"):
        issues.append("round mismatch")
    if response.get("source_accepted_head") != packet.get("accepted_head"):
        issues.append("source_accepted_head mismatch")

    basis = response.get("research_basis")
    if not isinstance(basis, dict):
        issues.append("research_basis must be an object")
        basis = {}
    observations = basis.get("observations")
    if not isinstance(observations, list) or not observations or not all(_nonempty(x) for x in observations):
        issues.append("research_basis.observations must be a nonempty string list")
    alternatives = basis.get("competing_explanations", [])
    if not isinstance(alternatives, list) or not all(isinstance(x, dict) and _nonempty(x.get("id")) and _nonempty(x.get("explanation")) for x in alternatives):
        issues.append("research_basis.competing_explanations malformed")
    if require_anomaly_method and len(alternatives) < 2:
        issues.append("anomaly method requires at least two competing explanations")
    if require_anomaly_method and not _nonempty(basis.get("discriminating_observation")):
        issues.append("anomaly method requires discriminating_observation")

    proposal = response.get("proposed_experiment")
    if not isinstance(proposal, dict):
        issues.append("proposed_experiment must be an object")
        proposal = {}
    for field in ("name", "mechanism_change", "falsifier", "success_metric"):
        if not _nonempty(proposal.get(field)):
            issues.append(f"proposed_experiment.{field} missing")
    procedure = proposal.get("procedure")
    if not isinstance(procedure, list) or not procedure or not all(_nonempty(x) for x in procedure):
        issues.append("proposed_experiment.procedure must be a nonempty string list")
    predictions = proposal.get("predictions")
    if not isinstance(predictions, list) or not predictions or not all(isinstance(x, dict) and _nonempty(x.get("condition")) and _nonempty(x.get("expected")) for x in predictions):
        issues.append("proposed_experiment.predictions malformed")
    if require_anomaly_method and len(predictions) < 2:
        issues.append("anomaly method requires competing predictions")

    lesson = response.get("candidate_lesson")
    if not isinstance(lesson, dict):
        issues.append("candidate_lesson must be an object")
        lesson = {}
    if not _nonempty(lesson.get("statement")):
        issues.append("candidate_lesson.statement missing")
    if not _nonempty(lesson.get("scope")):
        issues.append("candidate_lesson.scope missing")
    invalidation = lesson.get("invalidation_conditions")
    if not isinstance(invalidation, list) or not invalidation or not all(_nonempty(x) for x in invalidation):
        issues.append("candidate_lesson.invalidation_conditions must be a nonempty string list")

    resources = response.get("resources_requested")
    if not isinstance(resources, dict):
        issues.append("resources_requested must be an object")
        resources = {}
    evals = resources.get("receiver_evaluations")
    wall = resources.get("wall_seconds")
    usd = _decimal(resources.get("external_compute_usd"))
    limits = packet.get("round_limits", {})
    if not isinstance(evals, int) or isinstance(evals, bool) or evals < 0:
        issues.append("receiver_evaluations must be a nonnegative integer")
    elif evals > int(limits.get("receiver_evaluations", 0)):
        issues.append("receiver_evaluations exceeds round limit")
    if not isinstance(wall, int) or isinstance(wall, bool) or wall < 0:
        issues.append("wall_seconds must be a nonnegative integer")
    elif wall > int(limits.get("wall_seconds", 0)):
        issues.append("wall_seconds exceeds round limit")
    max_usd = _decimal(limits.get("external_compute_usd"))
    if usd is None or usd < 0:
        issues.append("external_compute_usd invalid")
    elif max_usd is None or usd > max_usd:
        issues.append("external_compute_usd exceeds round limit")

    tools = response.get("tools_used")
    if not isinstance(tools, list) or not all(_nonempty(x) for x in tools):
        issues.append("tools_used must be a string list")
    else:
        unknown = sorted(set(tools) - ALLOWED_TOOLS)
        if unknown:
            issues.append(f"unapproved tool(s): {unknown}")

    return not issues, issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packet", required=True, type=Path)
    ap.add_argument("--response", required=True, type=Path)
    ap.add_argument("--require-anomaly-method", action="store_true")
    args = ap.parse_args()
    packet = json.loads(args.packet.read_text())
    response = json.loads(args.response.read_text())
    ok, issues = validate_response(packet, response, require_anomaly_method=args.require_anomaly_method)
    print(json.dumps({"valid": ok, "issues": issues}, indent=2, sort_keys=True))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
