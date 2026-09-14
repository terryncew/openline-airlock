#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

HERE = Path(__file__).resolve().parent
PREREG = HERE / "AUTORESEARCH_LIVE_003_PREREGISTRATION.json"
EXPERIMENT_ID = "AUTORESEARCH-LIVE-003"
UPSTREAM_PIN = "228791fb499afffb54b46200aca536f79142f117"
AIRLOCK_BASE_MAIN = "e8a5f64bb993ad09726c1a4db8f4c5030f26b675"
STATE_SCHEMA = "openline.autoresearch.live003-state.v1"
RESULT_SCHEMA = "openline.autoresearch.live003-result.v1"
MAX_POD_WALL_SECONDS = 9000
MAX_GPU_SPEND_USD = 5.0
MAX_RECEIVER_MEASUREMENTS = 14
TRAINING_SECONDS_PER_MEASUREMENT = 300


def load_protocol_module():
    path = HERE / "protocol.py"
    spec = importlib.util.spec_from_file_location("autoresearch_live_003_protocol", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load protocol module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


protocol = load_protocol_module()


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        detail = p.stderr.strip() or p.stdout.strip() or f"command failed: {' '.join(cmd)}"
        raise RuntimeError(detail)
    return p


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd=repo, check=check).stdout.strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean_status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all")


def require_clean(repo: Path) -> None:
    status = clean_status(repo)
    if status:
        raise RuntimeError("experiment worktree is not clean:\n" + status)


def protected_hashes(repo: Path) -> dict[str, str]:
    files = [x for x in git(repo, "ls-files").splitlines() if x and x != "train.py"]
    if not files:
        raise RuntimeError("no protected tracked files")
    out: dict[str, str] = {}
    for rel in sorted(files):
        path = repo / rel
        if not path.is_file():
            raise RuntimeError(f"protected file missing: {rel}")
        out[rel] = sha256_file(path)
    return out


def verify_protected(repo: Path, expected: dict[str, str]) -> dict[str, Any]:
    status = clean_status(repo)
    if status:
        return {"ok": False, "reason": "DIRTY_OR_UNTRACKED_WORKTREE", "status": status.splitlines()}
    current = protected_hashes(repo)
    changed = sorted(k for k in set(expected) | set(current) if expected.get(k) != current.get(k))
    return {"ok": not changed, "reason": "MATCH" if not changed else "PROTECTED_HASH_MISMATCH", "changed": changed}


def state_path(evidence: Path) -> Path:
    return evidence / "state.json"


def load_state(evidence: Path) -> dict[str, Any]:
    path = state_path(evidence)
    if not path.is_file():
        raise RuntimeError("LIVE-003 state missing; run snapshot first")
    state = read_json(path)
    if state.get("schema") != STATE_SCHEMA:
        raise RuntimeError("unsupported LIVE-003 state")
    return state


def save_state(evidence: Path, state: dict[str, Any]) -> None:
    write_json(state_path(evidence), state)


def pstate(state: dict[str, Any]):
    return protocol.from_dict(state["protocol"])


def save_pstate(state: dict[str, Any], ps: Any) -> None:
    state["protocol"] = protocol.to_dict(ps)


def receiver_env(repo: Path, cache: Path) -> dict[str, str]:
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError(f"missing autoresearch venv: {python}")
    env = os.environ.copy()
    env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    env["AUTORESEARCH_HOST_CACHE"] = str(cache.resolve())
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    return env


def receiver(repo: Path, cache: Path, *args: str) -> dict[str, Any]:
    python = str(repo / ".venv" / "bin" / "python")
    p = run([python, ".airlock/receiver_gate.py", *args], cwd=repo, env=receiver_env(repo, cache))
    lines = [x for x in p.stdout.splitlines() if x.strip()]
    if not lines:
        raise RuntimeError("receiver emitted no JSON")
    value = json.loads(lines[-1])
    if not isinstance(value, dict):
        raise RuntimeError("receiver result is not an object")
    return value


