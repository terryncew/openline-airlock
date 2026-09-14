#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any

EXPERIMENT_ID = "AUTORESEARCH-LIVE-002"
UPSTREAM_PIN = "228791fb499afffb54b46200aca536f79142f117"
MAX_PROPOSALS = 2
EVIDENCE_SCHEMA = "openline.autoresearch.live-state.v1"
RESULT_SCHEMA = "openline.autoresearch.live-result.v1"
WORKER_IDENTITY = {
    "provider": "Meta",
    "product": "Muse personal AI agent",
    "model": "Muse Spark 1.3",
    "worker_name": "Prince",
    "interface": "conversational agent with its own Linux VM; operates RunPod through delegated browser tasks driving the Jupyter interface",
    "attestation": "self-declared by the worker before preregistration; not independently verified by runtime",
    "delegation_rule": "delegated browser transport is permitted; research reasoning, candidate selection, and train.py authorship may not be delegated to another model or subagent",
}


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


def json_load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def json_write(path: Path, value: dict[str, Any]) -> None:
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
        raise RuntimeError("experiment worktree is not clean; receiver refuses evaluation:\n" + status)


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
    rows = [line.strip() for line in p.stdout.splitlines() if line.strip()]
    return {"available": True, "rows": rows}


def receiver_env(repo: Path, cache: Path) -> dict[str, str]:
    venv_bin = repo / ".venv" / "bin"
    python = venv_bin / "python"
    if not python.is_file():
        raise RuntimeError(f"autoresearch virtualenv missing: {python}")
    env = os.environ.copy()
    env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    env["AUTORESEARCH_HOST_CACHE"] = str(cache.resolve())
    env.setdefault("CUDA_VISIBLE_DEVICES", "0")
    return env


def receiver(repo: Path, cache: Path, *args: str) -> dict[str, Any]:
    env = receiver_env(repo, cache)
    python = str(repo / ".venv" / "bin" / "python")
    p = run([python, ".airlock/receiver_gate.py", *args], cwd=repo, env=env)
    lines = [line for line in p.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("receiver emitted no JSON")
    value = json.loads(lines[-1])
    if not isinstance(value, dict):
        raise RuntimeError("receiver final line is not a JSON object")
    return value


def load_state(evidence: Path) -> dict[str, Any]:
    path = evidence / "state.json"
    if not path.is_file():
        raise RuntimeError("live experiment state missing; run snapshot first")
    state = json_load(path)
    if state.get("schema") != EVIDENCE_SCHEMA:
        raise RuntimeError("unsupported live experiment state")
    return state


def save_state(evidence: Path, state: dict[str, Any]) -> None:
    json_write(evidence / "state.json", state)


def copy_receipt(src: Path, evidence: Path, index: int) -> Path:
    dest = evidence / "receipts" / f"proposal-{index:02d}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def prereg_path() -> Path:
    return Path(__file__).with_name("AUTORESEARCH_LIVE_002_PREREGISTRATION.json").resolve()


def require_preregistered_worker() -> None:
    prereg = json_load(prereg_path())
    worker = prereg.get("worker")
    if not isinstance(worker, dict):
        raise RuntimeError("preregistration worker block missing")
    frozen = {
        "provider": worker.get("provider"),
        "product": worker.get("product"),
        "model": worker.get("model"),
        "worker_name": worker.get("worker_name"),
        "interface": worker.get("interface"),
        "attestation": worker.get("identity_attestation"),
        "delegation_rule": worker.get("delegation_rule"),
    }
    if frozen != WORKER_IDENTITY:
        raise RuntimeError("runtime worker identity does not match preregistration")


def command_snapshot(repo: Path, evidence: Path) -> None:
    repo = repo.resolve()
    evidence = evidence.resolve()
    require_preregistered_worker()
    require_clean(repo)
    upstream = json_load(repo / ".airlock" / "autoresearch-upstream.json")
    if upstream.get("commit") != UPSTREAM_PIN:
        raise RuntimeError("unexpected autoresearch upstream pin")
    head = git(repo, "rev-parse", "HEAD")
    push_url = git(repo, "remote", "get-url", "--push", "origin", check=False)
    if not push_url.startswith("no_push://"):
        raise RuntimeError(f"experiment clone push is not disabled: {push_url!r}")
    protected = tracked_protected_hashes(repo)
    airlock_root = Path(__file__).resolve().parents[2]
    airlock_driver_commit = git(airlock_root, "rev-parse", "HEAD", check=False) if (airlock_root / ".git").exists() else None
    state: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": utc_now(),
        "repo": str(repo),
        "upstream_pin": UPSTREAM_PIN,
        "airlock_driver_commit": airlock_driver_commit,
        "bootstrap_commit": head,
        "bootstrap_tree": git(repo, "rev-parse", f"{head}^{{tree}}"),
        "push_url": push_url,
        "protected_sha256": protected,
        "preregistration_sha256": sha256_file(prereg_path()),
        "hardware": hardware(),
        "worker_identity": WORKER_IDENTITY,
        "baseline": None,
        "proposals": [],
        "terminal": False,
        "terminal_verdict": None,
    }
    json_write(evidence / "protected-snapshot.json", {
        "schema": "openline.autoresearch.protected-snapshot.v1",
        "experiment_id": EXPERIMENT_ID,
        "bootstrap_commit": head,
        "files": protected,
    })
    save_state(evidence, state)
    print(json.dumps({
        "status": "SNAPSHOT_FROZEN",
        "bootstrap_commit": head,
        "protected_files": len(protected),
        "hardware": state["hardware"],
        "worker_identity": state["worker_identity"],
    }, sort_keys=True))


