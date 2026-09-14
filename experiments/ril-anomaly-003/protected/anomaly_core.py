#!/usr/bin/env python3
"""RIL-ANOMALY-003 shared core.

Rebuilt 2026-09-14 around a complete receiver truth table (no proxy metric).

Design (frozen):
- 16 frozen tasks from the RIL-RANK-LIVE-002 pool, 4 task families x 4 tasks.
- Before any primary API contact, the receiver executes ALL 12 candidates of
  every task locally (192 evaluations) and seals the complete acceptance truth.
- The 16 tasks are split into 4 disjoint matched round blocks, one task per
  family per round. Both arms see the same schedule.
- Every proposed method must deterministically select AND ORDER exactly 4 of
  the 12 opaque candidate IDs per task, using only the public candidate
  features/descriptions. The receiver scores the ordered selection against the
  sealed hidden truth with the original LIVE-002 semantics:
    task success  = an acceptable candidate appears in the selected four
    evaluations-to-first-success = its ordered position (1-4)
- PROMOTE only if the proposed method loses no receiver-confirmed task
  success relative to the current accepted head on that round's block AND
  either gains at least one task success or preserves all successes while
  reducing total evaluations-to-first-success. Otherwise REJECT/QUARANTINE
  and the head does not move. No proxy coverage metric may trigger promotion.

The hidden truth (per-candidate acceptance) is NEVER placed in a GPT packet.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

EXPERIMENT = "RIL-ANOMALY-003"
SCHEMA_PREREG = "openline.ril-anomaly-003.preregistration.v2"
SCHEMA_TRUTH = "openline.ril-anomaly-003.truth-table.v1"
SCHEMA_SCHEDULE = "openline.ril-anomaly-003.schedule.v1"
SCHEMA_SEAL = "openline.ril-anomaly-003.seal.v1"
SCHEMA_RECEIPT = "openline.ril-anomaly-003.receipt.v1"

# Isolation binding (frozen, verified 2026-09-14 from evidence):
# - provider-returned model identifier in all four -002 call records: gpt-6-astra
#   (api_driver.py populated model=str(response_body.get("model","")))
# - isolation receipt: evidence/ril-api-isolation-002/RIL_API_ISOLATION_002_RECEIPT.json
# - receipt SHA-256: 37b636a1d515d4b8c4b539327d8392c0859211e48d1edd7cd7c85d0a25aa27dd
# - frozen isolation commit: fb54967
MODEL_ID = "gpt-6-astra"
ISOLATION_002_RECEIPT = "evidence/ril-api-isolation-002/RIL_API_ISOLATION_002_RECEIPT.json"
ISOLATION_002_RECEIPT_SHA256 = "37b636a1d515d4b8c4b539327d8392c0859211e48d1edd7cd7c85d0a25aa27dd"
ISOLATION_002_COMMIT = "fb54967"

ARMS = ("anomaly_interview", "ordinary_search")
ROUNDS = (1, 2, 3, 4)
SELECTION_BUDGET = 4
CANDIDATES_PER_TASK = 12

# Pricing pinned from the -002 run (2026-09-14): $10 / 1M input, $50 / 1M out.
PRICE_INPUT_PER_1M = 10.0
PRICE_OUTPUT_PER_1M = 50.0
ARM_BUDGET_USD = 4.0
TOTAL_BUDGET_USD = 8.0
# Hard per-call ceiling: an arm has $4 over 4 calls; fail closed well under it.
PER_CALL_HARD_CEILING_USD = 1.0

RULE_TYPES = ("explicit_ids", "positional", "complement_positional")
# Rule types whose selections are computable on ANY block (carry forward as head).
GENERAL_RULE_TYPES = ("positional", "complement_positional")

SEAL_DIRNAME = "proofs/ril-anomaly-003"
TRUTH_FILENAME = "RIL_ANOMALY_003_TRUTH_TABLE.json"
SCHEDULE_FILENAME = "RIL_ANOMALY_003_SCHEDULE.json"
SEAL_FILENAME = "RIL_ANOMALY_003_SEAL.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# Method rules: validation and deterministic execution
# ---------------------------------------------------------------------------

def _task_candidate_ids(schedule: dict, task_id: str) -> list[str]:
    return list(schedule["tasks"][task_id]["presented_order"])


def _task_historical_ids(schedule: dict, task_id: str) -> list[str]:
    return list(schedule["tasks"][task_id]["historical_selected_order"])


def normalize_rule(
    rule: Any, block_task_ids: list[str], schedule: dict
) -> tuple[bool, list[str], dict[str, list[str]] | None]:
    """Validate a proposed method rule and execute it deterministically.

    Returns (ok, issues, selections). Selections maps task_id -> ordered list
    of exactly 4 candidate IDs. ok=False means the round is QUARANTINED: the
    rule is not an executable deterministic selection over the public IDs.
    """
    issues: list[str] = []
    if not isinstance(rule, dict):
        return False, ["rule is not a JSON object"], None
    rtype = rule.get("type")
    if rtype not in RULE_TYPES:
        return False, [f"rule type {rtype!r} not in {RULE_TYPES}"], None

    selections: dict[str, list[str]] = {}
    try:
        if rtype == "explicit_ids":
            sels = rule.get("selections")
            if not isinstance(sels, dict):
                return False, ["explicit_ids requires a 'selections' object"], None
            for tid in block_task_ids:
                ids = sels.get(tid)
                pool = set(_task_candidate_ids(schedule, tid))
                if not isinstance(ids, list) or len(ids) != SELECTION_BUDGET:
                    issues.append(f"{tid}: must list exactly {SELECTION_BUDGET} IDs")
                    continue
                if len(set(ids)) != SELECTION_BUDGET:
                    issues.append(f"{tid}: IDs not unique")
                bad = [i for i in ids if i not in pool]
                if bad:
                    issues.append(f"{tid}: IDs not among the task's 12 candidates: {bad}")
                selections[tid] = list(ids)
            extra = [t for t in sels if t not in block_task_ids]
            if extra:
                issues.append(f"selections for tasks outside this block: {extra}")
        elif rtype == "positional":
            pos = rule.get("positions")
            if (
                not isinstance(pos, list)
                or len(pos) != SELECTION_BUDGET
                or any(not isinstance(p, int) for p in pos)
            ):
                return False, ["positional requires 'positions': 4 integer indices"], None
            if len(set(pos)) != SELECTION_BUDGET:
                return False, ["positional indices not unique"], None
            if any(p < 0 or p >= CANDIDATES_PER_TASK for p in pos):
                return False, ["positional index out of range 0-11"], None
            for tid in block_task_ids:
                presented = _task_candidate_ids(schedule, tid)
                selections[tid] = [presented[p] for p in pos]
        elif rtype == "complement_positional":
            pos = rule.get("positions")
            if (
                not isinstance(pos, list)
                or len(pos) != SELECTION_BUDGET
                or any(not isinstance(p, int) for p in pos)
            ):
                return False, ["complement_positional requires 'positions': 4 integer indices"], None
            if len(set(pos)) != SELECTION_BUDGET:
                return False, ["complement_positional indices not unique"], None
            if any(p < 0 or p >= (CANDIDATES_PER_TASK - SELECTION_BUDGET) for p in pos):
                return False, ["complement_positional index out of range 0-7"], None
            for tid in block_task_ids:
                presented = _task_candidate_ids(schedule, tid)
                historical = set(_task_historical_ids(schedule, tid))
                rest = [cid for cid in presented if cid not in historical]
                if len(rest) != CANDIDATES_PER_TASK - SELECTION_BUDGET:
                    return False, [f"{tid}: historical overlap unexpected"], None
                selections[tid] = [rest[p] for p in pos]
    except (KeyError, TypeError) as exc:
        return False, [f"rule execution error: {exc}"], None

    if issues:
        return False, issues, None
    # Final determinism sanity: exactly 4 known IDs per block task.
    for tid in block_task_ids:
        pool = set(_task_candidate_ids(schedule, tid))
        s = selections.get(tid, [])
        if len(s) != SELECTION_BUDGET or len(set(s)) != SELECTION_BUDGET or any(i not in pool for i in s):
            return False, [f"{tid}: non-deterministic or invalid final selection"], None
    return True, [], selections


# ---------------------------------------------------------------------------
# Receiver scoring against the sealed truth
# ---------------------------------------------------------------------------

def score_selections(
    selections: dict[str, list[str]], truth: dict
) -> dict[str, Any]:
    """Score ordered selections against the sealed truth.

    Original LIVE-002 semantics: task success iff an acceptable candidate
    appears in the selected four; evaluations-to-first-success is its ordered
    position (1-based). No proxy metric involved.
    """
    per_task: dict[str, dict[str, Any]] = {}
    successes = 0
    total_evals_to_first = 0
    for tid, ordered in selections.items():
        accepted = truth["tasks"][tid]["accepted"]
        first = None
        for i, cid in enumerate(ordered, 1):
            entry = accepted.get(cid)
            # Sealed truth stores a per-candidate record; acceptance is its
            # "accepted" boolean. (A bare bool is also tolerated.)
            is_acceptable = entry.get("accepted") is True if isinstance(entry, dict) else bool(entry)
            if is_acceptable:
                first = i
                break
        found = first is not None
        if found:
            successes += 1
            total_evals_to_first += first
        per_task[tid] = {
            "ordered_selection": list(ordered),
            "found_acceptable": found,
            "evaluations_to_first_success": first,
            "evaluations_used": first if found else SELECTION_BUDGET,
        }
    return {
        "per_task": per_task,
        "task_successes": successes,
        "total_evaluations_to_first_success": total_evals_to_first,
    }


def promotion_decision(
    method_score: dict[str, Any], head_score: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Apply the frozen promotion rule.

    PROMOTE iff the method loses no receiver-confirmed task success relative
    to the head on this block AND (gains >= 1 task success OR preserves all
    successes while reducing total evaluations-to-first-success).
    """
    m_tasks = method_score["per_task"]
    h_tasks = head_score["per_task"]
    lost = sorted(
        tid for tid, h in h_tasks.items()
        if h["found_acceptable"] and not m_tasks[tid]["found_acceptable"]
    )
    detail = {
        "method_task_successes": method_score["task_successes"],
        "head_task_successes": head_score["task_successes"],
        "method_total_evals_to_first_success": method_score["total_evaluations_to_first_success"],
        "head_total_evals_to_first_success": head_score["total_evaluations_to_first_success"],
        "lost_task_successes": lost,
    }
    if lost:
        return "REJECT", detail
    m, h = method_score["task_successes"], head_score["task_successes"]
    if m > h:
        detail["reason"] = "gained_task_success"
        return "PROMOTE", detail
    if m == h and method_score["total_evaluations_to_first_success"] < head_score["total_evaluations_to_first_success"]:
        detail["reason"] = "preserved_successes_reduced_evaluations"
        return "PROMOTE", detail
    detail["reason"] = "no_gain_no_evaluation_reduction"
    return "REJECT", detail


