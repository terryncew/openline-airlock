#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import random
import secrets
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

EXPERIMENT = "RIL-RANK-001"
SCHEMA = "openline.ril-rank-001.result.v1"
BASELINE_ORDER_SEED = "ril-rank-001-baseline-order-v1"
CALIBRATION_FAMILIES = ("parsing", "state-transition", "aggregation", "validation")
HOLDOUT_FAMILIES = ("caching", "pagination", "retry", "schema-migration")
FEATURE_SPACE = {
    "strategy": ("guard", "normalize", "reorder", "cache", "retry", "vectorize"),
    "scope": ("narrow", "medium", "broad"),
    "evidence": ("direct", "derived", "speculative"),
    "complexity": ("low", "medium", "high"),
}
CANDIDATES_PER_TASK = 12
CALIBRATION_TASKS_PER_FAMILY = 16
HOLDOUT_TASKS_PER_FAMILY = 24
EVALUATION_BUDGET = 4
ACCEPT_GAIN = 2.20
MIN_PRIMARY_ADVANTAGE = 0.08
GLOBAL_EFFECT_STD = 0.80
FAMILY_EFFECT_STD = 1.00
TASK_BIAS_STD = 0.50
CANDIDATE_NOISE_STD = 0.30
LAPLACE_ALPHA = 1.0
LAPLACE_BETA = 3.0
MINIMUM_ANCESTOR = "79c3dbfb4ec3f844c15552720db5480acc311510"

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PREREG_PATH = HERE / "RIL_RANK_001_PREREGISTRATION.json"


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fsync_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    with path.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    return sha256_bytes(payload.encode("utf-8"))


def _digest(key_hex: str, *parts: Any) -> bytes:
    key = bytes.fromhex(key_hex)
    msg = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).digest()


def uniform01(key_hex: str, *parts: Any) -> float:
    d = _digest(key_hex, *parts)
    n = int.from_bytes(d[:8], "big")
    return (n + 0.5) / (2**64)


def normal01(key_hex: str, *parts: Any) -> float:
    # Deterministic Box-Muller; clamp away from exact zero.
    u1 = max(uniform01(key_hex, *parts, "u1"), 1e-15)
    u2 = uniform01(key_hex, *parts, "u2")
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)


def candidate_id(features: dict[str, str]) -> str:
    return sha256_bytes(canonical_bytes(features))[:16]


def generate_candidates(candidate_nonce: str, family: str, task_index: int) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    draw = 0
    while len(candidates) < CANDIDATES_PER_TASK:
        features: dict[str, str] = {}
        for feature_name, values in FEATURE_SPACE.items():
            d = _digest(candidate_nonce, family, task_index, draw, feature_name)
            features[feature_name] = values[int.from_bytes(d[:4], "big") % len(values)]
        cid = candidate_id(features)
        candidates.setdefault(cid, {"candidate_id": cid, "features": features})
        draw += 1
        if draw > 10000:
            raise RuntimeError("candidate generation failed to produce enough unique candidates")
    return sorted(candidates.values(), key=lambda c: c["candidate_id"])


def global_effect(world_nonce: str, feature: str, value: str) -> float:
    return GLOBAL_EFFECT_STD * normal01(world_nonce, "global", feature, value)


def family_effect(outcome_nonce: str, family: str, feature: str, value: str) -> float:
    return FAMILY_EFFECT_STD * normal01(outcome_nonce, "family", family, feature, value)


