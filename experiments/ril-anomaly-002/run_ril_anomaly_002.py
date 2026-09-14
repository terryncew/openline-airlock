#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EXPERIMENT = "RIL-ANOMALY-002"
SCHEMA = "openline.ril-anomaly-002.result.v1"
PREPARED_SCHEMA = "openline.ril-anomaly-002.prepared.v1"
STATE_SCHEMA = "openline.ril-anomaly-002.receiver-state.v1"
PACKET_SCHEMA = "openline.ril-anomaly-002.research-packet.v1"
OUTCOME_SCHEMA = "openline.ril-anomaly-002.receiver-outcome.v1"

FROZEN_MAIN = "734d4e8b6c341fe0f44b0b95c168a97d07493c8c"
SEED_FREEZE_PATH = Path("proofs/ril-rank-live-002/RIL_RANK_LIVE_002_FREEZE.json")
SEED_FREEZE_BLOB_SHA1 = "af4c4f9e96e6d9dd7bbe5c96fdcd05d9cd9c88bf"
SEED_VERDICT = "NO_OBSERVED_RIL_RANK_LIVE_002_TRANSFER_ADVANTAGE"
SEED_RESULT_SHA256 = "1005a9073ec099c58171e056bb73230c49a948db6a6b304f42914bf076d7caf2"

ANOMALY_001_FREEZE_PATH = Path("proofs/ril-anomaly-001/RIL_ANOMALY_001_FREEZE.json")
ANOMALY_001_FREEZE_SHA256 = "20109925aac11c7a49a0bf27a563b87d465f8b65d39c7b61cf07d7ce4dbe7199"
ANOMALY_001_VERDICT = "INCONCLUSIVE_RIL_ANOMALY_001_TERMINAL_FAILURE"
ANOMALY_001_FAILURE = "PROTOCOL_FAILURE_CROSS_ARM_PRODUCT_MEMORY_CONTAMINATION_BEFORE_CONTROL_ROUND_1"

ISOLATION_FREEZE_PATH = Path("proofs/ril-isolation-002/RIL_ISOLATION_002_FREEZE.json")
ISOLATION_FREEZE_SHA256 = "ce98f84046481f84f6e26a453fbc6f806e690e68f3d5c9bb6c13ae291f0d6285"
ISOLATION_VERDICT = "PASS_RIL_ISOLATION_002_GEMINI_TEMPORARY_CHAT_BOUNDARY"

ROUNDS_PER_ARM = 4
REQUIRED_PROMOTION_ADVANTAGE = 2
ROUND_MAX_RECEIVER_EVALS = 16
ROUND_MAX_EXTERNAL_USD = Decimal("1.50")
ROUND_MAX_WALL_SECONDS = 1200
ARM_MAX_RECEIVER_EVALS = ROUNDS_PER_ARM * ROUND_MAX_RECEIVER_EVALS
ARM_MAX_EXTERNAL_USD = ROUND_MAX_EXTERNAL_USD * ROUNDS_PER_ARM
ARM_MAX_WALL_SECONDS = ROUNDS_PER_ARM * ROUND_MAX_WALL_SECONDS

RESEARCHER = {"product": "Google Gemini consumer app", "model": "Flash Extended", "qualification_lineage": "3.8 Flash + Extended thinking", "mode": "Temporary Chat"}
ALLOWED_TOOLS = [
    "Gemini conversational reasoning",
]
MODES = ("anomaly_interview", "ordinary_search")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREREG_PATH = HERE / "RIL_ANOMALY_002_PREREGISTRATION.json"
DRIVER_PATH = HERE / "protected" / "research_driver.py"
ANOMALY_PROTOCOL_PATH = HERE / "ANOMALY_PROTOCOL.md"
CONTROL_PROTOCOL_PATH = HERE / "CONTROL_PROTOCOL.md"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(data)
    return sha256_bytes(data)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def dec(value: Any, name: str = "value") -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RuntimeError(f"invalid decimal {name}") from None
    if out < 0:
        raise RuntimeError(f"negative decimal {name}")
    return out