# ---------------------------------------------------------------------------
# Sealed artifact verification
# ---------------------------------------------------------------------------

def verify_isolation_lineage(root: Path) -> dict[str, Any]:
    """Verify the frozen RIL-API-ISOLATION-002 binding.

    Fails unless the isolation receipt exists at its frozen path, its SHA-256
    matches the frozen value, and every call record's provider-returned model
    identifier is exactly gpt-6-astra. Returns a summary of the check.
    """
    receipt_path = root / ISOLATION_002_RECEIPT
    if not receipt_path.exists():
        raise RuntimeError(f"isolation receipt missing: {receipt_path}")
    actual = sha256_bytes(receipt_path.read_bytes())
    if actual != ISOLATION_002_RECEIPT_SHA256:
        raise RuntimeError(
            f"isolation receipt hash mismatch: got {actual}, "
            f"need {ISOLATION_002_RECEIPT_SHA256}"
        )
    receipt = read_json(receipt_path)
    models: list[str] = []
    for pair in receipt.get("pairs", []):
        for side in ("exposure", "blind"):
            rec = pair.get(side, {})
            models.append(str(rec.get("model", "")))
    if len(models) != 4:
        raise RuntimeError(f"isolation receipt holds {len(models)} call records, need 4")
    if any(m != MODEL_ID for m in models):
        raise RuntimeError(f"isolation model lineage not exactly {MODEL_ID}: {models}")
    return {
        "receipt_path": ISOLATION_002_RECEIPT,
        "receipt_sha256": actual,
        "frozen_commit": ISOLATION_002_COMMIT,
        "call_records": len(models),
        "provider_returned_models": models,
    }


