#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

import inheritance
import protocol

EXPERIMENT_ID = "AUTORESEARCH-LIVE-004"
EVIDENCE_SCHEMA = "openline.autoresearch.live004-state.v1"
RESULT_SCHEMA = "openline.autoresearch.live004-result.v1"
AIRLOCK_MINIMUM_ANCESTOR = "536c080a03a9de0dff72ef7c9748f37833ca1f9c"
MAX_POD_WALL_SECONDS = 9000
MAX_GPU_SPEND_USD = 4.00
MAX_RECEIVER_MEASUREMENTS = 14
TRAINING_SECONDS_PER_MEASUREMENT = 300
HERE = Path(__file__).resolve().parent
PREREG = HERE / "AUTORESEARCH_LIVE_004_PREREGISTRATION.json"

WORKER = {
    "provider": "Meta",
    "product": "Muse personal AI agent",
    "model": "Muse Spark 1.3",
    "worker_name": "Prince",
    "identity_attestation": "self-declared; not independently verified by runtime",
}


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "command failed: " + " ".join(cmd))
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


def state_path(evidence: Path) -> Path:
    return evidence / "state.json"


def load_state(evidence: Path) -> dict[str, Any]:
    state = read_json(state_path(evidence))
    if state.get("schema") != EVIDENCE_SCHEMA:
        raise RuntimeError("unsupported LIVE-004 state")
    return state


def save_state(evidence: Path, state: dict[str, Any]) -> None:
    write_json(state_path(evidence), state)


def pstate(state: dict[str, Any]) -> protocol.ProtocolState:
    return protocol.from_dict(state.get("protocol", {}))


def save_pstate(state: dict[str, Any], ps: protocol.ProtocolState) -> None:
    state["protocol"] = protocol.to_dict(ps)


def clean_status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all")


def require_clean(repo: Path) -> None:
    status = clean_status(repo)
    if status:
        raise RuntimeError("research worktree is not clean:\n" + status)


def tracked_protected_hashes(repo: Path) -> dict[str, str]:
    files = [line for line in git(repo, "ls-files").splitlines() if line and line != "train.py"]
    if not files:
        raise RuntimeError("no protected tracked files found")
    out: dict[str, str] = {}
    for rel in sorted(files):
        path = repo / rel
        if not path.is_file():
            raise RuntimeError(f"protected tracked file missing: {rel}")
        out[rel] = sha256_file(path)
    return out


def verify_protected(repo: Path, expected: dict[str, str]) -> dict[str, Any]:
    status = clean_status(repo)
    if status:
        return {"ok": False, "reason": "DIRTY_OR_UNTRACKED_WORKTREE", "status": status.splitlines()}
    current = tracked_protected_hashes(repo)
    changed = sorted(path for path in set(expected) | set(current) if expected.get(path) != current.get(path))
    return {"ok": not changed, "reason": "MATCH" if not changed else "PROTECTED_HASH_MISMATCH", "changed": changed}


