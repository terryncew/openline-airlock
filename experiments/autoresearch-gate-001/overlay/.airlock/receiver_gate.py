#!/usr/bin/env python3
"""Receiver-owned keep/discard gate for pinned karpathy/autoresearch.

The generator may create candidate commits. This controller owns measurement,
decision receipts, and the `openline/accepted` ref. It intentionally does not
claim hostile-process isolation; it proves an independently computed protocol
path and exact evidence binding.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time
import uuid

from airlock.config import load as load_config
from airlock.improvement import evaluate_survivor, load_objective, measure_commit
from airlock.util import sha256_file, write_json
from airlock.verification import ensure_key, sign, verify_signature

SCHEMA = "openline.autoresearch.receiver-decision.v1"
STATE_SCHEMA = "openline.autoresearch.receiver-state.v1"
ACCEPTED_REF = "refs/heads/openline/accepted"
ALLOWED_PATH = "train.py"


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout.strip()


def common_git_dir(repo: Path) -> Path:
    value = git(repo, "rev-parse", "--git-common-dir")
    path = Path(value)
    return (path if path.is_absolute() else repo / path).resolve()


def receiver_home(repo: Path) -> Path:
    path = common_git_dir(repo) / "openline-autoresearch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(repo: Path) -> Path:
    return receiver_home(repo) / "state.json"


def key_path(repo: Path) -> Path:
    return receiver_home(repo) / "verification.key"


def receipts_dir(repo: Path) -> Path:
    path = receiver_home(repo) / "receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def upstream_manifest(repo: Path) -> dict:
    return load_json(repo / ".airlock" / "autoresearch-upstream.json")


def verify_upstream_immutables(repo: Path, commit: str) -> dict:
    manifest = upstream_manifest(repo)
    pin = manifest["commit"]
    if subprocess.run(["git", "merge-base", "--is-ancestor", pin, commit], cwd=repo).returncode != 0:
        raise RuntimeError(f"candidate is not descended from pinned autoresearch commit {pin}")
    checked = []
    for path, expected_blob in sorted(manifest["immutable_blobs"].items()):
        actual = git(repo, "rev-parse", f"{commit}:{path}")
        if actual != expected_blob:
            raise RuntimeError(f"immutable upstream path changed: {path}")
        checked.append({"path": path, "blob": actual})
    return {"upstream_pin": pin, "checked": checked}


def changed_paths(repo: Path, base: str, candidate: str) -> list[str]:
    out = git(repo, "diff", "--name-only", f"{base}..{candidate}")
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def require_candidate_scope(repo: Path, base: str, candidate: str) -> list[str]:
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, candidate], cwd=repo).returncode != 0:
        raise RuntimeError("candidate does not descend from receiver-accepted base")
    if candidate == base:
        raise RuntimeError("candidate equals accepted base")
    paths = changed_paths(repo, base, candidate)
    if paths != [ALLOWED_PATH]:
        raise RuntimeError(f"autoresearch scope requires exactly ['{ALLOWED_PATH}']; observed {paths}")
    verify_upstream_immutables(repo, candidate)
    return paths


def load_state(repo: Path) -> dict:
    path = state_path(repo)
    if not path.is_file():
        raise RuntimeError("receiver is not initialized; run: python .airlock/receiver_gate.py init")
    state = load_json(path)
    if state.get("schema") != STATE_SCHEMA:
        raise RuntimeError("unsupported receiver state schema")
    return state


def save_state(repo: Path, state: dict) -> None:
    write_json(state_path(repo), state)


def build_receipt_payload(
    repo: Path,
    *,
    base: str,
    candidate: str,
    paths: list[str],
    baseline: dict,
    evaluation: dict,
) -> dict:
    objective_path = repo / ".airlock" / "objective.json"
    config_path = repo / ".airlock" / "config.json"
    decision = "ACCEPT" if evaluation.get("disposition") == "ELIGIBLE" else "REJECT"
    return {
        "schema": SCHEMA,
        "upstream_pin": upstream_manifest(repo)["commit"],
        "base_commit": base,
        "candidate_commit": candidate,
        "candidate_tree": git(repo, "rev-parse", f"{candidate}^{{tree}}"),
        "changed_paths": paths,
        "objective_sha256": sha256_file(objective_path),
        "config_sha256": sha256_file(config_path),
        "baseline": deepcopy(baseline),
        "evaluation": deepcopy(evaluation),
        "decision": decision,
        "score_source": "receiver-owned Airlock measurement; mutable train.py stdout is not authoritative",
        "claim_boundary": "repository-state gate; not hostile-process isolation",
    }


def write_signed_receipt(repo: Path, payload: dict) -> Path:
    key = ensure_key(key_path(repo))
    record = sign(payload, key)
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    path = receipts_dir(repo) / f"decision-{stamp}.json"
    write_json(path, record)
    return path


def verify_receipt_binding(
    repo: Path,
    record: dict,
    *,
    expected_base: str,
    expected_candidate: str | None = None,
) -> dict:
    key = key_path(repo).read_bytes()
    if not verify_signature(record, key):
        raise RuntimeError("decision receipt signature invalid")
    payload = record.get("payload", {})
    if payload.get("schema") != SCHEMA:
        raise RuntimeError("decision receipt schema invalid")
    if payload.get("base_commit") != expected_base:
        raise RuntimeError("decision receipt base binding mismatch")
    candidate = payload.get("candidate_commit")
    if not isinstance(candidate, str):
        raise RuntimeError("decision receipt missing candidate")
    if expected_candidate is not None and candidate != expected_candidate:
        raise RuntimeError("decision receipt candidate binding mismatch")
    if payload.get("upstream_pin") != upstream_manifest(repo)["commit"]:
        raise RuntimeError("decision receipt upstream binding mismatch")
    actual_paths = require_candidate_scope(repo, expected_base, candidate)
    if actual_paths != payload.get("changed_paths"):
        raise RuntimeError("decision receipt changed-path binding mismatch")
    if payload.get("objective_sha256") != sha256_file(repo / ".airlock" / "objective.json"):
        raise RuntimeError("decision receipt objective binding mismatch")
    if payload.get("config_sha256") != sha256_file(repo / ".airlock" / "config.json"):
        raise RuntimeError("decision receipt config binding mismatch")
    return payload


def initialize(repo: Path) -> dict:
    repo = repo.resolve()
    head = git(repo, "rev-parse", "HEAD")
    verify_upstream_immutables(repo, head)
    manifest = upstream_manifest(repo)
    original_train_blob = manifest.get("initial_train_blob")
    if original_train_blob and git(repo, "rev-parse", f"{head}:train.py") != original_train_blob:
        raise RuntimeError("receiver init must start from the pinned upstream train.py")
    if state_path(repo).exists():
        raise RuntimeError("receiver already initialized")

    objective = load_objective(repo / ".airlock" / "objective.json")
    baseline = measure_commit(repo, head, objective)
    if baseline.get("status") != "MEASURED":
        raise RuntimeError(f"baseline measurement failed: {baseline.get('reason')}")

    # Receiver-owned ref starts at the operator bootstrap commit. CAS promotion
    # below is the only protocol path that advances it.
    git(repo, "update-ref", ACCEPTED_REF, head)
    ensure_key(key_path(repo))
    state = {
        "schema": STATE_SCHEMA,
        "upstream_pin": manifest["commit"],
        "bootstrap_commit": head,
        "accepted_commit": head,
        "accepted_measurement": baseline,
        "last_receipt": None,
    }
    save_state(repo, state)
    return state


def evaluate_candidate(repo: Path, candidate: str) -> Path:
    repo = repo.resolve()
    state = load_state(repo)
    base = state["accepted_commit"]
    candidate = git(repo, "rev-parse", candidate)
    paths = require_candidate_scope(repo, base, candidate)
    objective = load_objective(repo / ".airlock" / "objective.json")
    config = load_config(repo / ".airlock" / "config.json")
    baseline = state["accepted_measurement"]
    row = {
        "candidate_id": "autoresearch-candidate",
        "commit": candidate,
        "changed_paths": paths,
        "disposition": "SURVIVED",
        "reason": "AUTORESEARCH_TRAIN_PY_ONLY",
        "agent_report": {},
    }
    evaluation = evaluate_survivor(
        repo,
        base=base,
        row=row,
        baseline=baseline,
        objective=objective,
        protected_paths=list(config.get("protected_paths", [])),
        objective_relative_path=".airlock/objective.json",
    )
    payload = build_receipt_payload(
        repo,
        base=base,
        candidate=candidate,
        paths=paths,
        baseline=baseline,
        evaluation=evaluation,
    )
    return write_signed_receipt(repo, payload)


def promote(repo: Path, receipt_path: Path, expected_candidate: str | None = None) -> dict:
    repo = repo.resolve()
    state = load_state(repo)
    record = load_json(receipt_path)
    expected = None if expected_candidate is None else git(repo, "rev-parse", expected_candidate)
    payload = verify_receipt_binding(
        repo,
        record,
        expected_base=state["accepted_commit"],
        expected_candidate=expected,
    )
    if payload.get("decision") != "ACCEPT":
        raise RuntimeError("receiver receipt does not authorize promotion")
    evaluation = payload.get("evaluation", {})
    if evaluation.get("disposition") != "ELIGIBLE" or evaluation.get("reason") != "OBJECTIVE_CLEARED":
        raise RuntimeError("receipt does not contain an eligible receiver evaluation")
    candidate = payload["candidate_commit"]
    base = state["accepted_commit"]
    # Compare-and-swap: a stale/replayed receipt cannot move a newer accepted ref.
    git(repo, "update-ref", ACCEPTED_REF, candidate, base)
    state["accepted_commit"] = candidate
    state["accepted_measurement"] = evaluation["measurement"]
    state["last_receipt"] = str(receipt_path.resolve())
    save_state(repo, state)
    return state


def status(repo: Path) -> dict:
    state = load_state(repo)
    state = deepcopy(state)
    state["accepted_ref"] = git(repo, "rev-parse", ACCEPTED_REF)
    return state


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OpenLine receiver gate for karpathy/autoresearch")
    p.add_argument("--repo", default=".")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("init")
    ev = sub.add_parser("evaluate")
    ev.add_argument("candidate")
    pr = sub.add_parser("promote")
    pr.add_argument("receipt")
    pr.add_argument("--candidate")
    st = sub.add_parser("step")
    st.add_argument("candidate")
    sub.add_parser("status")
    return p


def main() -> int:
    args = _parser().parse_args()
    repo = Path(args.repo).resolve()
    if args.command == "verify":
        head = git(repo, "rev-parse", "HEAD")
        print(json.dumps(verify_upstream_immutables(repo, head), sort_keys=True))
        return 0
    if args.command == "init":
        print(json.dumps(initialize(repo), sort_keys=True))
        return 0
    if args.command == "evaluate":
        path = evaluate_candidate(repo, args.candidate)
        record = load_json(path)
        print(json.dumps({"receipt": str(path), "decision": record["payload"]["decision"]}, sort_keys=True))
        return 0
    if args.command == "promote":
        state = promote(repo, Path(args.receipt), args.candidate)
        print(json.dumps({"accepted_commit": state["accepted_commit"]}, sort_keys=True))
        return 0
    if args.command == "step":
        path = evaluate_candidate(repo, args.candidate)
        record = load_json(path)
        if record["payload"]["decision"] == "ACCEPT":
            state = promote(repo, path, args.candidate)
            print(json.dumps({"receipt": str(path), "decision": "ACCEPT", "accepted_commit": state["accepted_commit"]}, sort_keys=True))
        else:
            print(json.dumps({"receipt": str(path), "decision": "REJECT", "accepted_commit": load_state(repo)["accepted_commit"]}, sort_keys=True))
        return 0
    if args.command == "status":
        print(json.dumps(status(repo), sort_keys=True))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