def check_truth_shape(truth: dict, schedule: dict) -> int:
    """Enforce the sealed truth-table invariants. Returns evaluation count.

    Hard invariant: exactly 16 tasks x 12 candidates = 192 evaluations, and
    the four round blocks must partition the 16 tasks with one task per
    family per block. Raises RuntimeError on any violation.
    """
    if truth.get("schema") != SCHEMA_TRUTH:
        raise RuntimeError("truth table schema mismatch")
    if schedule.get("schema") != SCHEMA_SCHEDULE:
        raise RuntimeError("schedule schema mismatch")
    if len(truth["tasks"]) != 16:
        raise RuntimeError("truth table must cover 16 tasks")
    total_evals = 0
    for tid, t in truth["tasks"].items():
        if len(t.get("accepted", {})) != 12:
            raise RuntimeError(f"truth table task {tid} lacks 12 candidates")
        total_evals += len(t["accepted"])
    if total_evals != 192:
        raise RuntimeError(f"truth table holds {total_evals} evaluations, need exactly 192")
    blocks = schedule["round_blocks"]
    seen: list[str] = []
    for r in ("1", "2", "3", "4"):
        b = blocks[r]
        if len(b) != 4 or len({schedule["tasks"][t]["family"] for t in b}) != 4:
            raise RuntimeError(f"round block {r} must hold one task per family")
        seen.extend(b)
    if sorted(seen) != sorted(truth["tasks"].keys()):
        raise RuntimeError("round blocks must partition the 16 truth tasks")
    return total_evals