def hardware() -> dict[str, Any]:
    p = run([
        "nvidia-smi",
        "--query-gpu=name,uuid,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ], check=False)
    if p.returncode:
        return {"available": False, "error": p.stderr.strip() or p.stdout.strip()}
    return {"available": True, "rows": [line.strip() for line in p.stdout.splitlines() if line.strip()]}


def configure_measurement_env(repo: Path, cache: Path) -> None:
    venv_bin = repo / ".venv" / "bin"
    python = venv_bin / "python"
    if not python.is_file():
        raise RuntimeError(f"autoresearch virtualenv missing: {python}")
    os.environ["PATH"] = str(venv_bin) + os.pathsep + os.environ.get("PATH", "")
    os.environ["AUTORESEARCH_HOST_CACHE"] = str(cache.resolve())
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")


def copied_receipt(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def projected_spend(rate: float) -> float:
    return rate * MAX_POD_WALL_SECONDS / 3600.0


def budget_values(state: dict[str, Any]) -> tuple[float, float]:
    elapsed = max(0.0, time.time() - float(state["budget"]["pod_started_epoch"]))
    rate = float(state["budget"]["gpu_hourly_rate_usd"])
    spend = elapsed * rate / 3600.0
    return elapsed, spend


def check_budget(state: dict[str, Any], evidence: Path, *, mutate_on_exceed: bool = True) -> None:
    elapsed, spend = budget_values(state)
    state["budget"]["pod_wall_seconds_observed"] = round(elapsed, 3)
    state["budget"]["estimated_gpu_spend_usd"] = round(spend, 6)
    if elapsed <= MAX_POD_WALL_SECONDS and spend <= MAX_GPU_SPEND_USD:
        return
    if mutate_on_exceed and not state.get("terminal"):
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_BUDGET_EXCEEDED"
        save_state(evidence, state)
        finalize(state, evidence)
    raise RuntimeError(f"LIVE-004 budget exceeded: wall={elapsed:.1f}s spend=${spend:.4f}")


def consume_measurement_attempt(state: dict[str, Any], evidence: Path, label: str) -> None:
    attempts = int(state["budget"].get("receiver_measurements_attempted", 0))
    if attempts >= MAX_RECEIVER_MEASUREMENTS:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_BUDGET_EXCEEDED"
        save_state(evidence, state)
        finalize(state, evidence)
        raise RuntimeError("receiver-measurement budget exhausted")
    state["budget"]["receiver_measurements_attempted"] = attempts + 1
    state["budget"]["training_seconds_budgeted"] = (attempts + 1) * TRAINING_SECONDS_PER_MEASUREMENT
    state.setdefault("measurement_attempts", []).append({"index": attempts + 1, "label": label, "reserved_at_utc": utc_now()})
    save_state(evidence, state)


def abort(state: dict[str, Any], evidence: Path, verdict: str, detail: Any) -> None:
    state["terminal"] = True
    state["terminal_verdict"] = verdict
    state["abort_detail"] = detail
    save_state(evidence, state)
    finalize(state, evidence)
    raise RuntimeError(f"{verdict}: {detail}")


def snapshot(repo: Path, evidence: Path, bundle: Path, start_epoch: float, hourly_rate: float) -> None:
    evidence = evidence.resolve()
    repo = repo.resolve()
    airlock_root = HERE.parents[1]
    if projected_spend(hourly_rate) > MAX_GPU_SPEND_USD + 1e-9:
        raise RuntimeError(
            f"recorded GPU rate ${hourly_rate}/hr makes 150-minute projected spend ${projected_spend(hourly_rate):.4f}, above ${MAX_GPU_SPEND_USD:.2f} ceiling"
        )
    if evidence.exists() and any(evidence.iterdir()):
        raise RuntimeError("LIVE-004 evidence directory must be fresh and empty")
    evidence.mkdir(parents=True, exist_ok=True)

    inheritance_record = inheritance.verify_and_materialize_a(repo, bundle, airlock_root)
    write_json(evidence / "INHERITED_A.json", inheritance_record)
    require_clean(repo)
    protected = tracked_protected_hashes(repo)
    ps = protocol.ProtocolState()
    protocol.record_inheritance(ps, inheritance.INHERITED_A)

    state: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": utc_now(),
        "airlock_driver_commit": git(airlock_root, "rev-parse", "HEAD", check=False) if (airlock_root / ".git").exists() else None,
        "airlock_minimum_ancestor": AIRLOCK_MINIMUM_ANCESTOR,
        "upstream_pin": inheritance.UPSTREAM_PIN,
        "worker": WORKER,
        "preregistration_sha256": sha256_file(PREREG),
        "inheritance_record": inheritance_record,
        "protected_sha256": protected,
        "hardware": hardware(),
        "baseline": None,
        "accepted_commit": inheritance.INHERITED_A,
        "discoveries": [],
        "confirmation": None,
        "protocol": protocol.to_dict(ps),
        "budget": {
            "pod_started_epoch": float(start_epoch),
            "gpu_hourly_rate_usd": float(hourly_rate),
            "maximum_pod_wall_seconds": MAX_POD_WALL_SECONDS,
            "maximum_paid_gpu_spend_usd": MAX_GPU_SPEND_USD,
            "projected_spend_at_wall_ceiling_usd": round(projected_spend(hourly_rate), 6),
            "receiver_measurements_attempted": 0,
            "training_seconds_budgeted": 0,
        },
        "terminal": False,
        "terminal_verdict": None,
    }
    write_json(evidence / "protected-snapshot.json", {
        "schema": "openline.autoresearch.live004-protected-snapshot.v1",
        "inherited_a_commit": inheritance.INHERITED_A,
        "files": protected,
    })
    save_state(evidence, state)
    check_budget(state, evidence)
    print(json.dumps({
        "status": "INHERITED_A_FROZEN",
        "inherited_a_commit": inheritance.INHERITED_A,
        "inherited_a_train_blob": inheritance_record["inherited_a_train_blob"],
        "bundle_sha256": inheritance_record["carrier_git_bundle_sha256"],
        "protected_files": len(protected),
        "projected_spend_at_wall_ceiling_usd": state["budget"]["projected_spend_at_wall_ceiling_usd"],
    }, sort_keys=True))


def init(repo: Path, evidence: Path, cache: Path) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("baseline") is not None:
        raise RuntimeError("inherited-A baseline already measured")
    configure_measurement_env(repo, cache)
    check = verify_protected(repo, state["protected_sha256"])
    if not check["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", check)
    if git(repo, "rev-parse", "HEAD") != inheritance.INHERITED_A:
        abort(state, evidence, "ABORT_INHERITANCE_FAILURE", "HEAD moved before inherited-A baseline")
    consume_measurement_attempt(state, evidence, "fresh-inherited-a-baseline")
    import receiver
    rstate = receiver.initialize(repo, evidence, state["inheritance_record"])
    after = verify_protected(repo, state["protected_sha256"])
    if not after["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", after)
    state["baseline"] = rstate["accepted_measurement"]
    state["accepted_commit"] = rstate["accepted_commit"]
    state["baseline_completed_at_utc"] = utc_now()
    save_state(evidence, state)
    print(json.dumps({"status": "INHERITED_A_BASELINE_MEASURED", "accepted_commit": state["accepted_commit"], "baseline": state["baseline"]}, sort_keys=True))


def begin_call(evidence: Path) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("terminal"):
        raise RuntimeError(f"experiment terminal: {state.get('terminal_verdict')}")
    if state.get("baseline") is None:
        raise RuntimeError("measure inherited-A baseline before researcher contact")
    ps = pstate(state)
    call = protocol.begin_researcher_call(ps)
    save_pstate(state, ps)
    state["budget"]["researcher_calls"] = ps.researcher_calls
    save_state(evidence, state)
    print(json.dumps({"status": "RESEARCHER_CALL_RESERVED", "call": call, "remaining": protocol.MAX_RESEARCHER_CALLS - ps.researcher_calls}, sort_keys=True))


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
        save_state(evidence, state)
        finalize(state, evidence)
    else:
        save_state(evidence, state)
    print(json.dumps({"status": "RESEARCHER_CALL_ABANDONED", "action": action, "terminal_verdict": state.get("terminal_verdict")}, sort_keys=True))


def discover(repo: Path, evidence: Path, cache: Path, candidate_arg: str) -> None:
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("terminal"):
        raise RuntimeError(f"experiment terminal: {state.get('terminal_verdict')}")
    if state.get("baseline") is None:
        raise RuntimeError("inherited-A baseline missing")
    ps = pstate(state)
    if ps.open_researcher_call is None:
        raise RuntimeError("reserve a researcher call before discovery")
    require_clean(repo)
    candidate = git(repo, "rev-parse", candidate_arg)
    if candidate != git(repo, "rev-parse", "HEAD"):
        raise RuntimeError("candidate must be current clean HEAD")
    before = verify_protected(repo, state["protected_sha256"])
    if not before["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", before)
    configure_measurement_env(repo, cache)
    index = ps.discovery_evaluations + 1
    consume_measurement_attempt(state, evidence, f"b-discovery-{index:02d}")
    import receiver
    receipt_src = receiver.evaluate_candidate(repo, evidence, candidate)
    receipt_obj = read_json(receipt_src)
    decision = receipt_obj.get("payload", {}).get("decision")
    if decision not in {"ACCEPT", "REJECT"}:
        abort(state, evidence, "ABORT_EXECUTION_FAILURE", f"unexpected receiver decision {decision!r}")
    dest = copied_receipt(receipt_src, evidence / "receipts" / f"discovery-{index:02d}.json")
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
        "receipt": str(dest),
        "receipt_sha256": sha256_file(dest),
        "integrity_before": before,
        "integrity_after": after,
        "action": action,
    }
    state["discoveries"].append(row)
    save_pstate(state, ps)
    state["budget"]["researcher_calls"] = ps.researcher_calls

    if decision == "REJECT":
        accepted = receiver.status(repo, evidence).get("accepted_commit")
        state["accepted_commit"] = accepted
        git(repo, "branch", "-f", f"openline/live004-rejected-{index:02d}", candidate)
        git(repo, "reset", "--hard", str(accepted))
        if action == "STOP":
            state["terminal"] = True
            state["terminal_verdict"] = ps.terminal_verdict
            save_state(evidence, state)
            finalize(state, evidence)
        else:
            save_state(evidence, state)
    else:
        accepted = receiver.status(repo, evidence).get("accepted_commit")
        if accepted != state["accepted_commit"]:
            abort(state, evidence, "ABORT_EXECUTION_FAILURE", "accepted state moved before B confirmation")
        state["apparent_b_candidate"] = candidate
        state["apparent_b_discovery_receipt"] = str(dest)
        save_state(evidence, state)

    print(json.dumps({"status": "B_DISCOVERY_RECORDED", "candidate": candidate, "decision": decision, "action": action, "terminal_verdict": state.get("terminal_verdict")}, sort_keys=True))


def confirm(repo: Path, evidence: Path, cache: Path) -> None:
    import receiver
    state = load_state(evidence)
    check_budget(state, evidence)
    if state.get("terminal"):
        raise RuntimeError(f"experiment terminal: {state.get('terminal_verdict')}")
    ps = pstate(state)
    if ps.phase != "CONFIRMING_B" or not ps.apparent_b_candidate:
        raise RuntimeError("no apparent B awaiting confirmation")
    candidate = ps.apparent_b_candidate
    require_clean(repo)
    if git(repo, "rev-parse", "HEAD") != candidate:
        raise RuntimeError("confirmation requires exact apparent-B candidate as current HEAD")
    accepted_before = receiver.status(repo, evidence).get("accepted_commit")
    if accepted_before != state["accepted_commit"]:
        abort(state, evidence, "ABORT_EXECUTION_FAILURE", "accepted base moved before B confirmation")
    before = verify_protected(repo, state["protected_sha256"])
    if not before["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", before)
    configure_measurement_env(repo, cache)
    consume_measurement_attempt(state, evidence, "b-confirmation-first-apparent-win")
    receipt_src = receiver.evaluate_candidate(repo, evidence, candidate)
    receipt_obj = read_json(receipt_src)
    decision = receipt_obj.get("payload", {}).get("decision")
    if decision not in {"ACCEPT", "REJECT"}:
        abort(state, evidence, "ABORT_EXECUTION_FAILURE", f"unexpected B confirmation decision {decision!r}")
    dest = copied_receipt(receipt_src, evidence / "receipts" / "confirmation-01.json")
    action = protocol.record_confirmation(ps, candidate, decision)
    after = verify_protected(repo, state["protected_sha256"])
    if not after["ok"]:
        abort(state, evidence, "ABORT_INTEGRITY_FAILURE", after)
    state["confirmation"] = {
        "candidate_commit": candidate,
        "decision": decision,
        "evaluation": receipt_obj.get("payload", {}).get("evaluation"),
        "receipt": str(dest),
        "receipt_sha256": sha256_file(dest),
        "integrity_before": before,
        "integrity_after": after,
        "action": action,
    }
    save_pstate(state, ps)

    if action == "PROMOTE":
        promoted = receiver.promote(repo, evidence, dest, candidate)
        accepted = promoted.get("accepted_commit")
        if accepted != candidate:
            abort(state, evidence, "ABORT_EXECUTION_FAILURE", "receiver did not advance to confirmed B")
        state["accepted_commit"] = accepted
        protocol.record_promotion(ps, candidate)
        save_pstate(state, ps)
        state["terminal"] = True
        state["terminal_verdict"] = ps.terminal_verdict
    else:
        git(repo, "branch", "-f", "openline/live004-unconfirmed-apparent-b", candidate)
        git(repo, "reset", "--hard", str(state["accepted_commit"]))
        state["terminal"] = True
        state["terminal_verdict"] = ps.terminal_verdict

    save_state(evidence, state)
    finalize(state, evidence)
    print(json.dumps({"status": "TERMINAL", "candidate": candidate, "confirmation_decision": decision, "terminal_verdict": state["terminal_verdict"], "accepted_commit": state["accepted_commit"]}, sort_keys=True))


def finalize(state: dict[str, Any], evidence: Path) -> dict[str, Any]:
    ps = pstate(state)
    elapsed, spend = budget_values(state)
    state["budget"]["pod_wall_seconds_observed"] = round(elapsed, 3)
    state["budget"]["estimated_gpu_spend_usd"] = round(spend, 6)
    final_integrity = None
    repo_path = state.get("repo")
    if repo_path:
        try:
            final_integrity = verify_protected(Path(repo_path), state["protected_sha256"])
        except Exception as exc:
            final_integrity = {"ok": False, "reason": "FINAL_INTEGRITY_CHECK_ERROR", "detail": str(exc)}
    result = {
        "schema": RESULT_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "completed_at_utc": utc_now(),
        "terminal_verdict": state.get("terminal_verdict") or ps.terminal_verdict,
        "upstream_pin": state.get("upstream_pin"),
        "airlock_minimum_ancestor": state.get("airlock_minimum_ancestor"),
        "preregistration_sha256": state.get("preregistration_sha256"),
        "worker": state.get("worker"),
        "inheritance_record": state.get("inheritance_record"),
        "inherited_a_baseline": state.get("baseline"),
        "discoveries": state.get("discoveries"),
        "confirmation": state.get("confirmation"),
        "final_accepted_commit": state.get("accepted_commit"),
        "protocol": protocol.to_dict(ps),
        "budget": state.get("budget"),
        "protected_integrity_final": final_integrity,
        "claim_boundary": "exact A inheritance plus separately confirmed B can establish cumulative governed optimization; it does not establish recursive improvement, repeatability, independent-seed statistical superiority, worker identity attestation, or hostile-process isolation",
    }
    path = evidence / "AUTORESEARCH_LIVE_004_RESULT.json"
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
        "budget": state.get("budget"),
    }, sort_keys=True))