def command_init(repo: Path, evidence: Path, cache: Path) -> None:
    state = load_state(evidence)
    if state.get("baseline") is not None:
        raise RuntimeError("baseline already measured")
    check = verify_protected(repo, state["protected_sha256"])
    if not check["ok"]:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_INTEGRITY_FAILURE"
        state["integrity_failure"] = check
        save_state(evidence, state)
        raise RuntimeError(f"protected integrity failed before baseline: {check}")
    result = receiver(repo, cache, "init")
    check_after = verify_protected(repo, state["protected_sha256"])
    if not check_after["ok"]:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_INTEGRITY_FAILURE"
        state["integrity_failure"] = check_after
        save_state(evidence, state)
        raise RuntimeError(f"protected integrity failed after baseline: {check_after}")
    state["baseline"] = result.get("accepted_measurement")
    state["accepted_commit"] = result.get("accepted_commit")
    state["baseline_completed_at_utc"] = utc_now()
    save_state(evidence, state)
    print(json.dumps({"status": "BASELINE_MEASURED", "accepted_commit": state["accepted_commit"], "baseline": state["baseline"]}, sort_keys=True))


def finalize_result(repo: Path, evidence: Path, state: dict[str, Any]) -> dict[str, Any]:
    final_integrity = verify_protected(repo, state["protected_sha256"])
    if not final_integrity["ok"]:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_INTEGRITY_FAILURE"
        state["integrity_failure"] = final_integrity
    result = {
        "schema": RESULT_SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "completed_at_utc": utc_now(),
        "terminal_verdict": state.get("terminal_verdict"),
        "upstream_pin": state.get("upstream_pin"),
        "airlock_driver_commit": state.get("airlock_driver_commit"),
        "bootstrap_commit": state.get("bootstrap_commit"),
        "preregistration_sha256": state.get("preregistration_sha256"),
        "hardware": state.get("hardware"),
        "worker_identity": state.get("worker_identity"),
        "push_url": state.get("push_url"),
        "baseline": state.get("baseline"),
        "proposals": state.get("proposals"),
        "final_accepted_commit": state.get("accepted_commit"),
        "protected_integrity_final": final_integrity,
        "claim_boundary": "receiver-owned fixed-seed governance observation with self-declared worker identity; not statistical ML superiority, worker-identity attestation, or hostile-process isolation",
    }
    result_path = evidence / "AUTORESEARCH_LIVE_002_RESULT.json"
    json_write(result_path, result)
    state["result_path"] = str(result_path)
    save_state(evidence, state)
    return result