def copy_receipt(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def check_budget(state: dict[str, Any], evidence: Path) -> None:
    now = time.time()
    elapsed = max(0.0, now - float(state["budget"]["pod_started_epoch"]))
    rate = float(state["budget"]["gpu_hourly_rate_usd"])
    estimated = elapsed * rate / 3600.0
    state["budget"]["pod_wall_seconds_observed"] = round(elapsed, 3)
    state["budget"]["estimated_gpu_spend_usd"] = round(estimated, 6)
    save_state(evidence, state)
    if elapsed > MAX_POD_WALL_SECONDS or estimated > MAX_GPU_SPEND_USD:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_BUDGET_EXCEEDED"
        save_state(evidence, state)
        raise RuntimeError("LIVE-003 total wall/spend budget exceeded")


def consume_measurement_attempt(state: dict[str, Any], evidence: Path, label: str) -> None:
    count = int(state["budget"].get("receiver_measurement_attempts", 0)) + 1
    if count > MAX_RECEIVER_MEASUREMENTS:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_BUDGET_EXCEEDED"
        save_state(evidence, state)
        raise RuntimeError("receiver measurement budget exceeded")
    state["budget"]["receiver_measurement_attempts"] = count
    state["budget"]["training_seconds_ceiling_consumed"] = count * TRAINING_SECONDS_PER_MEASUREMENT
    state["budget"].setdefault("measurement_attempt_log", []).append({"index": count, "label": label, "started_at_utc": utc_now()})
    save_state(evidence, state)


def prereg_worker() -> dict[str, Any]:
    return read_json(PREREG)["worker"]


def snapshot(repo: Path, evidence: Path, start_epoch: float, hourly_rate: float) -> None:
    repo = repo.resolve()
    evidence = evidence.resolve()
    if evidence.exists() and any(evidence.iterdir()):
        raise RuntimeError("refusing to overwrite non-empty LIVE-003 evidence directory")
    evidence.mkdir(parents=True, exist_ok=True)
    require_clean(repo)
    manifest = read_json(repo / ".airlock" / "autoresearch-upstream.json")
    if manifest.get("commit") != UPSTREAM_PIN:
        raise RuntimeError("wrong autoresearch upstream pin")
    push_url = git(repo, "remote", "get-url", "--push", "origin", check=False)
    if not push_url.startswith("no_push://"):
        raise RuntimeError(f"experiment clone push is not disabled: {push_url!r}")
    airlock_root = HERE.parents[1]
    if (airlock_root / ".git").exists():
        airlock_head = git(airlock_root, "rev-parse", "HEAD")
        if airlock_head != AIRLOCK_BASE_MAIN and subprocess.run(["git", "merge-base", "--is-ancestor", AIRLOCK_BASE_MAIN, airlock_head], cwd=airlock_root).returncode != 0:
            raise RuntimeError("Airlock checkout does not descend from frozen LIVE-003 base")
    if hourly_rate <= 0:
        raise RuntimeError("hourly GPU rate must be positive")
    if hourly_rate * (MAX_POD_WALL_SECONDS / 3600.0) > MAX_GPU_SPEND_USD:
        raise RuntimeError("selected GPU rate cannot fit the frozen maximum wall time inside the $5 spend ceiling")
    protected = protected_hashes(repo)
    head = git(repo, "rev-parse", "HEAD")
    state = {
        "schema": STATE_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": utc_now(),
        "repo": str(repo),
        "upstream_pin": UPSTREAM_PIN,
        "airlock_base_main": AIRLOCK_BASE_MAIN,
        "bootstrap_commit": head,
        "push_url": push_url,
        "preregistration_sha256": sha256_file(PREREG),
        "worker": prereg_worker(),
        "protected_sha256": protected,
        "baseline": None,
        "accepted_commit": None,
        "discoveries": [],
        "confirmation": None,
        "protocol": protocol.to_dict(protocol.ProtocolState()),
        "budget": {
            "pod_started_epoch": float(start_epoch),
            "gpu_hourly_rate_usd": float(hourly_rate),
            "maximum_pod_wall_seconds": MAX_POD_WALL_SECONDS,
            "maximum_paid_gpu_spend_usd": MAX_GPU_SPEND_USD,
            "receiver_measurement_attempts": 0,
            "training_seconds_ceiling_consumed": 0,
            "researcher_calls": 0
        },
        "terminal": False,
        "terminal_verdict": None
    }
    write_json(evidence / "protected-snapshot.json", {"experiment_id": EXPERIMENT_ID, "bootstrap_commit": head, "files": protected})
    save_state(evidence, state)
    check_budget(state, evidence)
    print(json.dumps({"status": "SNAPSHOT_FROZEN", "bootstrap_commit": head, "protected_files": len(protected), "budget": state["budget"]}, sort_keys=True))


def initialize(repo: Path, evidence: Path, cache: Path) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("baseline") is not None:
        raise RuntimeError("baseline already measured")
    integrity = verify_protected(repo, state["protected_sha256"])
    if not integrity["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", integrity)
    consume_measurement_attempt(state, evidence, "baseline")
    result = receiver(repo, cache, "init")
    integrity_after = verify_protected(repo, state["protected_sha256"])
    if not integrity_after["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", integrity_after)
    state["baseline"] = result.get("accepted_measurement")
    state["accepted_commit"] = result.get("accepted_commit")
    state["baseline_completed_at_utc"] = utc_now()
    save_state(evidence, state)
    print(json.dumps({"status": "BASELINE_MEASURED", "accepted_commit": state["accepted_commit"], "baseline": state["baseline"]}, sort_keys=True))


def abort(state: dict[str, Any], evidence: Path, verdict: str, detail: Any) -> None:
    state["terminal"] = True
    state["terminal_verdict"] = verdict
    state["abort_detail"] = detail
    save_state(evidence, state)
    finalize(state, evidence)
    raise RuntimeError(f"{verdict}: {detail}")


def begin_call(evidence: Path) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("terminal"):
        raise RuntimeError(f"experiment terminal: {state.get('terminal_verdict')}")
    if state.get("baseline") is None:
        raise RuntimeError("baseline missing")
    ps = pstate(state)
    try:
        index = protocol.begin_researcher_call(ps)
    except RuntimeError:
        save_pstate(state, ps)
        state["budget"]["researcher_calls"] = ps.researcher_calls
        if ps.terminal_verdict:
            state["terminal"] = True
            state["terminal_verdict"] = ps.terminal_verdict
            finalize(state, evidence)
        save_state(evidence, state)
        raise
    save_pstate(state, ps)
    state["budget"]["researcher_calls"] = ps.researcher_calls
    save_state(evidence, state)
    print(json.dumps({"status": "RESEARCHER_CALL_AUTHORIZED", "call": index, "maximum_calls": protocol.MAX_RESEARCHER_CALLS}, sort_keys=True))


def abandon_call(evidence: Path, reason: str) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    ps = pstate(state)
    action = protocol.abandon_researcher_call(ps, reason)
    save_pstate(state, ps)
    state["budget"]["researcher_calls"] = ps.researcher_calls
    if action == "STOP":
        state["terminal"] = True
        state["terminal_verdict"] = ps.terminal_verdict
        finalize(state, evidence)
    save_state(evidence, state)
    print(json.dumps({"status": "RESEARCHER_CALL_ABANDONED", "reason": reason, "action": action, "calls": ps.researcher_calls}, sort_keys=True))


def discovery(repo: Path, evidence: Path, cache: Path, candidate_arg: str) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("terminal"):
        raise RuntimeError(f"experiment terminal: {state.get('terminal_verdict')}")
    ps = pstate(state)
    if ps.phase != "SEARCHING" or ps.open_researcher_call is None:
        raise RuntimeError("run begin-call before contacting researcher and submitting a discovery candidate")
    require_clean(repo)
    candidate = git(repo, "rev-parse", candidate_arg)
    if candidate != git(repo, "rev-parse", "HEAD"):
        raise RuntimeError("candidate must be current clean HEAD")
    before = verify_protected(repo, state["protected_sha256"])
    if not before["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", before)
    consume_measurement_attempt(state, evidence, f"discovery-{ps.discovery_evaluations + 1:02d}")
    eval_result = receiver(repo, cache, "evaluate", candidate)
    receipt_src = Path(str(eval_result["receipt"]))
    receipt_obj = read_json(receipt_src)
    decision = receipt_obj.get("payload", {}).get("decision")
    if decision not in {"ACCEPT", "REJECT"}:
        abort(state, evidence, "ABORT_EXECUTION_FAILURE", f"unexpected receiver decision {decision!r}")
    index = ps.discovery_evaluations + 1
    copied = copy_receipt(receipt_src, evidence / "receipts" / f"discovery-{index:02d}.json")
    action = protocol.record_discovery(ps, candidate, decision)
    after = verify_protected(repo, state["protected_sha256"])
    if not after["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", after)
    row = {
        "index": index,
        "researcher_call": ps.researcher_calls,
        "candidate_commit": candidate,
        "candidate_tree": git(repo, "rev-parse", f"{candidate}^{{tree}}"),
        "train_blob": git(repo, "rev-parse", f"{candidate}:train.py"),
        "decision": decision,
        "evaluation": receipt_obj.get("payload", {}).get("evaluation"),
        "receipt": str(copied),
        "receipt_sha256": sha256_file(copied),
        "integrity_before": before,
        "integrity_after": after,
        "action": action
    }
    state["discoveries"].append(row)
    save_pstate(state, ps)
    state["budget"]["researcher_calls"] = ps.researcher_calls

    if decision == "REJECT":
        accepted = receiver(repo, cache, "status").get("accepted_commit")
        state["accepted_commit"] = accepted
        git(repo, "branch", "-f", f"openline/live003-rejected-{index:02d}", candidate)
        git(repo, "reset", "--hard", str(accepted))
        if action == "STOP":
            state["terminal"] = True
            state["terminal_verdict"] = ps.terminal_verdict
            save_state(evidence, state)
            finalize(state, evidence)
        else:
            save_state(evidence, state)
    else:
        # Critical invariant: discovery ACCEPT is only an apparent win. The
        # accepted receiver ref remains unchanged until a fresh confirmation ACCEPT.
        accepted = receiver(repo, cache, "status").get("accepted_commit")
        if accepted != state["accepted_commit"]:
            abort(state, evidence, "ABORT_EXECUTION_FAILURE", "accepted state moved before confirmation")
        state["apparent_win_candidate"] = candidate
        state["apparent_win_discovery_receipt"] = str(copied)
        save_state(evidence, state)

    print(json.dumps({"status": "DISCOVERY_RECORDED", "candidate": candidate, "decision": decision, "action": action, "terminal_verdict": state.get("terminal_verdict")}, sort_keys=True))


def confirm(repo: Path, evidence: Path, cache: Path) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("terminal"):
        raise RuntimeError(f"experiment terminal: {state.get('terminal_verdict')}")
    ps = pstate(state)
    if ps.phase != "CONFIRMING" or not ps.apparent_win_candidate:
        raise RuntimeError("no apparent win awaiting confirmation")
    candidate = ps.apparent_win_candidate
    require_clean(repo)
    if git(repo, "rev-parse", "HEAD") != candidate:
        raise RuntimeError("confirmation requires exact apparent-win candidate as current HEAD")
    accepted_before = receiver(repo, cache, "status").get("accepted_commit")
    if accepted_before != state["accepted_commit"]:
        abort(state, evidence, "ABORT_EXECUTION_FAILURE", "accepted base moved before confirmation")
    before = verify_protected(repo, state["protected_sha256"])
    if not before["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", before)

    consume_measurement_attempt(state, evidence, "confirmation-first-apparent-win")
    eval_result = receiver(repo, cache, "evaluate", candidate)
    receipt_src = Path(str(eval_result["receipt"]))
    receipt_obj = read_json(receipt_src)
    decision = receipt_obj.get("payload", {}).get("decision")
    if decision not in {"ACCEPT", "REJECT"}:
        abort(state, evidence, "ABORT_EXECUTION_FAILURE", f"unexpected confirmation decision {decision!r}")
    copied = copy_receipt(receipt_src, evidence / "receipts" / "confirmation-01.json")
    action = protocol.record_confirmation(ps, candidate, decision)
    after = verify_protected(repo, state["protected_sha256"])
    if not after["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", after)
    state["confirmation"] = {
        "candidate_commit": candidate,
        "decision": decision,
        "evaluation": receipt_obj.get("payload", {}).get("evaluation"),
        "receipt": str(copied),
        "receipt_sha256": sha256_file(copied),
        "integrity_before": before,
        "integrity_after": after,
        "action": action
    }
    save_pstate(state, ps)

    if action == "PROMOTE":
        # Only the confirmation receipt may authorize promotion.
        promoted = receiver(repo, cache, "promote", str(copied), "--candidate", candidate)
        accepted = promoted.get("accepted_commit")
        if accepted != candidate:
            abort(state, evidence, "ABORT_EXECUTION_FAILURE", "receiver did not advance to confirmed candidate")
        state["accepted_commit"] = accepted
        protocol.record_promotion(ps, candidate)
        save_pstate(state, ps)
        state["terminal"] = True
        state["terminal_verdict"] = ps.terminal_verdict
    else:
        git(repo, "branch", "-f", "openline/live003-unconfirmed-apparent-win", candidate)
        git(repo, "reset", "--hard", str(state["accepted_commit"]))
        state["terminal"] = True
        state["terminal_verdict"] = ps.terminal_verdict

    save_state(evidence, state)
    finalize(state, evidence)
    print(json.dumps({"status": "TERMINAL", "candidate": candidate, "confirmation_decision": decision, "terminal_verdict": state["terminal_verdict"], "accepted_commit": state["accepted_commit"]}, sort_keys=True))


def finalize(state: dict[str, Any], evidence: Path) -> dict[str, Any]:
    ps = pstate(state)
    elapsed = max(0.0, time.time() - float(state["budget"]["pod_started_epoch"]))
    rate = float(state["budget"]["gpu_hourly_rate_usd"])
    state["budget"]["pod_wall_seconds_observed"] = round(elapsed, 3)
    state["budget"]["estimated_gpu_spend_usd"] = round(elapsed * rate / 3600.0, 6)
    result = {
        "schema": RESULT_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "completed_at_utc": utc_now(),
        "terminal_verdict": state.get("terminal_verdict") or ps.terminal_verdict,
        "upstream_pin": state.get("upstream_pin"),
        "airlock_base_main": state.get("airlock_base_main"),
        "preregistration_sha256": state.get("preregistration_sha256"),
        "worker": state.get("worker"),
        "baseline": state.get("baseline"),
        "discoveries": state.get("discoveries"),
        "confirmation": state.get("confirmation"),
        "final_accepted_commit": state.get("accepted_commit"),
        "protocol": protocol.to_dict(ps),
        "budget": state.get("budget"),
        "claim_boundary": "one confirmed fixed-seed live improvement A at most; no cumulative optimization, repeatability, statistical superiority, or recursive-improvement claim"
    }
    path = evidence / "AUTORESEARCH_LIVE_003_RESULT.json"
    write_json(path, result)
    state["result_path"] = str(path)
    save_state(evidence, state)
    return result


def status(evidence: Path) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    print(json.dumps({
        "experiment_id": EXPERIMENT_ID,
        "terminal": state.get("terminal"),
        "terminal_verdict": state.get("terminal_verdict"),
        "accepted_commit": state.get("accepted_commit"),
        "protocol": state.get("protocol"),
        "budget": state.get("budget")
    }, sort_keys=True))


def self_test() -> None:
    prereg = read_json(PREREG)
    assert prereg["experiment_id"] == EXPERIMENT_ID
    assert prereg["lineage"]["airlock_base_main"] == AIRLOCK_BASE_MAIN
    assert prereg["search_budget"]["maximum_researcher_calls"] == protocol.MAX_RESEARCHER_CALLS
    assert prereg["search_budget"]["maximum_discovery_evaluations"] == protocol.MAX_DISCOVERY_EVALUATIONS
    assert prereg["search_budget"]["maximum_confirmation_evaluations"] == protocol.MAX_CONFIRMATION_EVALUATIONS
    assert prereg["total_budget"]["maximum_pod_wall_seconds"] == MAX_POD_WALL_SECONDS
    assert float(prereg["total_budget"]["maximum_paid_gpu_spend_usd"]) == MAX_GPU_SPEND_USD
    assert prereg["search_budget"]["maximum_receiver_measurements_including_baseline"] == MAX_RECEIVER_MEASUREMENTS
    assert prereg["search_budget"]["maximum_training_seconds"] == MAX_RECEIVER_MEASUREMENTS * TRAINING_SECONDS_PER_MEASUREMENT
    print(json.dumps({"status": "PASS_LIVE_003_STATIC_SELF_TEST"}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AUTORESEARCH-LIVE-003 receiver-owned search driver")
    p.add_argument("--repo", default="/workspace/autoresearch-live-003")
    p.add_argument("--evidence", default="/workspace/autoresearch-live-003-evidence")
    p.add_argument("--cache", default="/workspace/.cache/autoresearch")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--start-epoch", type=float, required=True)
    s.add_argument("--hourly-rate-usd", type=float, required=True)
    sub.add_parser("init")
    sub.add_parser("begin-call")
    a = sub.add_parser("abandon-call")
    a.add_argument("--reason", required=True)
    d = sub.add_parser("discover")
    d.add_argument("candidate")
    sub.add_parser("confirm")
    sub.add_parser("status")
    sub.add_parser("self-test")
    return p


def main() -> int:
    args = parser().parse_args()
    repo = Path(args.repo).resolve()
    evidence = Path(args.evidence).resolve()
    cache = Path(args.cache).resolve()
    if args.command == "snapshot":
        snapshot(repo, evidence, args.start_epoch, args.hourly_rate_usd)
    elif args.command == "init":
        initialize(repo, evidence, cache)
    elif args.command == "begin-call":
        begin_call(evidence)
    elif args.command == "abandon-call":
        abandon_call(evidence, args.reason)
    elif args.command == "discover":
        discovery(repo, evidence, cache, args.candidate)
    elif args.command == "confirm":
        confirm(repo, evidence, cache)
    elif args.command == "status":
        status(evidence)
    elif args.command == "self-test":
        self_test()
    else:
        raise AssertionError(args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