def self_test() -> None:
    prereg = read_json(PREREG)
    assert prereg["experiment_id"] == EXPERIMENT_ID
    assert prereg["lineage"]["required_inherited_a_commit"] == inheritance.INHERITED_A
    assert prereg["lineage"]["required_predecessor_baseline_commit"] == inheritance.PREDECESSOR_BASELINE
    assert prereg["upstream"]["commit"] == inheritance.UPSTREAM_PIN
    assert prereg["search_budget"]["maximum_researcher_calls"] == protocol.MAX_RESEARCHER_CALLS
    assert prereg["search_budget"]["maximum_discovery_evaluations"] == protocol.MAX_DISCOVERY_EVALUATIONS
    assert prereg["search_budget"]["maximum_confirmation_evaluations"] == protocol.MAX_CONFIRMATION_EVALUATIONS
    assert prereg["search_budget"]["maximum_receiver_measurements_including_inherited_a_baseline"] == MAX_RECEIVER_MEASUREMENTS
    assert prereg["search_budget"]["maximum_training_seconds"] == MAX_RECEIVER_MEASUREMENTS * TRAINING_SECONDS_PER_MEASUREMENT
    assert prereg["total_budget"]["maximum_pod_wall_seconds"] == MAX_POD_WALL_SECONDS
    assert float(prereg["total_budget"]["maximum_paid_gpu_spend_usd"]) == MAX_GPU_SPEND_USD
    ps = protocol.ProtocolState()
    try:
        protocol.begin_researcher_call(ps)
        raise AssertionError("search began before inheritance")
    except RuntimeError:
        pass
    protocol.record_inheritance(ps, inheritance.INHERITED_A)
    assert protocol.begin_researcher_call(ps) == 1
    assert protocol.record_discovery(ps, "b1", "ACCEPT") == "CONFIRM"
    assert protocol.record_confirmation(ps, "b1", "ACCEPT") == "PROMOTE"
    protocol.record_promotion(ps, "b1")
    assert ps.terminal_verdict == "CUMULATIVE_GOVERNED_OPTIMIZATION_PROMOTED"
    print(json.dumps({"status": "PASS_LIVE_004_STATIC_SELF_TEST"}, sort_keys=True))