def verify_sealed_artifacts(root: Path, prereg: dict) -> tuple[dict, dict]:
    """Load truth table + schedule, verifying sha256 against preregistration."""
    seal_dir = root / SEAL_DIRNAME
    truth_path = seal_dir / TRUTH_FILENAME
    sched_path = seal_dir / SCHEDULE_FILENAME
    expected = prereg.get("sealed_artifacts", {})
    for path, key in ((truth_path, "truth_table_sha256"), (sched_path, "schedule_sha256")):
        if not path.exists():
            raise RuntimeError(f"sealed artifact missing: {path}")
        actual = sha256_bytes(path.read_bytes())
        if expected.get(key) != actual:
            raise RuntimeError(f"sealed artifact hash mismatch: {path.name}")
    truth = read_json(truth_path)
    schedule = read_json(sched_path)
    check_truth_shape(truth, schedule)
    return truth, schedule


# ---------------------------------------------------------------------------
# Public packet building (GPT sees this; the truth table never enters it)
# ---------------------------------------------------------------------------

FROZEN_FAILURE_EVIDENCE = (
    "The historical researcher investigated these 16 frozen tasks in two "
    "separately presented sessions. In both sessions it reconstructed the "
    "same exact four-candidate evaluation order on all 16 tasks, ignoring "
    "candidate presentation order. The receiver independently executed the "
    "selected candidates and confirmed improvement on 1 of the 16 tasks in "
    "each session. The same behavior with different presentation is the "
    "unresolved failure under investigation: the researcher's selection "
    "strategy did not respond to the only thing that changed."
)

