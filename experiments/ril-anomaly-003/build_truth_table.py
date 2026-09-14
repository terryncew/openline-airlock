#!/usr/bin/env python3
"""RIL-ANOMALY-003 one-time build: receiver truth table + fresh schedule.

Runs ONCE, locally, before any primary API contact. It:

1. Loads the frozen RIL-RANK-EXEC-001 engine (sha-verified) and the frozen
   RIL-RANK-LIVE-002 receiver artifacts (ordering seal, receiver map, rows).
2. Executes ALL 12 candidates of every one of the 16 tasks through the
   receiver's evaluate_candidate (192 local evaluations), EXACTLY ONCE.
   Determinism is established by the frozen engine (sha-pinned, pure function
   of the frozen task data nonce — no unseeded randomness) plus the
   cross-validation below.
3. Cross-validates the truth table against the frozen record: scoring the
   historical selections against the new truth must reproduce all 32 frozen
   receiver_results exactly (0 mismatches tolerated).
4. Generates a FRESH matched schedule over the same 16 frozen tasks. Scope
   decision (2026-09-14): the seed anomaly is defined over these 16 frozen
   tasks, the preregistered initial accepted head is the frozen historical
   selection on these tasks, and the 32/32 cross-validation requires them —
   so "fresh" applies to the schedule, not the task data. A seeded shuffle
   assigns each family's 4 tasks across the 4 round blocks (one task per
   family per round), and a seeded shuffle sets each task's candidate
   presentation order. Same schedule for both arms.
5. Writes proofs/ril-anomaly-003/{TRUTH_TABLE,SCHEDULE,SEAL}.json and refuses
   to overwrite them (the seal is single-write).

No network, no API, no credentials. The sealed truth is committed BEFORE the
first primary GPT call; its sha256 is pinned in the preregistration.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import importlib.util
import json
import secrets
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "protected"))
import anomaly_core as core  # noqa: E402

# Frozen predecessor references (must match the rank-live-002 freeze).
ENGINE_PATH = ROOT / "experiments/ril-rank-exec-001/run_ril_rank_exec_001.py"
ENGINE_SHA256 = "bd350e1144068d10e9354ccec4a67de42810658f0ea9303899bc741f980c060a"
SEAL_PATH = ROOT / "proofs/ril-rank-live-002/RIL_RANK_LIVE_002_ORDERING_SEAL.json"
SEAL_SHA256 = "9538249118d485965dc572d1a5dbd400a93aaa5a0d8985a3de102138fa668fba"
RMAP_PATH = ROOT / "proofs/ril-rank-live-002/RIL_RANK_LIVE_002_RECEIVER_MAP.json"
ROWS_PATH = ROOT / "proofs/ril-rank-live-002/RIL_RANK_LIVE_002_MATCHED_LIVE_ROWS.json"

OUT_DIR = ROOT / core.SEAL_DIRNAME
FAMILIES = ("dedupe-stream", "normalized-join", "sliding-window", "transient-fetch")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class SeededRNG:
    """Deterministic RNG from a hex seed (HMAC-SHA256 counter stream)."""

    def __init__(self, seed_hex: str, label: str):
        self._key = bytes.fromhex(seed_hex)
        self._label = label.encode()
        self._counter = 0

    def _bytes(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            out += hmac.new(
                self._key, self._label + self._counter.to_bytes(8, "big"), hashlib.sha256
            ).digest()
            self._counter += 1
        return out[:n]

    def randbelow(self, n: int) -> int:
        if n <= 0:
            raise ValueError("randbelow requires n > 0")
        return int.from_bytes(self._bytes(8), "big") % n

    def shuffle(self, xs: list) -> list:
        xs = list(xs)
        for i in range(len(xs) - 1, 0, -1):
            j = self.randbelow(i + 1)
            xs[i], xs[j] = xs[j], xs[i]
        return xs


def load_engine():
    if sha256_file(ENGINE_PATH) != ENGINE_SHA256:
        raise SystemExit("frozen engine sha256 mismatch — refusing to build truth table")
    spec = importlib.util.spec_from_file_location("ril_rank_exec_001_frozen_engine", str(ENGINE_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def task_public_context(family: str, task: dict[str, Any]) -> dict[str, Any]:
    # Same public projection the rank-live-002 packet used (public only).
    if family == "dedupe-stream":
        values = list(task["values"])
        return {"family": family, "input_count": len(values), "sample": values[:8],
                "receiver_hint": task.get("hint_mode"), "derived_signal": bool(task.get("derived_signal")),
                "goal": "preserve first-occurrence dedupe semantics while reducing counted operations"}
    if family == "normalized-join":
        left, right = list(task["left"]), list(task["right"])
        return {"family": family, "left_count": len(left), "right_count": len(right),
                "left_key_sample": [x[0] for x in left[:5]], "right_key_sample": [x[0] for x in right[:5]],
                "receiver_hint": task.get("hint_mode"), "derived_signal": bool(task.get("derived_signal")),
                "goal": "preserve normalized join semantics while reducing counted operations"}
    if family == "sliding-window":
        events, queries = list(task["events"]), list(task["queries"])
        return {"family": family, "event_count": len(events), "query_count": len(queries),
                "event_sample": events[:10], "query_sample": queries[:5],
                "receiver_hint": task.get("hint_mode"), "derived_signal": bool(task.get("derived_signal")),
                "goal": "preserve window counts while reducing counted operations"}
    if family == "transient-fetch":
        req = list(task["requests"])
        fails = dict(task["fail_counts"])
        return {"family": family, "request_count": len(req), "unique_keys": len(set(req)),
                "request_sample": req[:10],
                "observed_failure_count_sample": {k: fails[k] for k in sorted(fails)[:5]},
                "receiver_hint": task.get("hint_mode"), "derived_signal": bool(task.get("derived_signal")),
                "goal": "preserve successful fetch results while reducing counted operations"}
    raise ValueError(family)


def candidate_description(c: dict[str, Any]) -> str:
    f = c["features"]
    return f"strategy={f['strategy']}; scope={f['scope']}; evidence={f['evidence']}; complexity={f['complexity']}"


def build_truth(engine, seal_tasks: dict, data_nonce: str) -> dict[str, Any]:
    """Run all 12 candidates of all 16 tasks through the receiver (192 evals)."""
    tasks: dict[str, Any] = {}
    for tid, item in seal_tasks.items():
        task = engine.make_task(item["family"], item["task_index"], data_nonce)
        by = {c["candidate_id"]: c for c in item["candidates"]}
        if len(by) != 12:
            raise SystemExit(f"{tid}: expected 12 candidates, got {len(by)}")
        accepted: dict[str, dict[str, Any]] = {}
        for cid, c in by.items():
            o = engine.evaluate_candidate(item["family"], task, c)
            accepted[cid] = {
                "accepted": bool(o["accepted"]),
                "correct": bool(o["correct"]),
                "operations": o["operations"],
                "baseline_operations": o["baseline_operations"],
                "operation_ratio": o["operation_ratio"],
                "gain": o["gain"],
                "reason": o["reason"],
            }
        tasks[tid] = {"family": item["family"], "accepted": accepted}
    return {"schema": core.SCHEMA_TRUTH, "experiment": core.EXPERIMENT, "tasks": tasks}


def cross_validate(engine, truth: dict, rows: list[dict], seal_tasks: dict) -> tuple[int, int]:
    """Reproduce every frozen row receiver_result from the new truth table."""
    checked = 0
    mismatches = 0
    keys = ("found_acceptable", "evaluations_to_first_acceptable", "evaluations_used",
            "censored_evaluations_to_first_acceptable", "best_gain_seen")
    outcomes_cache: dict[str, dict] = {}
    for row in rows:
        tid = row["task_id"]
        if tid not in outcomes_cache:
            item = seal_tasks[tid]
            outcomes_cache[tid] = {
                cid: {"accepted": truth["tasks"][tid]["accepted"][cid]["accepted"],
                      "gain": truth["tasks"][tid]["accepted"][cid]["gain"]}
                for cid in truth["tasks"][tid]["accepted"]
            }
        rr = engine.score_order(row["prince_selected_order"], outcomes_cache[tid], 4)
        checked += 1
        for k in keys:
            if rr[k] != row["receiver_result"][k]:
                mismatches += 1
    return checked, mismatches


def build_schedule(
    seed_hex: str, seal_tasks: dict, rows: list[dict], public_contexts: dict, candidate_public: dict
) -> dict[str, Any]:
    rng = SeededRNG(seed_hex, "ril-anomaly-003-schedule")
    # Historical selections: identical in both frozen sessions; assert it.
    hist: dict[str, list[str]] = {}
    for row in rows:
        tid = row["task_id"]
        sel = list(row["prince_selected_order"])
        if tid in hist:
            assert hist[tid] == sel, f"historical selection differs across sessions for {tid}"
        hist[tid] = sel
    # Fresh round-block assignment: shuffle each family's 4 tasks across rounds.
    by_family: dict[str, list[str]] = {f: [] for f in FAMILIES}
    for tid, item in seal_tasks.items():
        by_family[item["family"]].append(tid)
    for f in FAMILIES:
        assert len(by_family[f]) == 4, f
        by_family[f] = rng.shuffle(sorted(by_family[f]))
    round_blocks = {str(r): [by_family[f][r - 1] for f in FAMILIES] for r in (1, 2, 3, 4)}
    # Fresh presentation order per task.
    tasks: dict[str, Any] = {}
    for tid, item in seal_tasks.items():
        cids = [c["candidate_id"] for c in item["candidates"]]
        presented = rng.shuffle(cids)
        block = next(r for r in ("1", "2", "3", "4") if tid in round_blocks[r])
        tasks[tid] = {
            "family": item["family"],
            "round_block": block,
            "presented_order": presented,
            "historical_selected_order": hist[tid],
            "public_context": public_contexts[tid],
            "candidates_public": candidate_public[tid],
        }
    return {
        "schema": core.SCHEMA_SCHEDULE,
        "experiment": core.EXPERIMENT,
        "seed_hex": seed_hex,
        "round_blocks": round_blocks,
        "tasks": tasks,
    }


def main() -> int:
    # Hard invariant: a second truth-build under the same experiment ID is
    # forbidden, even if the sealed files were deleted from disk. The seal
    # lives in git history; its presence there refuses any rebuild.
    import subprocess
    try:
        logged = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--format=%H", "--", core.SEAL_DIRNAME],
            capture_output=True, text=True, timeout=30,
        )
        if logged.returncode == 0 and logged.stdout.strip():
            raise SystemExit(
                "refusing second truth-build: a sealed truth table already exists "
                f"under {core.EXPERIMENT} in git history ({logged.stdout.strip().splitlines()[0][:12]}...). "
                "Redesign requires a new experiment ID."
            )
    except FileNotFoundError:
        pass  # git unavailable; fall through to the file-existence guard
    for p, expected in ((SEAL_PATH, SEAL_SHA256),):
        if sha256_file(p) != expected:
            raise SystemExit(f"frozen input hash mismatch: {p}")
    for name in (core.TRUTH_FILENAME, core.SCHEDULE_FILENAME, core.SEAL_FILENAME):
        if (OUT_DIR / name).exists():
            raise SystemExit(f"refusing to overwrite sealed artifact: {name} (single-write seal)")

    engine = load_engine()
    seal = json.loads(SEAL_PATH.read_text())
    rmap = json.loads(RMAP_PATH.read_text())
    rows = json.loads(ROWS_PATH.read_text())
    data_nonce = rmap["task_data_nonce"]
    seal_tasks = {t["task_id"]: t for t in seal["tasks"]}
    if len(seal_tasks) != 16:
        raise SystemExit("expected 16 sealed tasks")

    # Public projections (what GPT may see).
    public_contexts: dict[str, dict] = {}
    candidate_public: dict[str, dict[str, dict]] = {}
    for tid, item in seal_tasks.items():
        task = engine.make_task(item["family"], item["task_index"], data_nonce)
        public_contexts[tid] = task_public_context(item["family"], task)
        candidate_public[tid] = {
            c["candidate_id"]: {"description": candidate_description(c), "features": dict(c["features"])}
            for c in item["candidates"]
        }

    # 1) Truth table, built EXACTLY ONCE (192 evaluations, no more).
    truth_a = build_truth(engine, seal_tasks, data_nonce)
    n_evals = sum(len(t["accepted"]) for t in truth_a["tasks"].values())
    assert n_evals == 192, n_evals

    # 2) Cross-validate against the frozen 32-row receiver record.
    checked, mismatches = cross_validate(engine, truth_a, rows, seal_tasks)
    if mismatches:
        raise SystemExit(f"truth table cross-validation failed: {mismatches} mismatches")

    # 3) Fresh matched schedule.
    seed_hex = secrets.token_hex(16)
    schedule = build_schedule(seed_hex, seal_tasks, rows, public_contexts, candidate_public)

    truth_sha = core.write_json(OUT_DIR / core.TRUTH_FILENAME, truth_a)
    sched_sha = core.write_json(OUT_DIR / core.SCHEDULE_FILENAME, schedule)
    seal_obj = {
        "schema": core.SCHEMA_SEAL,
        "experiment": core.EXPERIMENT,
        "built_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "builder": "Muse (Prince) — local build, no API contact",
        "truth_table_sha256": truth_sha,
        "schedule_sha256": sched_sha,
        "schedule_seed_hex": seed_hex,
        "receiver_evaluations": n_evals,
        "determinism_check": {"runs": 1, "basis": "frozen sha-pinned engine, pure function of the frozen task data nonce (no unseeded randomness), plus 32/32 cross-validation against frozen receiver rows"},
        "cross_validation": {"frozen_rows_checked": checked, "mismatches": mismatches},
        "inputs": {
            "engine_runner_sha256": ENGINE_SHA256,
            "ordering_seal_sha256": SEAL_SHA256,
            "receiver_map_sha256": sha256_file(RMAP_PATH),
            "matched_rows_sha256": sha256_file(ROWS_PATH),
            "task_data_nonce": data_nonce,
        },
        "note": "Sealed BEFORE the first RIL-ANOMALY-003 primary API request. "
                "The hidden truth (per-candidate acceptance) is never placed in a GPT packet.",
    }
    seal_sha = core.write_json(OUT_DIR / core.SEAL_FILENAME, seal_obj)
    print(f"truth table : {OUT_DIR / core.TRUTH_FILENAME}  sha256={truth_sha}")
    print(f"schedule    : {OUT_DIR / core.SCHEDULE_FILENAME}  sha256={sched_sha}")
    print(f"seal        : {OUT_DIR / core.SEAL_FILENAME}  sha256={seal_sha}")
    print(f"evaluations : {n_evals} (192 = 16 tasks x 12 candidates)")
    print(f"cross-check : {checked} frozen rows reproduced, {mismatches} mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
