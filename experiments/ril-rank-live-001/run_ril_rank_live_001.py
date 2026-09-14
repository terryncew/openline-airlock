#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

EXPERIMENT = "RIL-RANK-LIVE-001"
SCHEMA = "openline.ril-rank-live-001.result.v1"
SCIENTIFIC_STANDING = "LIVE_AGENT_SELECTION_MATCHED_TRANSFER_SINGLE_RUN"
PREDECESSOR_MAIN = "2a808e764fe898f76dcb5025283eba98beafa3b1"
PREDECESSOR_FREEZE_BLOB = "ad893c75856b2f4518a5fb82b7fe8fb28f1dc769"
PREDECESSOR_RUNNER_SHA256 = "bd350e1144068d10e9354ccec4a67de42810658f0ea9303899bc741f980c060a"
POLICY_SEAL_SHA256 = "51e8bbf519d4c36e86081eb9cf33be3aaf1c065ae897798cf168f1fc1df4cc29"
HERMES_COMMIT = "afe06f21f45f476c25034c4529818d9a2f9fdf1c"
HERMES_MODEL = "gpt-5.6-sol"
HERMES_PROVIDER = "openai-api"
TASKS_PER_FAMILY = 4
EVALUATION_BUDGET = 4
MIN_RATE_ADVANTAGE = 0.125
INHERITED_LEARNING_COST_EVALUATIONS = 768
MAX_ITERATIONS = 2
MAX_OUTPUT_TOKENS = 768
MAX_REPORTED_TOTAL_TOKENS = 16000
MAX_ESTIMATED_USD_PER_CALL = Decimal("0.08")
MAX_ESTIMATED_USD_ALL_CALLS = Decimal("2.56")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREREG_PATH = HERE / "RIL_RANK_LIVE_001_PREREGISTRATION.json"
DRIVER_PATH = HERE / "protected" / "live_agent_driver.py"
PREDECESSOR_RUNNER = ROOT / "experiments" / "ril-rank-exec-001" / "run_ril_rank_exec_001.py"
POLICY_PATH = ROOT / "experiments" / "ril-rank-exec-001" / "frozen" / "RIL_RANK_001_POLICY_SEAL.json"
PREDECESSOR_FREEZE = ROOT / "proofs" / "ril-rank-exec-001" / "RIL_RANK_EXEC_001_FREEZE.json"