def main() -> int:
    ap = argparse.ArgumentParser(description="AUTORESEARCH-LIVE-004 exact A inheritance + confirmed B driver")
    ap.add_argument("--repo", default="/workspace/autoresearch-live-004")
    ap.add_argument("--evidence", default="/workspace/autoresearch-live-004-evidence")
    ap.add_argument("--cache", default="/workspace/.cache/autoresearch")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--bundle", required=True)
    s.add_argument("--start-epoch", required=True, type=float)
    s.add_argument("--hourly-rate-usd", required=True, type=float)
    sub.add_parser("init")
    sub.add_parser("begin-call")
    a = sub.add_parser("abandon-call")
    a.add_argument("--reason", required=True)
    d = sub.add_parser("discover")
    d.add_argument("candidate")
    sub.add_parser("confirm")
    sub.add_parser("status")
    sub.add_parser("self-test")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    evidence = Path(args.evidence).resolve()
    cache = Path(args.cache).resolve()
    if args.command == "snapshot":
        snapshot(repo, evidence, Path(args.bundle), args.start_epoch, args.hourly_rate_usd)
        # Persist repo path only after snapshot succeeds.
        state = load_state(evidence)
        state["repo"] = str(repo)
        save_state(evidence, state)
    elif args.command == "init":
        init(repo, evidence, cache)
    elif args.command == "begin-call":
        begin_call(evidence)
    elif args.command == "abandon-call":
        abandon_call(evidence, args.reason)
    elif args.command == "discover":
        discover(repo, evidence, cache, args.candidate)
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