def load_driver():
    spec = importlib.util.spec_from_file_location("ril_anomaly_research_driver", DRIVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load response validator")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git_available(root: Path = ROOT) -> bool:
    return shutil.which("git") is not None and (root / ".git").exists()


def sh(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    cp = subprocess.run(list(args), cwd=None if cwd is None else str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and cp.returncode:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr[-1500:]}")
    return cp.stdout.strip()


def verify_repo(root: Path = ROOT) -> dict[str, Any]:
    seed_path = root / SEED_FREEZE_PATH
    anomaly_path = root / ANOMALY_001_FREEZE_PATH
    isolation_path = root / ISOLATION_FREEZE_PATH
    for path in (seed_path, anomaly_path, isolation_path):
        if not path.is_file():
            raise RuntimeError(f"required predecessor missing: {path.relative_to(root)}")

    seed = read_json(seed_path)
    if seed.get("experiment") != "RIL-RANK-LIVE-002" or seed.get("formal_verdict") != SEED_VERDICT:
        raise RuntimeError("seed freeze standing changed")
    if seed.get("integrity", {}).get("result_sha256") != SEED_RESULT_SHA256:
        raise RuntimeError("seed result binding changed")
    if seed.get("primary", {}).get("same_exact_selected_order_tasks") != 16:
        raise RuntimeError("seed exact-order observation changed")
    if seed.get("primary", {}).get("success_count_advantage") != 0:
        raise RuntimeError("seed null advantage changed")

    anomaly = read_json(anomaly_path)
    if sha256_file(anomaly_path) != ANOMALY_001_FREEZE_SHA256:
        raise RuntimeError("RIL-ANOMALY-001 freeze hash changed")
    if anomaly.get("formal_verdict") != ANOMALY_001_VERDICT:
        raise RuntimeError("RIL-ANOMALY-001 verdict changed")
    if anomaly.get("terminal_failure") != ANOMALY_001_FAILURE:
        raise RuntimeError("RIL-ANOMALY-001 failure cause changed")
    if anomaly.get("status") != "FROZEN_TERMINAL":
        raise RuntimeError("RIL-ANOMALY-001 is not terminal")

    isolation = read_json(isolation_path)
    if sha256_file(isolation_path) != ISOLATION_FREEZE_SHA256:
        raise RuntimeError("RIL-ISOLATION-002 freeze hash changed")
    if isolation.get("formal_verdict") != ISOLATION_VERDICT:
        raise RuntimeError("RIL-ISOLATION-002 qualification changed")
    if isolation.get("status") != "FROZEN_TERMINAL":
        raise RuntimeError("RIL-ISOLATION-002 is not terminal")
    successor = isolation.get("successor", {})
    if successor.get("experiment") != EXPERIMENT or successor.get("permission") != "MAY_PROCEED":
        raise RuntimeError("RIL-ISOLATION-002 did not authorize this successor")

    head = None
    seed_blob = None
    if git_available(root):
        head = sh("git", "rev-parse", "HEAD", cwd=root)
        anc = subprocess.run(["git", "merge-base", "--is-ancestor", FROZEN_MAIN, head], cwd=root)
        if anc.returncode:
            raise RuntimeError(f"HEAD is not descended from frozen main {FROZEN_MAIN}")
        seed_blob = sh("git", "rev-parse", f"HEAD:{SEED_FREEZE_PATH.as_posix()}", cwd=root)
        if seed_blob != SEED_FREEZE_BLOB_SHA1:
            raise RuntimeError(f"seed freeze blob changed: {seed_blob}")

    return {
        "verified": True,
        "frozen_main": FROZEN_MAIN,
        "head": head,
        "seed_freeze_blob_sha1": seed_blob or SEED_FREEZE_BLOB_SHA1,
        "seed_result_sha256": SEED_RESULT_SHA256,
        "anomaly_001_freeze_sha256": sha256_file(anomaly_path),
        "isolation_002_freeze_sha256": sha256_file(isolation_path),
        "qualified_substrate": RESEARCHER,
    }


def seed_anomaly(seed: dict[str, Any]) -> dict[str, Any]:
    primary = seed["primary"]
    return {
        "source_experiment": "RIL-RANK-LIVE-002",
        "source_formal_verdict": seed["formal_verdict"],
        "observed_failure": (
            "The frozen LIVE-002 experiment used two fresh Prince/Muse Spark 1.3 sessions whose only experimental difference "
            "was candidate presentation order. Prince reconstructed the same exact four-candidate evaluation order "
            "on all 16 tasks. Each arm produced 1/16 receiver-confirmed improvements and 63 receiver evaluations."
        ),
        "boundary": (
            "The LIVE-002 null applies to Prince under that frozen protocol. It does not establish that every "
            "live agent erases inherited ranking signal, and it does not establish that Prince cannot investigate a "
            "failure and discover a better search strategy."
        ),
        "primary": {
            "tasks": primary["tasks"],
            "same_exact_selected_order_tasks": primary["same_exact_selected_order_tasks"],
            "evidence_successes": primary["evidence_successes"],
            "baseline_successes": primary["baseline_successes"],
            "receiver_evaluations_evidence": primary["receiver_evaluations_evidence"],
            "receiver_evaluations_baseline": primary["receiver_evaluations_baseline"],
            "success_count_advantage": primary["success_count_advantage"],
        },
        "open_question": (
            "Can a researcher start from an unresolved failure, investigate where the current explanation stops working, "
            "design a discriminating experiment, and earn a new search lesson that produces more independently confirmed "
            "improvements than ordinary search under the same bounded resources?"
        ),
    }


def initial_head(seed_sha256: str) -> str:
    return sha256_bytes(canonical({
        "experiment": EXPERIMENT,
        "seed_freeze_sha256": seed_sha256,
        "isolation_freeze_sha256": ISOLATION_FREEZE_SHA256,
        "accepted_lessons": [],
    }))


def arm_map() -> dict[str, str]:
    sessions = ["session-1", "session-2"]
    modes = list(MODES)
    random.SystemRandom().shuffle(modes)
    return dict(zip(sessions, modes))


def protocol_text(mode: str) -> str:
    path = ANOMALY_PROTOCOL_PATH if mode == "anomaly_interview" else CONTROL_PROTOCOL_PATH
    return path.read_text()


def packet_for(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    arm = state["arms"][session_id]
    round_no = len(arm["attempts"]) + 1
    if round_no > ROUNDS_PER_ARM:
        raise RuntimeError(f"{session_id} already completed all rounds")
    visible_history = []
    for attempt in arm["attempts"]:
        visible_history.append({
            "round": attempt["round"],
            "proposal_summary": attempt["proposal_summary"],
            "receiver_outcome": attempt["receiver_outcome_public"],
            "promotion": attempt["promotion"],
        })
    return {
        "schema": PACKET_SCHEMA,
        "experiment": EXPERIMENT,
        "session_id": session_id,
        "round": round_no,
        "researcher": RESEARCHER,
        "available_tools": ALLOWED_TOOLS,
        "authority": "research/proposal only; receiver owns experiment execution, evaluation, promotion, and inheritance",
        "substrate_rule": (
            "This session is one arm-local Gemini Temporary Chat. Keep all four rounds for this arm in this same chat. "
            "Do not reference, request, reconstruct, or import the other arm. The second arm uses a separate fresh Temporary Chat."
        ),
        "seed_anomaly": state["seed_anomaly"],
        "accepted_head": arm["accepted_head"],
        "accepted_lessons": deepcopy(arm["accepted_lessons"]),
        "observed_history": visible_history,
        "round_limits": {
            "receiver_evaluations": ROUND_MAX_RECEIVER_EVALS,
            "external_compute_usd": str(ROUND_MAX_EXTERNAL_USD),
            "wall_seconds": ROUND_MAX_WALL_SECONDS,
        },
        "remaining_arm_budget": {
            "receiver_evaluations": ARM_MAX_RECEIVER_EVALS - arm["resources_used"]["receiver_evaluations"],
            "external_compute_usd": str(ARM_MAX_EXTERNAL_USD - dec(arm["resources_used"]["external_compute_usd"])),
            "wall_seconds": ARM_MAX_WALL_SECONDS - arm["resources_used"]["wall_seconds"],
            "research_rounds": ROUNDS_PER_ARM - len(arm["attempts"]),
        },
        "response_contract": {
            "experiment": EXPERIMENT,
            "session_id": session_id,
            "round": round_no,
            "source_accepted_head": arm["accepted_head"],
            "research_basis": {
                "observations": ["<observation>"],
                "competing_explanations": [{"id": "E1", "explanation": "<explanation>"}],
                "discriminating_observation": "<what observation would separate explanations>",
            },
            "proposed_experiment": {
                "name": "<short name>",
                "mechanism_change": "<what mechanism or search strategy changes>",
                "procedure": ["<bounded step>"],
                "predictions": [{"condition": "<if explanation/mechanism>", "expected": "<observable>"}],
                "falsifier": "<what would make you reject the proposed mechanism>",
                "success_metric": "<receiver-measurable improvement metric>",
            },
            "candidate_lesson": {
                "statement": "<lesson proposed for inheritance only if receiver promotion occurs>",
                "scope": "<where it applies>",
                "invalidation_conditions": ["<condition that reopens the lesson>"]
            },
            "resources_requested": {
                "receiver_evaluations": 0,
                "external_compute_usd": "0.00",
                "wall_seconds": 0,
            },
            "tools_used": [],
        },
        "ratchet_rule": (
            "A rejected or quarantined proposal may remain in observed history, but it cannot change accepted_head and its "
            "candidate_lesson cannot enter accepted_lessons. Only a receiver-confirmed PROMOTE advances the ratchet."
        ),
        "anti_rescue": (
            "After primary contact begins, do not change the seed anomaly, protocols, round count, resource ceilings, "
            "promotion rule, researcher substrate, Temporary Chat arm-isolation rule, or scoring threshold under this experiment ID."
        ),
    }


def prepare(output: Path, root: Path = ROOT) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("prepare output must be absent or empty")
    output.mkdir(parents=True, exist_ok=True)
    repo = verify_repo(root)
    seed = read_json(root / SEED_FREEZE_PATH)
    seed_sha = sha256_file(root / SEED_FREEZE_PATH)
    mapping = arm_map()
    head0 = initial_head(seed_sha)
    state = {
        "schema": STATE_SCHEMA,
        "experiment": EXPERIMENT,
        "prepared_utc": utcnow(),
        "frozen_repo": repo,
        "seed_anomaly": seed_anomaly(seed),
        "receiver_private_arm_map": mapping,
        "arms": {},
        "status": "PREPARED_NO_PRIMARY_CONTACT",
    }
    for session_id in sorted(mapping):
        state["arms"][session_id] = {
            "mode": mapping[session_id],
            "accepted_head": head0,
            "accepted_lessons": [],
            "attempts": [],
            "resources_used": {"receiver_evaluations": 0, "external_compute_usd": "0.000000", "wall_seconds": 0},
            "terminal": None,
        }
    state_sha = write_json(output / "receiver-private-state.json", state)
    packets = {}
    for session_id in sorted(mapping):
        session_dir = output / session_id
        session_dir.mkdir()
        packet = packet_for(state, session_id)
        packet_sha = write_json(session_dir / "packet.json", packet)
        (session_dir / "RESEARCH_PROTOCOL.md").write_text(protocol_text(mapping[session_id]))
        packets[session_id] = {
            "packet_sha256": packet_sha,
            "protocol_sha256": sha256_file(session_dir / "RESEARCH_PROTOCOL.md"),
        }
    seal = {
        "schema": PREPARED_SCHEMA,
        "experiment": EXPERIMENT,
        "receiver_private_state_sha256": state_sha,
        "seed_freeze_sha256": seed_sha,
        "seed_freeze_blob_sha1": SEED_FREEZE_BLOB_SHA1,
        "frozen_main": FROZEN_MAIN,
        "rounds_per_arm": ROUNDS_PER_ARM,
        "required_promotion_advantage": REQUIRED_PROMOTION_ADVANTAGE,
        "round_limits": {
            "receiver_evaluations": ROUND_MAX_RECEIVER_EVALS,
            "external_compute_usd": str(ROUND_MAX_EXTERNAL_USD),
            "wall_seconds": ROUND_MAX_WALL_SECONDS,
        },
        "packets": packets,
        "arm_map_is_receiver_private": True,
        "primary_contact_started": False,
    }
    write_json(output / "PREPARED_SEAL.json", seal)
    return seal


def response_summary(response: dict[str, Any]) -> dict[str, Any]:
    p = response["proposed_experiment"]
    return {
        "name": p["name"],
        "mechanism_change": p["mechanism_change"],
        "success_metric": p["success_metric"],
        "falsifier": p["falsifier"],
        "candidate_lesson": response["candidate_lesson"]["statement"],
    }


def validate_receiver_outcome(outcome: dict[str, Any], *, packet: dict[str, Any], response_sha256: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if outcome.get("schema") != OUTCOME_SCHEMA:
        issues.append("outcome schema mismatch")
    if outcome.get("experiment") != EXPERIMENT:
        issues.append("outcome experiment mismatch")
    if outcome.get("session_id") != packet["session_id"]:
        issues.append("outcome session mismatch")
    if outcome.get("round") != packet["round"]:
        issues.append("outcome round mismatch")
    if outcome.get("response_sha256") != response_sha256:
        issues.append("outcome response binding mismatch")
    if outcome.get("independent_evaluator") != "receiver":
        issues.append("independent_evaluator must be receiver")
    for key in ("protocol_valid", "confirmed_improvement", "regression_detected"):
        if not isinstance(outcome.get(key), bool):
            issues.append(f"{key} must be boolean")
    evidence = outcome.get("evidence_artifact_sha256")
    if not isinstance(evidence, str) or not HEX64.fullmatch(evidence):
        issues.append("evidence_artifact_sha256 must be sha256")
    evals = outcome.get("receiver_evaluations")
    wall = outcome.get("wall_seconds")
    try:
        usd = dec(outcome.get("external_compute_usd"), "external_compute_usd")
    except RuntimeError:
        usd = None
        issues.append("external_compute_usd invalid")
    if not isinstance(evals, int) or isinstance(evals, bool) or evals < 0 or evals > ROUND_MAX_RECEIVER_EVALS:
        issues.append("receiver_evaluations outside round limit")
    if not isinstance(wall, int) or isinstance(wall, bool) or wall < 0 or wall > ROUND_MAX_WALL_SECONDS:
        issues.append("wall_seconds outside round limit")
    if usd is not None and usd > ROUND_MAX_EXTERNAL_USD:
        issues.append("external_compute_usd outside round limit")
    return not issues, issues


def promotion_decision(outcome: dict[str, Any]) -> str:
    if not outcome["protocol_valid"]:
        return "QUARANTINE"
    if outcome["regression_detected"]:
        return "REJECT"
    if outcome["confirmed_improvement"]:
        return "PROMOTE"
    return "REJECT"


def successor_head(source_head: str, response: dict[str, Any], response_sha: str, outcome: dict[str, Any]) -> str:
    lesson = response["candidate_lesson"]
    material = {
        "source_accepted_head": source_head,
        "response_sha256": response_sha,
        "receiver_evidence_sha256": outcome["evidence_artifact_sha256"],
        "candidate_lesson_sha256": sha256_bytes(canonical(lesson)),
        "promotion": "PROMOTE",
    }
    return sha256_bytes(canonical(material))


def public_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_valid": outcome["protocol_valid"],
        "confirmed_improvement": outcome["confirmed_improvement"],
        "regression_detected": outcome["regression_detected"],
        "receiver_evaluations": outcome["receiver_evaluations"],
        "external_compute_usd": outcome["external_compute_usd"],
        "wall_seconds": outcome["wall_seconds"],
        "evidence_artifact_sha256": outcome["evidence_artifact_sha256"],
    }


def record_round(*, prepared: Path, session_id: str, response_path: Path, outcome_path: Path, next_packet: Path | None) -> dict[str, Any]:
    state_path = prepared / "receiver-private-state.json"
    state = read_json(state_path)
    if state.get("schema") != STATE_SCHEMA or state.get("experiment") != EXPERIMENT:
        raise RuntimeError("prepared state invalid")
    if session_id not in state["arms"]:
        raise RuntimeError("unknown session")
    arm = state["arms"][session_id]
    if arm["terminal"] is not None:
        raise RuntimeError("arm already terminal")
    packet = packet_for(state, session_id)
    response = read_json(response_path)
    driver = load_driver()
    valid, issues = driver.validate_response(packet, response, require_anomaly_method=(arm["mode"] == "anomaly_interview"))
    if not valid:
        arm["terminal"] = {"status": "PROTOCOL_FAILURE", "issues": issues, "round": packet["round"]}
        state["status"] = "PRIMARY_CONTACT_ACTIVE"
        write_json(state_path, state)
        return {"terminal": True, "status": "PROTOCOL_FAILURE", "issues": issues}

    response_sha = sha256_file(response_path)
    outcome = read_json(outcome_path)
    ok, outcome_issues = validate_receiver_outcome(outcome, packet=packet, response_sha256=response_sha)
    if not ok:
        arm["terminal"] = {"status": "RECEIVER_OUTCOME_INVALID", "issues": outcome_issues, "round": packet["round"]}
        state["status"] = "PRIMARY_CONTACT_ACTIVE"
        write_json(state_path, state)
        return {"terminal": True, "status": "RECEIVER_OUTCOME_INVALID", "issues": outcome_issues}

    new_evals = arm["resources_used"]["receiver_evaluations"] + outcome["receiver_evaluations"]
    new_usd = dec(arm["resources_used"]["external_compute_usd"]) + dec(outcome["external_compute_usd"])
    new_wall = arm["resources_used"]["wall_seconds"] + outcome["wall_seconds"]
    if new_evals > ARM_MAX_RECEIVER_EVALS or new_usd > ARM_MAX_EXTERNAL_USD or new_wall > ARM_MAX_WALL_SECONDS:
        arm["terminal"] = {"status": "BUDGET_EXHAUSTED", "round": packet["round"]}
        state["status"] = "PRIMARY_CONTACT_ACTIVE"
        write_json(state_path, state)
        return {"terminal": True, "status": "BUDGET_EXHAUSTED"}

    decision = promotion_decision(outcome)
    source_head = arm["accepted_head"]
    next_head = source_head
    inherited = False
    if decision == "PROMOTE":
        next_head = successor_head(source_head, response, response_sha, outcome)
        lesson = deepcopy(response["candidate_lesson"])
        lesson.update({
            "earned_from_round": packet["round"],
            "source_accepted_head": source_head,
            "successor_accepted_head": next_head,
            "response_sha256": response_sha,
            "receiver_evidence_sha256": outcome["evidence_artifact_sha256"],
        })
        arm["accepted_lessons"].append(lesson)
        arm["accepted_head"] = next_head
        inherited = True

    attempt = {
        "round": packet["round"],
        "source_accepted_head": source_head,
        "response_sha256": response_sha,
        "proposal_summary": response_summary(response),
        "receiver_outcome_public": public_outcome(outcome),
        "promotion": decision,
        "lesson_inherited": inherited,
        "successor_accepted_head": next_head,
    }
    arm["attempts"].append(attempt)
    arm["resources_used"] = {
        "receiver_evaluations": new_evals,
        "external_compute_usd": str(new_usd.quantize(Decimal("0.000001"))),
        "wall_seconds": new_wall,
    }
    state["status"] = "PRIMARY_CONTACT_ACTIVE"

    if len(arm["attempts"]) >= ROUNDS_PER_ARM:
        arm["terminal"] = {"status": "ROUNDS_COMPLETE", "round": packet["round"]}
    write_json(state_path, state)

    out = {
        "terminal": arm["terminal"] is not None,
        "status": arm["terminal"]["status"] if arm["terminal"] else "ROUND_COMPLETE",
        "promotion": decision,
        "accepted_head": arm["accepted_head"],
        "accepted_lessons": len(arm["accepted_lessons"]),
        "resources_used": arm["resources_used"],
    }
    if arm["terminal"] is None and next_packet is not None:
        np = packet_for(state, session_id)
        write_json(next_packet, np)
        out["next_packet"] = str(next_packet)
    return out


def score(prepared: Path, output: Path) -> dict[str, Any]:
    state = read_json(prepared / "receiver-private-state.json")
    arms = state["arms"]
    if any(arms[s]["terminal"] is None for s in arms):
        raise RuntimeError("both arms must be terminal before scoring")
    mode_to_session = {mode: session for session, mode in state["receiver_private_arm_map"].items()}
    metrics: dict[str, Any] = {}
    for mode in MODES:
        sid = mode_to_session[mode]
        arm = arms[sid]
        promotions = sum(1 for a in arm["attempts"] if a["promotion"] == "PROMOTE")
        rejects = sum(1 for a in arm["attempts"] if a["promotion"] == "REJECT")
        quarantines = sum(1 for a in arm["attempts"] if a["promotion"] == "QUARANTINE")
        metrics[mode] = {
            "session_id": sid,
            "promotions": promotions,
            "rejects": rejects,
            "quarantines": quarantines,
            "rounds_completed": len(arm["attempts"]),
            "accepted_lessons": len(arm["accepted_lessons"]),
            "final_accepted_head": arm["accepted_head"],
            "resources_used": arm["resources_used"],
            "terminal": arm["terminal"],
        }
    advantage = metrics["anomaly_interview"]["promotions"] - metrics["ordinary_search"]["promotions"]
    if any(metrics[m]["terminal"]["status"] in {"PROTOCOL_FAILURE", "RECEIVER_OUTCOME_INVALID", "BUDGET_EXHAUSTED"} for m in MODES):
        verdict = "INCONCLUSIVE_RIL_ANOMALY_002_TERMINAL_FAILURE"
    elif advantage >= REQUIRED_PROMOTION_ADVANTAGE:
        verdict = "PASS_RIL_ANOMALY_002_EARNED_RESEARCH_RATCHET"
    elif advantage <= -REQUIRED_PROMOTION_ADVANTAGE:
        verdict = "OBSERVED_RIL_ANOMALY_002_ORDINARY_SEARCH_ADVANTAGE"
    else:
        verdict = "NO_OBSERVED_RIL_ANOMALY_002_ADVANTAGE"
    result = {
        "schema": SCHEMA,
        "experiment": EXPERIMENT,
        "formal_verdict": verdict,
        "scientific_standing": "SINGLE_RUN_MATCHED_START_OPEN_ENDED_RESEARCH_PROCESS_WITH_RECEIVER_RATCHET",
        "required_promotion_advantage": REQUIRED_PROMOTION_ADVANTAGE,
        "promotion_advantage": advantage,
        "arms": metrics,
        "ratchet": {
            "state": "accepted_head",
            "promotion_rule": "receiver-confirmed improvement only",
            "rejected_or_quarantined_lessons_inherited": False,
            "observed_negative_results_retained": True,
            "compare_and_swap_binding": "source accepted_head -> receiver evidence -> successor accepted_head",
        },
        "claim_boundary": {
            "earned_if_pass": (
                "Under this single bounded run, anomaly-first investigation produced at least two more independently "
                "receiver-confirmed promoted research improvements than ordinary search from the same starting failure and resource ceilings."
            ),
            "not_earned": [
                "recursive self-improvement",
                "Level 4 autonomous improvement",
                "general scientific judgment advantage",
                "universal researcher advantage",
                "repeatability",
                "production value",
                "economic payback",
                "hostile-process isolation",
            ],
        },
        "seed": state["seed_anomaly"],
        "scored_utc": utcnow(),
    }
    write_json(output, result)
    return result


def self_check() -> dict[str, Any]:
    # Instrument-power check only. Simulate the receiver ratchet with deterministic valid records.
    seed_sha = "1" * 64
    h0 = initial_head(seed_sha)
    fake_response = {
        "experiment": EXPERIMENT,
        "session_id": "session-1",
        "round": 1,
        "source_accepted_head": h0,
        "research_basis": {
            "observations": ["the prior mechanism stopped changing behavior"],
            "competing_explanations": [
                {"id": "E1", "explanation": "researcher reconstructs choices independently"},
                {"id": "E2", "explanation": "presentation signal is too weak to survive selection"},
            ],
            "discriminating_observation": "remove candidate ordering and perturb available evidence instead",
        },
        "proposed_experiment": {
            "name": "probe",
            "mechanism_change": "change evidence available to search, not list order",
            "procedure": ["freeze two explanations", "run one discriminating probe"],
            "predictions": [
                {"condition": "E1", "expected": "same choices despite order"},
                {"condition": "E2", "expected": "choices change when evidence changes"},
            ],
            "falsifier": "no behavioral separation under the evidence perturbation",
            "success_metric": "receiver-confirmed improvement count",
        },
        "candidate_lesson": {
            "statement": "intervene on search evidence rather than presentation order",
            "scope": "live candidate search",
            "invalidation_conditions": ["no receiver-confirmed gain on fresh tasks"],
        },
        "resources_requested": {"receiver_evaluations": 4, "external_compute_usd": "0.00", "wall_seconds": 60},
        "tools_used": ["Gemini conversational reasoning"],
    }
    packet = {
        "experiment": EXPERIMENT,
        "session_id": "session-1",
        "round": 1,
        "accepted_head": h0,
        "round_limits": {
            "receiver_evaluations": ROUND_MAX_RECEIVER_EVALS,
            "external_compute_usd": str(ROUND_MAX_EXTERNAL_USD),
            "wall_seconds": ROUND_MAX_WALL_SECONDS,
        },
    }
    driver = load_driver()
    good, issues = driver.validate_response(packet, fake_response, require_anomaly_method=True)
    if not good:
        raise RuntimeError(f"valid anomaly response rejected: {issues}")
    weak = deepcopy(fake_response)
    weak["research_basis"]["competing_explanations"] = weak["research_basis"]["competing_explanations"][:1]
    weak_ok, _ = driver.validate_response(packet, weak, require_anomaly_method=True)
    if weak_ok:
        raise RuntimeError("anomaly validator failed to require competing explanations")
    control_ok, control_issues = driver.validate_response(packet, weak, require_anomaly_method=False)
    if not control_ok:
        raise RuntimeError(f"ordinary-search validator overconstrained control: {control_issues}")

    outcome = {
        "schema": OUTCOME_SCHEMA,
        "experiment": EXPERIMENT,
        "session_id": "session-1",
        "round": 1,
        "response_sha256": sha256_bytes(canonical(fake_response)),
        "independent_evaluator": "receiver",
        "protocol_valid": True,
        "confirmed_improvement": True,
        "regression_detected": False,
        "evidence_artifact_sha256": "2" * 64,
        "receiver_evaluations": 4,
        "external_compute_usd": "0.00",
        "wall_seconds": 60,
    }
    # Outcome binding validator is file-hash based in primary. Here check decision and head semantics directly.
    if promotion_decision(outcome) != "PROMOTE":
        raise RuntimeError("positive receiver outcome failed to promote")
    h1 = successor_head(h0, fake_response, outcome["response_sha256"], outcome)
    if h1 == h0 or not HEX64.fullmatch(h1):
        raise RuntimeError("ratchet failed to advance accepted head")
    negative = dict(outcome, confirmed_improvement=False)
    if promotion_decision(negative) != "REJECT":
        raise RuntimeError("negative receiver outcome did not reject")
    quarantine = dict(outcome, protocol_valid=False)
    if promotion_decision(quarantine) != "QUARANTINE":
        raise RuntimeError("invalid protocol did not quarantine")

    return {
        "self_check": "PASS",
        "valid_anomaly_response": True,
        "weak_anomaly_response_rejected": True,
        "same_weak_response_valid_as_ordinary_search": True,
        "promote_advances_head": h1 != h0,
        "reject_does_not_imply_promotion": True,
        "quarantine_does_not_imply_promotion": True,
        "rounds_per_arm": ROUNDS_PER_ARM,
        "required_promotion_advantage": REQUIRED_PROMOTION_ADVANTAGE,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-check")
    sub.add_parser("verify-repo")
    p = sub.add_parser("prepare")
    p.add_argument("--output", required=True, type=Path)
    r = sub.add_parser("record-round")
    r.add_argument("--prepared", required=True, type=Path)
    r.add_argument("--session-id", required=True, choices=["session-1", "session-2"])
    r.add_argument("--response", required=True, type=Path)
    r.add_argument("--outcome", required=True, type=Path)
    r.add_argument("--next-packet", type=Path)
    s = sub.add_parser("score")
    s.add_argument("--prepared", required=True, type=Path)
    s.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    if args.cmd == "self-check":
        print(json.dumps(self_check(), indent=2, sort_keys=True))
        return 0
    if args.cmd == "verify-repo":
        print(json.dumps(verify_repo(), indent=2, sort_keys=True))
        return 0
    if args.cmd == "prepare":
        print(json.dumps(prepare(args.output), indent=2, sort_keys=True))
        return 0
    if args.cmd == "record-round":
        print(json.dumps(record_round(prepared=args.prepared, session_id=args.session_id, response_path=args.response, outcome_path=args.outcome, next_packet=args.next_packet), indent=2, sort_keys=True))
        return 0
    if args.cmd == "score":
        print(json.dumps(score(args.prepared, args.output), indent=2, sort_keys=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