HISTORY_TEXT = (
    "Receiver history is identical in both arms. The candidate vocabulary is strategy, scope, evidence, and complexity. "
    "No candidate-specific outcome, terminal score, hidden oracle result, or task-family success table is disclosed to the live researcher. "
    "The inherited ranker's only treatment effect is the frozen ordering of the same candidate pool."
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_json(path: Path, value: Any, *, durable: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    with path.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        if durable:
            os.fsync(f.fileno())
    if durable:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return sha256_bytes(payload.encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sh(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    cp = subprocess.run(
        list(args), cwd=None if cwd is None else str(cwd), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr[-1200:]}")
    return cp.stdout.strip()


def git_available() -> bool:
    return shutil.which("git") is not None and (ROOT / ".git").exists()


def verify_git_lineage() -> None:
    if not git_available():
        return
    cp = subprocess.run(["git", "merge-base", "--is-ancestor", PREDECESSOR_MAIN, "HEAD"], cwd=ROOT)
    if cp.returncode != 0:
        raise RuntimeError(f"HEAD is not descended from frozen predecessor main {PREDECESSOR_MAIN}")
    blob = sh("git", "rev-parse", "HEAD:proofs/ril-rank-exec-001/RIL_RANK_EXEC_001_FREEZE.json", cwd=ROOT)
    if blob != PREDECESSOR_FREEZE_BLOB:
        raise RuntimeError(f"predecessor freeze blob changed: {blob} != {PREDECESSOR_FREEZE_BLOB}")


def verify_predecessor() -> None:
    if not PREDECESSOR_RUNNER.is_file() or sha256_file(PREDECESSOR_RUNNER) != PREDECESSOR_RUNNER_SHA256:
        raise RuntimeError("exact RIL-RANK-EXEC-001 executable engine is not present")
    if not POLICY_PATH.is_file() or sha256_file(POLICY_PATH) != POLICY_SEAL_SHA256:
        raise RuntimeError("exact frozen RIL-RANK-001 policy seal is not present")
    if not PREDECESSOR_FREEZE.is_file():
        raise RuntimeError("RIL-RANK-EXEC-001 freeze missing")
    freeze = read_json(PREDECESSOR_FREEZE)
    if freeze.get("formal_verdict") != "PASS_RIL_RANK_EXEC_001_EXECUTABLE_TRANSFER":
        raise RuntimeError("predecessor executable transfer did not pass")
    if freeze.get("live_agent_standing") != "NOT_TESTED" or freeze.get("level4_standing") != "NOT_EARNED":
        raise RuntimeError("predecessor claim boundary changed")
    if freeze.get("bindings", {}).get("frozen_predecessor_policy_seal_sha256") != POLICY_SEAL_SHA256:
        raise RuntimeError("predecessor freeze is not bound to the exact frozen policy seal")
    verify_git_lineage()


def load_exec_engine():
    verify_predecessor()
    spec = importlib.util.spec_from_file_location("ril_rank_exec_001_frozen_engine", PREDECESSOR_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load frozen executable engine")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def prereg() -> dict[str, Any]:
    value = read_json(PREREG_PATH)
    if value.get("schema") != "openline.ril-rank-live-001.preregistration.v1" or value.get("experiment") != EXPERIMENT:
        raise RuntimeError("unexpected preregistration")
    return value


def verify_frozen_files(value: dict[str, Any], *, require_committed: bool) -> dict[str, str]:
    observed: dict[str, str] = {}
    for rel, expected in value["frozen_files"].items():
        path = ROOT / rel
        if not path.is_file():
            raise RuntimeError(f"frozen file missing: {rel}")
        digest = sha256_file(path)
        if digest != expected:
            raise RuntimeError(f"frozen file hash mismatch: {rel}: {digest} != {expected}")
        observed[rel] = digest
    if require_committed and git_available():
        if sh("git", "status", "--porcelain", cwd=ROOT):
            raise RuntimeError("live primary requires a clean committed repository")
        for rel, expected in value["frozen_files"].items():
            cp = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if cp.returncode != 0 or sha256_bytes(cp.stdout) != expected:
                raise RuntimeError(f"frozen file is not committed unchanged: {rel}")
        rel = PREREG_PATH.relative_to(ROOT).as_posix()
        cp = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if cp.returncode != 0 or sha256_bytes(cp.stdout) != sha256_file(PREREG_PATH):
            raise RuntimeError("preregistration must itself be committed unchanged before live model contact")
    return observed


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
    return {}


def validate_live_order(parsed: dict[str, Any], shortlist: list[str]) -> tuple[bool, list[str]]:
    order = parsed.get("evaluation_order")
    if not isinstance(order, list) or len(order) != EVALUATION_BUDGET:
        return False, []
    if not all(isinstance(x, str) for x in order):
        return False, []
    if len(set(order)) != EVALUATION_BUDGET:
        return False, []
    if set(order) != set(shortlist):
        return False, []
    return True, list(order)


def task_public_context(family: str, task: dict[str, Any]) -> dict[str, Any]:
    if family == "dedupe-stream":
        values = list(task["values"])
        return {
            "family": family,
            "input_count": len(values),
            "sample": values[:8],
            "receiver_hint": task.get("hint_mode"),
            "derived_signal": bool(task.get("derived_signal")),
            "goal": "preserve first-occurrence dedupe semantics while reducing counted operations",
        }
    if family == "normalized-join":
        left, right = list(task["left"]), list(task["right"])
        return {
            "family": family,
            "left_count": len(left), "right_count": len(right),
            "left_key_sample": [x[0] for x in left[:5]],
            "right_key_sample": [x[0] for x in right[:5]],
            "receiver_hint": task.get("hint_mode"),
            "derived_signal": bool(task.get("derived_signal")),
            "goal": "preserve normalized join semantics while reducing counted operations",
        }
    if family == "sliding-window":
        events, queries = list(task["events"]), list(task["queries"])
        return {
            "family": family,
            "event_count": len(events), "query_count": len(queries),
            "event_sample": events[:10], "query_sample": queries[:5],
            "receiver_hint": task.get("hint_mode"),
            "derived_signal": bool(task.get("derived_signal")),
            "goal": "preserve window counts while reducing counted operations",
        }
    if family == "transient-fetch":
        requests = list(task["requests"])
        fails = dict(task["fail_counts"])
        return {
            "family": family,
            "request_count": len(requests), "unique_keys": len(set(requests)),
            "request_sample": requests[:10],
            "observed_failure_count_sample": {k: fails[k] for k in sorted(fails)[:5]},
            "receiver_hint": task.get("hint_mode"),
            "derived_signal": bool(task.get("derived_signal")),
            "goal": "preserve successful fetch results while reducing counted operations",
        }
    raise ValueError(family)


def build_prompt(*, arm: str, task_id: str, public_context: dict[str, Any], ordered_candidates: list[dict[str, Any]]) -> str:
    pool = [
        {"position": i + 1, "candidate_id": c["candidate_id"], "features": c["features"], "eligible_under_budget": i < EVALUATION_BUDGET}
        for i, c in enumerate(ordered_candidates)
    ]
    return (
        "RIL-RANK-LIVE-001 matched live researcher. You do not control the receiver, evaluator, candidate pool, or budget. "
        "The receiver will deterministically execute candidate implementations after your answer. The same 12 candidates exist in both matched arms; only their frozen presentation order differs. "
        f"Exactly the first {EVALUATION_BUDGET} positions are eligible under the receiver budget. Reorder ONLY those four from most to least promising. "
        "Do not select any candidate outside the eligible prefix. Return ONLY one JSON object with exactly this shape: "
        '{"evaluation_order":["candidate_id","candidate_id","candidate_id","candidate_id"]}. '
        "No markdown and no extra keys.\n\n"
        f"Frozen shared history:\n{HISTORY_TEXT}\n\n"
        f"Task id: {task_id}\n"
        f"Task public context: {json.dumps(public_context, sort_keys=True)}\n"
        f"Candidate pool in frozen order: {json.dumps(pool, sort_keys=True)}\n"
        "The live researcher is blinded to which ordering rule produced this list."
    )


def prepare_hermes_home(root: Path, label: str, api_key: str) -> Path:
    home = root / "hermes-homes" / label
    if home.exists():
        raise RuntimeError(f"fresh Hermes home already exists: {home}")
    home.mkdir(parents=True)
    (home / ".env").write_text(f"OPENAI_API_KEY={api_key}\n", encoding="utf-8")
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: openai-api\n"
        f"  default: {HERMES_MODEL}\n"
        f"  max_tokens: {MAX_OUTPUT_TOKENS}\n"
        "terminal:\n"
        "  backend: local\n"
        "  cwd: \".\"\n"
        "  timeout: 30\n"
        "approvals:\n"
        "  mode: off\n"
        "agent:\n"
        f"  max_turns: {MAX_ITERATIONS}\n",
        encoding="utf-8",
    )
    (home / "SOUL.md").write_text(
        "You are a bounded research-ordering worker. Return the exact requested JSON only. "
        "You have no acceptance, promotion, deployment, or policy authority.\n",
        encoding="utf-8",
    )
    os.chmod(home / ".env", 0o600)
    os.chmod(home / "config.yaml", 0o600)
    return home


@contextmanager
def worker_environment(home: Path):
    saved = dict(os.environ)
    try:
        for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(name, None)
        os.environ["HERMES_HOME"] = str(home)
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def accounting(usage: dict[str, Any]) -> dict[str, Any]:
    required_ints = ("input_tokens", "output_tokens", "total_tokens", "api_calls")
    numeric = all(isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool) and usage[k] >= 0 for k in required_ints)
    try:
        cost = Decimal(str(usage.get("estimated_cost_usd")))
        cost_valid = cost > 0
    except (InvalidOperation, TypeError):
        cost = Decimal("0")
        cost_valid = False
    priced = str(usage.get("cost_status") or "").lower() not in {"", "unknown", "unavailable", "none"}
    source_ok = str(usage.get("cost_source") or "").lower() not in {"", "unknown", "none"}
    identity = usage.get("model") == HERMES_MODEL and usage.get("provider") == HERMES_PROVIDER
    complete = bool(numeric and cost_valid and priced and source_ok and identity)
    within = bool(complete and int(usage["total_tokens"]) <= MAX_REPORTED_TOTAL_TOKENS and cost <= MAX_ESTIMATED_USD_PER_CALL)
    return {
        "telemetry_complete": complete,
        "within_preregistered_limits": within,
        "estimated_cost_usd": str(cost),
        "reported_total_tokens": usage.get("total_tokens"),
        "reported_api_calls": usage.get("api_calls"),
        "cost_status": usage.get("cost_status"),
        "cost_source": usage.get("cost_source"),
        "model": usage.get("model"),
        "provider": usage.get("provider"),
    }


def hermes_python() -> Path:
    exe = shutil.which("hermes")
    if not exe:
        raise RuntimeError("pinned hermes executable not found on PATH")
    resolved = Path(exe).resolve()
    python = resolved.parent / "python"
    if not python.is_file():
        raise RuntimeError(f"could not resolve pinned Hermes venv python beside {resolved}")
    return python


def run_live_call(*, run_root: Path, evidence_dir: Path, arm: str, task_id: str, prompt: str, api_key: str, shortlist: list[str]) -> dict[str, Any]:
    label = f"{task_id}-{arm}"
    home = prepare_hermes_home(run_root, label, api_key)
    workdir = run_root / "isolated-cwds" / label
    workdir.mkdir(parents=True)
    prompt_path = home / "prompt.txt"
    response_path = home / "response.txt"
    usage_path = home / "usage.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    driver = DRIVER_PATH.resolve()
    with worker_environment(home):
        cp = subprocess.run(
            [
                str(hermes_python()), str(driver),
                "--prompt-file", str(prompt_path),
                "--response-file", str(response_path),
                "--usage-file", str(usage_path),
                "--model", HERMES_MODEL,
                "--provider", HERMES_PROVIDER,
                "--max-iterations", str(MAX_ITERATIONS),
                "--max-output-tokens", str(MAX_OUTPUT_TOKENS),
            ],
            cwd=workdir, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    response = response_path.read_text(encoding="utf-8", errors="replace") if response_path.is_file() else ""
    usage = read_json(usage_path) if usage_path.is_file() else {}
    parsed = parse_json_object(response)
    order_valid, evaluation_order = validate_live_order(parsed, shortlist)
    acct = accounting(usage)
    record = {
        "arm": arm, "task_id": task_id, "fresh_hermes_home": True,
        "driver_exit_code": cp.returncode,
        "prompt_sha256": sha256_file(prompt_path),
        "response_sha256": sha256_file(response_path) if response_path.is_file() else None,
        "usage_sha256": sha256_file(usage_path) if usage_path.is_file() else None,
        "shortlist": shortlist,
        "evaluation_order": evaluation_order,
        "order_valid": order_valid,
        "accounting": acct,
        "stderr_tail": cp.stderr[-600:],
    }
    write_json(evidence_dir / f"{label}-live-receipt.json", record, durable=True)
    (evidence_dir / f"{label}-response.txt").write_text(response, encoding="utf-8")
    return record


def arm_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    selected = [r[arm] for r in rows]
    found = sum(1 for r in selected if r["receiver_result"]["found_acceptable"])
    evals = sum(int(r["receiver_result"]["evaluations_used"]) for r in selected)
    cost = sum((Decimal(str(r["live"]["accounting"]["estimated_cost_usd"])) for r in selected), Decimal("0"))
    return {
        "tasks": len(selected),
        "confirmed_improvements": found,
        "confirmed_improvement_rate": found / len(selected) if selected else 0.0,
        "receiver_evaluations_used_total": evals,
        "mean_receiver_evaluations_used": evals / len(selected) if selected else None,
        "live_model_cost_usd": str(cost),
        "confirmed_improvements_per_live_model_usd": (float(Decimal(found) / cost) if cost > 0 else None),
        "all_live_orders_valid": all(r["live"]["order_valid"] and r["live"]["driver_exit_code"] == 0 for r in selected),
        "all_cost_telemetry_complete": all(r["live"]["accounting"]["telemetry_complete"] for r in selected),
        "all_calls_within_limits": all(r["live"]["accounting"]["within_preregistered_limits"] for r in selected),
    }


def classify(evidence: dict[str, Any], baseline: dict[str, Any], all_valid: bool, economics_valid: bool) -> str:
    if not all_valid:
        return "INCONCLUSIVE_RIL_RANK_LIVE_001_LIVE_EXECUTION"
    if not economics_valid:
        return "INCONCLUSIVE_RIL_RANK_LIVE_001_ECONOMICS"
    er = float(evidence["confirmed_improvement_rate"])
    br = float(baseline["confirmed_improvement_rate"])
    eval_gain = int(baseline["receiver_evaluations_used_total"]) - int(evidence["receiver_evaluations_used_total"])
    e_eff = evidence["confirmed_improvements_per_live_model_usd"]
    b_eff = baseline["confirmed_improvements_per_live_model_usd"]
    efficiency_gain = e_eff is not None and b_eff is not None and e_eff > b_eff
    if er - br >= MIN_RATE_ADVANTAGE and eval_gain > 0 and efficiency_gain:
        return "PASS_RIL_RANK_LIVE_001_OBSERVED_LIVE_TRANSFER"
    if er - br >= MIN_RATE_ADVANTAGE and eval_gain > 0:
        return "LIVE_TRANSFER_WITH_MODEL_COST_PENALTY"
    if br - er >= MIN_RATE_ADVANTAGE:
        return "OBSERVED_LIVE_RANKING_DISADVANTAGE"
    return "NO_OBSERVED_LIVE_TRANSFER_ADVANTAGE"


def self_check() -> None:
    value = prereg()
    verify_predecessor()
    verify_frozen_files(value, require_committed=False)
    engine = load_exec_engine()
    policy = read_json(POLICY_PATH)
    assert value["design"]["tasks_total"] == len(engine.FAMILIES) * TASKS_PER_FAMILY
    assert value["design"]["evaluation_budget"] == EVALUATION_BUDGET
    assert value["design"]["min_rate_advantage"] == MIN_RATE_ADVANTAGE
    nonce = "31" * 32
    data_nonce = "47" * 32
    for family in engine.FAMILIES:
        cands = engine.generate_candidates(nonce, family, 0)
        task_id = f"{family}-000"
        evidence_order = engine.learned_order(policy["learned_model"], cands)
        baseline_order = engine.baseline_order(policy["baseline_order_seed"], task_id, cands)
        assert set(evidence_order) == set(baseline_order) == {c["candidate_id"] for c in cands}
        task = engine.make_task(family, 0, data_nonce)
        context = task_public_context(family, task)
        by_id = {c["candidate_id"]: c for c in cands}
        ordered = [by_id[cid] for cid in evidence_order]
        prompt = build_prompt(arm="evidence", task_id=task_id, public_context=context, ordered_candidates=ordered)
        assert HISTORY_TEXT in prompt and all(c["candidate_id"] in prompt for c in cands)
        shortlist = evidence_order[:EVALUATION_BUDGET]
        ok, out = validate_live_order({"evaluation_order": list(reversed(shortlist))}, shortlist)
        assert ok and set(out) == set(shortlist)
        outcomes = {c["candidate_id"]: engine.evaluate_candidate(family, task, c) for c in cands}
        score = engine.score_order(out, outcomes, EVALUATION_BUDGET)
        assert 1 <= score["evaluations_used"] <= EVALUATION_BUDGET
    print("RIL-RANK-LIVE-001 self-check: PASS")


def run(output: Path, evidence_dir: Path) -> dict[str, Any]:
    if output.exists() or evidence_dir.exists():
        raise SystemExit("refusing to reuse output/evidence path")
    value = prereg()
    verify_predecessor()
    verify_frozen_files(value, require_committed=True)
    engine = load_exec_engine()
    policy = read_json(POLICY_PATH)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY required for live primary")
    evidence_dir.mkdir(parents=True, exist_ok=False)
    run_root = Path(tempfile.mkdtemp(prefix="ril-rank-live-001-"))
    started = time.time()
    try:
        candidate_nonce = secrets.token_hex(32)
        sealed_tasks: list[dict[str, Any]] = []
        for family in engine.FAMILIES:
            for idx in range(TASKS_PER_FAMILY):
                task_id = f"{family}-{idx:03d}"
                cands = engine.generate_candidates(candidate_nonce, family, idx)
                sealed_tasks.append({
                    "family": family, "task_index": idx, "task_id": task_id, "candidates": cands,
                    "orders": {
                        "evidence": engine.learned_order(policy["learned_model"], cands),
                        "baseline": engine.baseline_order(policy["baseline_order_seed"], task_id, cands),
                    },
                })
        ordering_seal = {
            "schema": "openline.ril-rank-live-001.ordering-seal.v1", "experiment": EXPERIMENT,
            "policy_seal_sha256": POLICY_SEAL_SHA256, "candidate_nonce": candidate_nonce,
            "task_data_exists_at_seal": False, "tasks": sealed_tasks,
        }
        ordering_seal_sha = write_json(evidence_dir / "ordering-seal-before-task-data.json", ordering_seal, durable=True)
        task_data_nonce = secrets.token_hex(32)
        rows: list[dict[str, Any]] = []
        cumulative_live_cost = Decimal("0")
        for task_pos, item in enumerate(sealed_tasks):
            family, idx, task_id = item["family"], item["task_index"], item["task_id"]
            task = engine.make_task(family, idx, task_data_nonce)
            public_context = task_public_context(family, task)
            by_id = {c["candidate_id"]: c for c in item["candidates"]}
            outcomes = {cid: engine.evaluate_candidate(family, task, cand) for cid, cand in by_id.items()}
            row: dict[str, Any] = {"family": family, "task_id": task_id, "task_public_context": public_context}
            arm_schedule = ("evidence", "baseline") if task_pos % 2 == 0 else ("baseline", "evidence")
            for arm in arm_schedule:
                ordered_ids = item["orders"][arm]
                ordered_candidates = [by_id[cid] for cid in ordered_ids]
                shortlist = ordered_ids[:EVALUATION_BUDGET]
                prompt = build_prompt(arm=arm, task_id=task_id, public_context=public_context, ordered_candidates=ordered_candidates)
                live = run_live_call(
                    run_root=run_root, evidence_dir=evidence_dir, arm=arm, task_id=task_id,
                    prompt=prompt, api_key=api_key, shortlist=shortlist,
                )
                try:
                    cumulative_live_cost += Decimal(str(live["accounting"]["estimated_cost_usd"]))
                except (InvalidOperation, TypeError):
                    pass
                if cumulative_live_cost > MAX_ESTIMATED_USD_ALL_CALLS:
                    raise RuntimeError(f"global live-model cost ceiling exceeded: {cumulative_live_cost} > {MAX_ESTIMATED_USD_ALL_CALLS}")
                if live["order_valid"] and live["driver_exit_code"] == 0:
                    receiver_result = engine.score_order(live["evaluation_order"], outcomes, EVALUATION_BUDGET)
                else:
                    receiver_result = {
                        "found_acceptable": False, "evaluations_to_first_acceptable": None,
                        "evaluations_used": EVALUATION_BUDGET,
                        "censored_evaluations_to_first_acceptable": EVALUATION_BUDGET + 1,
                        "best_gain_seen": None, "invalid_live_order": True,
                    }
                row[arm] = {
                    "presented_order": ordered_ids,
                    "shortlist": shortlist,
                    "live": live,
                    "receiver_result": receiver_result,
                }
            rows.append(row)
        rows_sha = write_json(evidence_dir / "matched-live-rows.json", rows, durable=True)
        evidence_summary = arm_summary(rows, "evidence")
        baseline_summary = arm_summary(rows, "baseline")
        all_valid = evidence_summary["all_live_orders_valid"] and baseline_summary["all_live_orders_valid"]
        economics_valid = (
            evidence_summary["all_cost_telemetry_complete"] and baseline_summary["all_cost_telemetry_complete"]
            and evidence_summary["all_calls_within_limits"] and baseline_summary["all_calls_within_limits"]
            and cumulative_live_cost <= MAX_ESTIMATED_USD_ALL_CALLS
        )
        verdict = classify(evidence_summary, baseline_summary, all_valid, economics_valid)
        e_rate = float(evidence_summary["confirmed_improvement_rate"])
        b_rate = float(baseline_summary["confirmed_improvement_rate"])
        eval_savings = int(baseline_summary["receiver_evaluations_used_total"]) - int(evidence_summary["receiver_evaluations_used_total"])
        savings_per_task = eval_savings / len(rows)
        projected_break_even = None
        if savings_per_task > 0:
            import math
            projected_break_even = math.ceil(INHERITED_LEARNING_COST_EVALUATIONS / savings_per_task)
        result = {
            "schema": SCHEMA, "experiment": EXPERIMENT, "verdict": verdict,
            "scientific_standing": SCIENTIFIC_STANDING,
            "repeatability_standing": "NOT_TESTED_SINGLE_MATCHED_RUN",
            "level4_standing": "NOT_EARNED",
            "recursive_improvement_standing": "NOT_EARNED",
            "predecessor": value["predecessor"],
            "design": value["design"],
            "primary_metric": {
                "name": "confirmed_acceptable_improvement_rate_after_live_researcher_reorders_frozen_top4_shortlist",
                "tasks": len(rows), "evaluation_budget": EVALUATION_BUDGET,
                "evidence_rate": e_rate, "baseline_rate": b_rate,
                "advantage_vs_baseline": e_rate - b_rate,
                "min_rate_advantage": MIN_RATE_ADVANTAGE,
                "receiver_evaluation_savings_vs_baseline": eval_savings,
            },
            "arms": {"evidence": evidence_summary, "baseline": baseline_summary},
            "economics": {
                "all_live_model_cost_usd": str(cumulative_live_cost),
                "global_live_model_cost_ceiling_usd": str(MAX_ESTIMATED_USD_ALL_CALLS),
                "inherited_learning_cost_evaluations": INHERITED_LEARNING_COST_EVALUATIONS,
                "receiver_evaluation_savings_vs_baseline": eval_savings,
                "mean_receiver_evaluation_savings_per_task": savings_per_task,
                "projected_break_even_future_tasks_at_observed_receiver_savings_rate": projected_break_even,
                "learning_cost_recovered_in_this_run": eval_savings >= INHERITED_LEARNING_COST_EVALUATIONS,
            },
            "integrity": {
                "predecessor_main": PREDECESSOR_MAIN,
                "predecessor_freeze_blob": PREDECESSOR_FREEZE_BLOB,
                "exact_policy_seal_sha256": POLICY_SEAL_SHA256,
                "exact_predecessor_runner_sha256": PREDECESSOR_RUNNER_SHA256,
                "same_history_both_arms": True,
                "same_candidate_pool_both_arms": True,
                "same_live_model_both_arms": True,
                "same_live_limits_both_arms": True,
                "only_frozen_candidate_order_differs_before_live_call": True,
                "ordering_sealed_before_task_data_nonce": True,
                "ordering_seal_sha256": ordering_seal_sha,
                "task_data_nonce": task_data_nonce,
                "matched_live_rows_sha256": rows_sha,
                "fresh_hermes_home_each_call": True,
                "arm_call_order_alternated_by_task": True,
                "all_live_orders_valid": all_valid,
                "economics_valid": economics_valid,
            },
            "claim_boundary": value["claim_boundary"],
            "started_unix": started, "completed_unix": time.time(),
        }
        write_json(output, result, durable=True)
        return result
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--evidence-dir", type=Path)
    args = ap.parse_args()
    if args.self_check:
        self_check()
        return 0
    if not args.output or not args.evidence_dir:
        ap.error("--output and --evidence-dir required unless --self-check")
    result = run(args.output, args.evidence_dir)
    print(json.dumps({
        "verdict": result["verdict"],
        "primary_metric": result["primary_metric"],
        "economics": result["economics"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