def evaluate_candidate(
    *,
    world_nonce: str,
    outcome_nonce: str,
    family: str,
    task_index: int,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    gain = 0.0
    for feature, value in candidate["features"].items():
        gain += global_effect(world_nonce, feature, value)
        gain += family_effect(outcome_nonce, family, feature, value)
    gain += TASK_BIAS_STD * normal01(outcome_nonce, "task", family, task_index)
    gain += CANDIDATE_NOISE_STD * normal01(
        outcome_nonce, "candidate", family, task_index, candidate["candidate_id"]
    )
    accepted = gain >= ACCEPT_GAIN
    if accepted:
        reason = "OBJECTIVE_CLEARED"
    elif gain < 0:
        reason = "REGRESSIVE"
    else:
        reason = "MINIMUM_GAIN_NOT_CLEARED"
    return {
        "candidate_id": candidate["candidate_id"],
        "features": candidate["features"],
        "gain": round(gain, 12),
        "accepted": accepted,
        "reason": reason,
    }


def evaluate_family_tasks(
    *,
    families: Iterable[str],
    tasks_per_family: int,
    candidate_nonce: str,
    world_nonce: str,
    outcome_nonce: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family in families:
        for task_index in range(tasks_per_family):
            task_id = f"{family}-{task_index:03d}"
            for candidate in generate_candidates(candidate_nonce, family, task_index):
                row = evaluate_candidate(
                    world_nonce=world_nonce,
                    outcome_nonce=outcome_nonce,
                    family=family,
                    task_index=task_index,
                    candidate=candidate,
                )
                row["family"] = family
                row["task_index"] = task_index
                row["task_id"] = task_id
                rows.append(row)
    return rows


def build_rank_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        accepted = 1 if row["accepted"] else 0
        for feature, value in row["features"].items():
            key = (feature, value)
            stats[key][0] += accepted
            stats[key][1] += 1
    atoms: dict[str, Any] = {}
    for feature, values in FEATURE_SPACE.items():
        for value in values:
            successes, total = stats[(feature, value)]
            p = (successes + LAPLACE_ALPHA) / (total + LAPLACE_ALPHA + LAPLACE_BETA)
            log_odds = math.log(p / (1.0 - p))
            atoms[f"{feature}={value}"] = {
                "successes": successes,
                "total": total,
                "smoothed_success_rate": p,
                "log_odds": log_odds,
            }
    return {"atoms": atoms, "alpha": LAPLACE_ALPHA, "beta": LAPLACE_BETA}


def rank_score(model: dict[str, Any], candidate: dict[str, Any]) -> float:
    total = 0.0
    for feature, value in candidate["features"].items():
        total += model["atoms"][f"{feature}={value}"]["log_odds"]
    return total


def learned_order(model: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    ranked = sorted(candidates, key=lambda c: (-rank_score(model, c), c["candidate_id"]))
    return [c["candidate_id"] for c in ranked]


def baseline_order(task_id: str, candidates: list[dict[str, Any]]) -> list[str]:
    def key(c: dict[str, Any]) -> tuple[str, str]:
        digest = hashlib.sha256(
            f"{BASELINE_ORDER_SEED}|{task_id}|{c['candidate_id']}".encode("utf-8")
        ).hexdigest()
        return digest, c["candidate_id"]
    return [c["candidate_id"] for c in sorted(candidates, key=key)]


def shuffled_history(rows: list[dict[str, Any]], shuffle_nonce: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["task_id"]].append(row)
    out: list[dict[str, Any]] = []
    for task_id in sorted(grouped):
        task_rows = sorted(grouped[task_id], key=lambda r: r["candidate_id"])
        outcomes = [
            {"accepted": r["accepted"], "gain": r["gain"], "reason": r["reason"]}
            for r in task_rows
        ]
        seed = int.from_bytes(_digest(shuffle_nonce, "shuffle", task_id)[:8], "big")
        rng = random.Random(seed)
        rng.shuffle(outcomes)
        for row, outcome in zip(task_rows, outcomes):
            clone = dict(row)
            clone.update(outcome)
            out.append(clone)
    return out


def group_outcomes(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[row["task_id"]][row["candidate_id"]] = row
    return grouped


def score_order(order: list[str], outcomes: dict[str, dict[str, Any]], budget: int) -> dict[str, Any]:
    seen = order[:budget]
    first: int | None = None
    best_gain = -math.inf
    for index, cid in enumerate(seen, start=1):
        row = outcomes[cid]
        best_gain = max(best_gain, float(row["gain"]))
        if first is None and row["accepted"]:
            first = index
            break
    evaluations_used = first if first is not None else budget
    if best_gain == -math.inf:
        raise RuntimeError("empty evaluated set")
    global_best = max(float(r["gain"]) for r in outcomes.values())
    return {
        "found_acceptable": first is not None,
        "evaluations_to_first_acceptable": first,
        "evaluations_used": evaluations_used,
        "censored_evaluations_to_first_acceptable": first if first is not None else budget + 1,
        "best_gain_seen": best_gain,
        "global_best_gain": global_best,
        "regret": global_best - best_gain,
    }


def summarize_method(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    n = len(rows)
    found = sum(1 for r in rows if r[method]["found_acceptable"])
    by_family: dict[str, Any] = {}
    for family in HOLDOUT_FAMILIES:
        fr = [r for r in rows if r["family"] == family]
        ffound = sum(1 for r in fr if r[method]["found_acceptable"])
        by_family[family] = {
            "tasks": len(fr),
            "found_within_budget": ffound,
            "found_within_budget_rate": ffound / len(fr),
            "mean_evaluations_used": statistics.fmean(r[method]["evaluations_used"] for r in fr),
        }
    firsts = [r[method]["evaluations_to_first_acceptable"] for r in rows]
    wins_firsts = [x for x in firsts if x is not None]
    return {
        "tasks": n,
        "found_within_budget": found,
        "found_within_budget_rate": found / n,
        "evaluations_used_total": sum(r[method]["evaluations_used"] for r in rows),
        "mean_evaluations_used": statistics.fmean(r[method]["evaluations_used"] for r in rows),
        "mean_evaluations_to_first_win_among_wins": statistics.fmean(wins_firsts) if wins_firsts else None,
        "mean_censored_evaluations_to_first_win": statistics.fmean(
            r[method]["censored_evaluations_to_first_acceptable"] for r in rows
        ),
        "mean_best_gain_seen": statistics.fmean(r[method]["best_gain_seen"] for r in rows),
        "mean_regret": statistics.fmean(r[method]["regret"] for r in rows),
        "by_family": by_family,
    }


def classify(learned_rate: float, baseline_rate: float, shuffled_rate: float) -> str:
    beats_baseline = learned_rate - baseline_rate >= MIN_PRIMARY_ADVANTAGE
    beats_shuffled = learned_rate - shuffled_rate >= MIN_PRIMARY_ADVANTAGE
    if beats_baseline and beats_shuffled:
        return "PASS_RIL_RANK_001_HISTORY_RANKING_SIGNAL"
    if beats_baseline and not beats_shuffled:
        return "RANKING_ADVANTAGE_HISTORY_SIGNAL_NOT_ESTABLISHED"
    if beats_shuffled and not beats_baseline:
        return "HISTORY_SIGNAL_NO_BASELINE_ADVANTAGE"
    return "NO_PREDICTIVE_RANKING_ADVANTAGE"


def break_even(calibration_evaluations: int, savings_total: int, holdout_tasks: int) -> int | None:
    if savings_total <= 0:
        return None
    savings_per_task = savings_total / holdout_tasks
    return math.ceil(calibration_evaluations / savings_per_task)


def verify_frozen_files(prereg: dict[str, Any]) -> None:
    for rel, expected in prereg["frozen_files"].items():
        path = REPO_ROOT / rel
        if not path.exists():
            raise SystemExit(f"missing frozen file: {rel}")
        actual = sha256_file(path)
        if actual != expected:
            raise SystemExit(f"frozen hash mismatch: {rel}: {actual} != {expected}")


def self_check() -> None:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    assert prereg["experiment"] == EXPERIMENT
    assert prereg["primary_metric"]["evaluation_budget"] == EVALUATION_BUDGET
    assert prereg["primary_metric"]["min_rate_advantage_vs_each_control"] == MIN_PRIMARY_ADVANTAGE
    assert tuple(prereg["family_split"]["calibration_families"]) == CALIBRATION_FAMILIES
    assert tuple(prereg["family_split"]["holdout_families"]) == HOLDOUT_FAMILIES
    assert set(CALIBRATION_FAMILIES).isdisjoint(HOLDOUT_FAMILIES)
    verify_frozen_files(prereg)
    # Deterministic structural smoke with fixed nonces; not the primary.
    n = "01" * 32
    rows = evaluate_family_tasks(
        families=CALIBRATION_FAMILIES[:1],
        tasks_per_family=2,
        candidate_nonce=n,
        world_nonce="02" * 32,
        outcome_nonce="03" * 32,
    )
    model = build_rank_model(rows)
    candidates = generate_candidates("04" * 32, HOLDOUT_FAMILIES[0], 0)
    assert len(learned_order(model, candidates)) == CANDIDATES_PER_TASK
    shuffled = shuffled_history(rows, "05" * 32)
    assert len(shuffled) == len(rows)
    print("RIL-RANK-001 self-check: PASS")


def run(output: Path, evidence_dir: Path) -> dict[str, Any]:
    if output.exists() or evidence_dir.exists():
        raise SystemExit("refusing to reuse output/evidence path")
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    verify_frozen_files(prereg)
    evidence_dir.mkdir(parents=True, exist_ok=False)

    started = time.time()
    world_nonce = secrets.token_hex(32)
    calibration_candidate_nonce = secrets.token_hex(32)
    calibration_outcome_nonce = secrets.token_hex(32)

    t0 = time.perf_counter()
    calibration_rows = evaluate_family_tasks(
        families=CALIBRATION_FAMILIES,
        tasks_per_family=CALIBRATION_TASKS_PER_FAMILY,
        candidate_nonce=calibration_candidate_nonce,
        world_nonce=world_nonce,
        outcome_nonce=calibration_outcome_nonce,
    )
    calibration_seconds = time.perf_counter() - t0
    calibration_sha = fsync_json(evidence_dir / "calibration-evidence.json", calibration_rows)

    shuffle_nonce = secrets.token_hex(32)
    shuffled_rows = shuffled_history(calibration_rows, shuffle_nonce)
    # Preserve exact per-task label multiset under shuffle.
    for task_id in {r["task_id"] for r in calibration_rows}:
        original = sorted((r["accepted"], r["reason"], r["gain"]) for r in calibration_rows if r["task_id"] == task_id)
        shuffled = sorted((r["accepted"], r["reason"], r["gain"]) for r in shuffled_rows if r["task_id"] == task_id)
        if original != shuffled:
            raise RuntimeError(f"shuffle did not preserve outcome multiset for {task_id}")

    t1 = time.perf_counter()
    learned_model = build_rank_model(calibration_rows)
    shuffled_model = build_rank_model(shuffled_rows)
    ranking_seconds = time.perf_counter() - t1
    policy_seal = {
        "schema": "openline.ril-rank-001.policy-seal.v1",
        "experiment": EXPERIMENT,
        "calibration_evidence_sha256": calibration_sha,
        "calibration_rows": len(calibration_rows),
        "shuffle_nonce": shuffle_nonce,
        "learned_model": learned_model,
        "shuffled_model": shuffled_model,
        "baseline_order_seed": BASELINE_ORDER_SEED,
        "ranker_excludes_task_family_identity": True,
    }
    policy_seal_sha = fsync_json(evidence_dir / "policy-seal.json", policy_seal)

    # Holdout candidate descriptors are created only after policy seal.
    holdout_candidate_nonce = secrets.token_hex(32)
    holdout_tasks: list[dict[str, Any]] = []
    for family in HOLDOUT_FAMILIES:
        for task_index in range(HOLDOUT_TASKS_PER_FAMILY):
            task_id = f"{family}-{task_index:03d}"
            candidates = generate_candidates(holdout_candidate_nonce, family, task_index)
            holdout_tasks.append({
                "family": family,
                "task_index": task_index,
                "task_id": task_id,
                "candidates": candidates,
                "orders": {
                    "baseline": baseline_order(task_id, candidates),
                    "evidence": learned_order(learned_model, candidates),
                    "history_shuffled": learned_order(shuffled_model, candidates),
                },
            })
    ranking_seal = {
        "schema": "openline.ril-rank-001.holdout-ranking-seal.v1",
        "experiment": EXPERIMENT,
        "policy_seal_sha256": policy_seal_sha,
        "holdout_candidate_nonce": holdout_candidate_nonce,
        "tasks": holdout_tasks,
        "holdout_outcomes_exist_at_seal": False,
    }
    ranking_seal_sha = fsync_json(evidence_dir / "holdout-rankings-sealed-before-outcomes.json", ranking_seal)

    # Only after every holdout ordering is durably sealed does the receiver create outcomes.
    holdout_outcome_nonce = secrets.token_hex(32)
    t2 = time.perf_counter()
    holdout_outcome_rows = evaluate_family_tasks(
        families=HOLDOUT_FAMILIES,
        tasks_per_family=HOLDOUT_TASKS_PER_FAMILY,
        candidate_nonce=holdout_candidate_nonce,
        world_nonce=world_nonce,
        outcome_nonce=holdout_outcome_nonce,
    )
    holdout_eval_seconds = time.perf_counter() - t2
    holdout_outcomes_sha = fsync_json(evidence_dir / "holdout-outcomes.json", holdout_outcome_rows)
    grouped = group_outcomes(holdout_outcome_rows)

    scored_rows: list[dict[str, Any]] = []
    for task in holdout_tasks:
        outcomes = grouped[task["task_id"]]
        row = {"family": task["family"], "task_id": task["task_id"]}
        for method, order in task["orders"].items():
            row[method] = score_order(order, outcomes, EVALUATION_BUDGET)
        scored_rows.append(row)

    summaries = {
        "baseline": summarize_method(scored_rows, "baseline"),
        "evidence": summarize_method(scored_rows, "evidence"),
        "history_shuffled": summarize_method(scored_rows, "history_shuffled"),
    }
    learned_rate = summaries["evidence"]["found_within_budget_rate"]
    baseline_rate = summaries["baseline"]["found_within_budget_rate"]
    shuffled_rate = summaries["history_shuffled"]["found_within_budget_rate"]
    verdict = classify(learned_rate, baseline_rate, shuffled_rate)

    baseline_savings = summaries["baseline"]["evaluations_used_total"] - summaries["evidence"]["evaluations_used_total"]
    shuffled_savings = summaries["history_shuffled"]["evaluations_used_total"] - summaries["evidence"]["evaluations_used_total"]
    calibration_evaluations = len(calibration_rows)
    holdout_task_count = len(scored_rows)
    economic = {
        "learning_cost": {
            "calibration_evaluations": calibration_evaluations,
            "calibration_cpu_seconds": calibration_seconds,
            "learned_ranker_cpu_seconds": ranking_seconds,
            "conservative_rule": "All calibration evaluations count as incremental learning cost. History-shuffled control cost is experimental overhead, not production learning cost.",
        },
        "downstream": {
            "holdout_tasks": holdout_task_count,
            "evaluation_savings_vs_baseline": baseline_savings,
            "evaluation_savings_vs_history_shuffled": shuffled_savings,
            "mean_evaluation_savings_per_task_vs_baseline": baseline_savings / holdout_task_count,
            "mean_evaluation_savings_per_task_vs_history_shuffled": shuffled_savings / holdout_task_count,
            "holdout_outcome_generation_cpu_seconds": holdout_eval_seconds,
        },
        "break_even_future_tasks_vs_baseline": break_even(calibration_evaluations, baseline_savings, holdout_task_count),
        "standing": (
            "NO_DOWNSTREAM_EVALUATION_SAVINGS"
            if baseline_savings <= 0
            else (
                "LEARNING_COST_RECOVERED_WITHIN_HOLDOUT"
                if baseline_savings >= calibration_evaluations
                else "LEARNING_COST_NOT_RECOVERED_WITHIN_HOLDOUT"
            )
        ),
    }

    all_three_miss = sum(
        1 for r in scored_rows
        if not r["baseline"]["found_acceptable"]
        and not r["evidence"]["found_acceptable"]
        and not r["history_shuffled"]["found_acceptable"]
    )
    result = {
        "schema": SCHEMA,
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "scientific_standing": "CONTROLLED_SYNTHETIC_FAMILY_HELD_OUT_CALIBRATION",
        "level4_standing": "NOT_EARNED",
        "predecessor": prereg["predecessor"],
        "primary_metric": {
            "name": "acceptable_improvement_found_within_fixed_evaluation_budget",
            "evaluation_budget": EVALUATION_BUDGET,
            "min_rate_advantage_vs_each_control": MIN_PRIMARY_ADVANTAGE,
            "evidence_rate": learned_rate,
            "baseline_rate": baseline_rate,
            "history_shuffled_rate": shuffled_rate,
            "advantage_vs_baseline": learned_rate - baseline_rate,
            "advantage_vs_history_shuffled": learned_rate - shuffled_rate,
        },
        "methods": summaries,
        "misses": {
            "all_three_miss_tasks": all_three_miss,
            "tasks_total": holdout_task_count,
        },
        "economics": economic,
        "integrity": {
            "calibration_and_holdout_families_disjoint": set(CALIBRATION_FAMILIES).isdisjoint(HOLDOUT_FAMILIES),
            "family_identity_excluded_from_rank_model": True,
            "policy_sealed_before_holdout_candidate_generation": True,
            "all_holdout_orders_sealed_before_holdout_outcome_nonce": True,
            "history_shuffle_preserved_per_task_outcome_multisets": True,
            "same_candidate_pool_and_budget_all_methods": True,
            "holdout_outcome_feedback_returned_to_ranker": False,
        },
        "evidence": {
            "calibration_sha256": calibration_sha,
            "policy_seal_sha256": policy_seal_sha,
            "holdout_ranking_seal_sha256": ranking_seal_sha,
            "holdout_outcomes_sha256": holdout_outcomes_sha,
            "world_nonce": world_nonce,
            "calibration_candidate_nonce": calibration_candidate_nonce,
            "calibration_outcome_nonce": calibration_outcome_nonce,
            "holdout_outcome_nonce": holdout_outcome_nonce,
        },
        "rows": scored_rows,
        "claim_boundary": prereg["claim_boundary"],
        "started_unix": started,
        "completed_unix": time.time(),
    }
    fsync_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if args.output is None or args.evidence_dir is None:
        parser.error("--output and --evidence-dir are required for a primary run")
    result = run(args.output, args.evidence_dir)
    print(json.dumps({
        "verdict": result["verdict"],
        "primary_metric": result["primary_metric"],
        "economics": result["economics"],
        "misses": result["misses"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