def command_step(repo: Path, evidence: Path, cache: Path, candidate_arg: str) -> None:
    state = load_state(evidence)
    if state.get("baseline") is None:
        raise RuntimeError("baseline missing; run init first")
    if state.get("terminal"):
        raise RuntimeError(f"experiment already terminal: {state.get('terminal_verdict')}")
    proposals = list(state.get("proposals", []))
    if len(proposals) >= MAX_PROPOSALS:
        raise RuntimeError("proposal budget exhausted")
    require_clean(repo)
    candidate = git(repo, "rev-parse", candidate_arg)
    head = git(repo, "rev-parse", "HEAD")
    if candidate != head:
        raise RuntimeError(f"candidate must be current clean HEAD; candidate={candidate} HEAD={head}")
    check_before = verify_protected(repo, state["protected_sha256"])
    if not check_before["ok"]:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_INTEGRITY_FAILURE"
        state["integrity_failure"] = check_before
        save_state(evidence, state)
        raise RuntimeError(f"protected integrity failed before proposal: {check_before}")

    idx = len(proposals) + 1
    eval_result = receiver(repo, cache, "evaluate", candidate)
    receipt_src = Path(str(eval_result["receipt"]))
    receipt = json_load(receipt_src)
    payload = receipt.get("payload", {})
    decision = payload.get("decision")
    copied = copy_receipt(receipt_src, evidence, idx)
    proposal = {
        "index": idx,
        "candidate_commit": candidate,
        "candidate_tree": git(repo, "rev-parse", f"{candidate}^{{tree}}"),
        "train_blob": git(repo, "rev-parse", f"{candidate}:train.py"),
        "decision": decision,
        "evaluation": payload.get("evaluation"),
        "receipt": str(copied),
        "receipt_sha256": sha256_file(copied),
        "integrity_before": check_before,
    }

    if decision == "ACCEPT":
        promoted = receiver(repo, cache, "promote", str(receipt_src), "--candidate", candidate)
        state["accepted_commit"] = promoted.get("accepted_commit")
        state["terminal"] = True
        state["terminal_verdict"] = "GOVERNANCE_PASS_PROMOTION"
    elif decision == "REJECT":
        accepted = receiver(repo, cache, "status").get("accepted_commit")
        state["accepted_commit"] = accepted
        git(repo, "branch", "-f", f"openline/rejected-{idx}", candidate)
        git(repo, "reset", "--hard", str(accepted))
        if idx >= MAX_PROPOSALS:
            state["terminal"] = True
            state["terminal_verdict"] = "GOVERNANCE_PASS_NO_PROMOTION"
    else:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_EXECUTION_FAILURE"
        state["execution_failure"] = f"unexpected receiver decision: {decision!r}"

    check_after = verify_protected(repo, state["protected_sha256"])
    proposal["integrity_after"] = check_after
    proposals.append(proposal)
    state["proposals"] = proposals
    if not check_after["ok"]:
        state["terminal"] = True
        state["terminal_verdict"] = "ABORT_INTEGRITY_FAILURE"
        state["integrity_failure"] = check_after
    save_state(evidence, state)

    out: dict[str, Any] = {
        "status": "TERMINAL" if state["terminal"] else "PROPOSAL_REJECTED_CONTINUE",
        "proposal": idx,
        "decision": decision,
        "accepted_commit": state.get("accepted_commit"),
        "terminal_verdict": state.get("terminal_verdict"),
        "receipt": str(copied),
    }
    if state["terminal"]:
        result = finalize_result(repo, evidence, state)
        out["result"] = str(evidence / "AUTORESEARCH_LIVE_002_RESULT.json")
        out["terminal_verdict"] = result["terminal_verdict"]
    print(json.dumps(out, sort_keys=True))


def command_status(repo: Path, evidence: Path) -> None:
    state = load_state(evidence)
    check = verify_protected(repo, state["protected_sha256"])
    print(json.dumps({"state": state, "protected_integrity": check}, sort_keys=True))


def command_finalize(repo: Path, evidence: Path) -> None:
    state = load_state(evidence)
    if not state.get("terminal"):
        raise RuntimeError("experiment is not terminal")
    result = finalize_result(repo, evidence, state)
    print(json.dumps({"result": str(evidence / "AUTORESEARCH_LIVE_002_RESULT.json"), "terminal_verdict": result["terminal_verdict"]}, sort_keys=True))


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "OpenLine Test")
        git(repo, "config", "user.email", "test@example.invalid")
        (repo / "train.py").write_text("x=1\n")
        (repo / "prepare.py").write_text("fixed=1\n")
        (repo / ".airlock").mkdir()
        (repo / ".airlock" / "gate.py").write_text("gate=1\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "base")
        snap = tracked_protected_hashes(repo)
        assert verify_protected(repo, snap)["ok"]
        (repo / "train.py").write_text("x=2\n")
        git(repo, "add", "train.py")
        git(repo, "commit", "-qm", "candidate")
        assert verify_protected(repo, snap)["ok"]
        (repo / "prepare.py").write_text("fixed=2\n")
        assert not verify_protected(repo, snap)["ok"]
        git(repo, "checkout", "--", "prepare.py")
        (repo / "helper.py").write_text("escape=1\n")
        assert not verify_protected(repo, snap)["ok"]
    print(json.dumps({"self_test": "PASS"}))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="External live driver for AUTORESEARCH-LIVE-002")
    p.add_argument("--repo", default="/workspace/autoresearch-live-002")
    p.add_argument("--evidence", default="/workspace/autoresearch-live-002-evidence")
    p.add_argument("--cache", default="/workspace/.cache/autoresearch")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    sub.add_parser("init")
    step = sub.add_parser("step")
    step.add_argument("candidate")
    sub.add_parser("status")
    sub.add_parser("finalize")
    sub.add_parser("self-test")
    return p


def main() -> int:
    args = parser().parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    repo = Path(args.repo)
    evidence = Path(args.evidence)
    cache = Path(args.cache)
    if args.command == "snapshot":
        command_snapshot(repo, evidence)
    elif args.command == "init":
        command_init(repo, evidence, cache)
    elif args.command == "step":
        command_step(repo, evidence, cache, args.candidate)
    elif args.command == "status":
        command_status(repo, evidence)
    elif args.command == "finalize":
        command_finalize(repo, evidence)
    else:
        raise AssertionError(args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