RESPONSE_CONTRACT = {
    "type": "object",
    "required": ["experiment", "arm", "round", "investigation", "rule", "proposed_lesson"],
    "properties": {
        "experiment": {"const": EXPERIMENT},
        "arm": {"enum": list(ARMS)},
        "round": {"type": "integer", "minimum": 1, "maximum": 4},
        "investigation": {"type": "string", "minLength": 1},
        "rule": {
            "type": "object",
            "required": ["type"],
            "properties": {"type": {"enum": list(RULE_TYPES)}},
        },
        "proposed_lesson": {"type": "string", "minLength": 1},
    },
}


def build_packet(
    arm: str,
    round_no: int,
    schedule: dict,
    head_state: dict,
    arm_history: dict,
    public_contexts: dict[str, dict],
    candidate_public: dict[str, dict[str, dict]],
) -> dict:
    """Build one round's public packet. Contains zero hidden-truth bytes."""
    block = schedule["round_blocks"][str(round_no)]
    tasks = []
    for tid in block:
        presented = schedule["tasks"][tid]["presented_order"]
        pool = [
            {
                "presentation_position": i + 1,
                "candidate_id": cid,
                "description": candidate_public[tid][cid]["description"],
                "features": candidate_public[tid][cid]["features"],
            }
            for i, cid in enumerate(presented)
        ]
        tasks.append(
            {
                "task_id": tid,
                "family": schedule["tasks"][tid]["family"],
                "task_public_context": public_contexts[tid],
                "candidate_pool_in_presented_order": pool,
                "current_accepted_head_ordered_selection": head_state["per_block"][str(round_no)][tid],
                "instruction": (
                    f"Propose a deterministic method that selects and orders exactly "
                    f"{SELECTION_BUDGET} unique candidate IDs for EACH of this block's "
                    f"{len(block)} tasks, using only the public candidate "
                    f"features/descriptions. Return it as 'rule'."
                ),
            }
        )
    return {
        "schema": "openline.ril-anomaly-003.round-packet.v1",
        "experiment": EXPERIMENT,
        "arm": arm,
        "round": round_no,
        "model_binding": {
            "pinned_model_id": MODEL_ID,
            "bound_to": "provider-returned model identifier in all four "
                        + ISOLATION_002_RECEIPT
                        + " call records",
        },
        "frozen_failure_evidence": FROZEN_FAILURE_EVIDENCE,
        "arm_history": arm_history,
        "tasks": tasks,
        "response_contract": RESPONSE_CONTRACT,
        "rules": {
            "fresh_independent_request": True,
            "no_other_arm_information": True,
            "hidden_truth_never_disclosed": True,
            "non_executable_rule_quarantines_round": True,
        },
    }


def assert_no_truth_leakage(packet: dict) -> None:
    """Fail if any hidden-truth-shaped content appears in a public packet."""
    blob = json.dumps(packet)
    if '"accepted"' in blob or "evaluations_to_first_success" in blob:
        raise RuntimeError("truth leakage: acceptance data in public packet")
    for t in packet["tasks"]:
        for c in t["candidate_pool_in_presented_order"]:
            allowed = {"presentation_position", "candidate_id", "description", "features"}
            if set(c.keys()) - allowed:
                raise RuntimeError("unexpected candidate field in packet")


def computed_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens / 1_000_000 * PRICE_INPUT_PER_1M + completion_tokens / 1_000_000 * PRICE_OUTPUT_PER_1M
