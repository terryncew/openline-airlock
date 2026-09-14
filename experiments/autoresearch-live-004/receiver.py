from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time
import uuid
from typing import Any

from airlock.config import load as load_config
from airlock.improvement import evaluate_survivor, load_objective, measure_commit
from airlock.util import sha256_file, write_json
from airlock.verification import ensure_key, sign, verify_signature

from inheritance import INHERITED_A, UPSTREAM_PIN

SCHEMA = "openline.autoresearch.live004-receiver-decision.v1"
STATE_SCHEMA = "openline.autoresearch.live004-receiver-state.v1"
ACCEPTED_REF = "refs/heads/openline/accepted-live004"
ALLOWED_PATH = "train.py"


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def receiver_dir(evidence: Path) -> Path:
    path = evidence / "receiver"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(evidence: Path) -> Path:
    return receiver_dir(evidence) / "state.json"


def key_path(evidence: Path) -> Path:
    return receiver_dir(evidence) / "verification.key"


def receipts_dir(evidence: Path) -> Path:
    path = receiver_dir(evidence) / "receipts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_state(evidence: Path) -> dict[str, Any]:
    state = read_json(state_path(evidence))
    if state.get("schema") != STATE_SCHEMA:
        raise RuntimeError("unsupported LIVE-004 receiver state")
    return state


def save_state(evidence: Path, state: dict[str, Any]) -> None:
    write_json(state_path(evidence), state)


def upstream_manifest(repo: Path) -> dict[str, Any]:
    return read_json(repo / ".airlock" / "autoresearch-upstream.json")


def verify_upstream_immutables(repo: Path, commit: str) -> dict[str, Any]:
    manifest = upstream_manifest(repo)
    if manifest.get("commit") != UPSTREAM_PIN:
        raise RuntimeError("unexpected autoresearch upstream pin")
    if subprocess.run(["git", "merge-base", "--is-ancestor", UPSTREAM_PIN, commit], cwd=repo).returncode:
        raise RuntimeError("candidate does not descend from pinned upstream")
    checked: list[dict[str, str]] = []
    for path, expected_blob in sorted(manifest["immutable_blobs"].items()):
        actual = git(repo, "rev-parse", f"{commit}:{path}")
        if actual != expected_blob:
            raise RuntimeError(f"immutable upstream path changed: {path}")
        checked.append({"path": path, "blob": actual})
    return {"upstream_pin": UPSTREAM_PIN, "checked": checked}


def changed_paths(repo: Path, base: str, candidate: str) -> list[str]:
    return sorted(x for x in git(repo, "diff", "--name-only", f"{base}..{candidate}").splitlines() if x)


def require_candidate_scope(repo: Path, base: str, candidate: str) -> list[str]:
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, candidate], cwd=repo).returncode:
        raise RuntimeError("candidate does not descend from receiver-accepted base")
    if candidate == base:
        raise RuntimeError("candidate equals accepted base")
    paths = changed_paths(repo, base, candidate)
    if paths != [ALLOWED_PATH]:
        raise RuntimeError(f"LIVE-004 scope requires exactly ['{ALLOWED_PATH}']; observed {paths}")
    verify_upstream_immutables(repo, candidate)
    return paths


def initialize(repo: Path, evidence: Path, inheritance_record: dict[str, Any]) -> dict[str, Any]:
    repo = repo.resolve()
    head = git(repo, "rev-parse", "HEAD")
    if head != INHERITED_A:
        raise RuntimeError(f"receiver init requires exact inherited A at HEAD; observed {head}")
    if inheritance_record.get("inherited_a_commit") != INHERITED_A:
        raise RuntimeError("inheritance record does not bind exact A")
    if state_path(evidence).exists():
        raise RuntimeError("LIVE-004 receiver already initialized")
    verify_upstream_immutables(repo, head)
    objective = load_objective(repo / ".airlock" / "objective.json")
    baseline = measure_commit(repo, head, objective)
    if baseline.get("status") != "MEASURED":
        raise RuntimeError(f"inherited-A baseline measurement failed: {baseline.get('reason')}")
    git(repo, "update-ref", ACCEPTED_REF, head)
    ensure_key(key_path(evidence))
    state = {
        "schema": STATE_SCHEMA,
        "upstream_pin": UPSTREAM_PIN,
        "inherited_a_commit": INHERITED_A,
        "inheritance_record_sha256": sha256_file(evidence / "INHERITED_A.json"),
        "accepted_commit": head,
        "accepted_measurement": baseline,
        "last_receipt": None,
    }
    save_state(evidence, state)
    return state


def build_receipt_payload(repo: Path, evidence: Path, *, base: str, candidate: str, paths: list[str], baseline: dict, evaluation: dict) -> dict:
    objective_path = repo / ".airlock" / "objective.json"
    config_path = repo / ".airlock" / "config.json"
    decision = "ACCEPT" if evaluation.get("disposition") == "ELIGIBLE" else "REJECT"
    return {
        "schema": SCHEMA,
        "experiment_id": "AUTORESEARCH-LIVE-004",
        "upstream_pin": UPSTREAM_PIN,
        "inherited_a_commit": INHERITED_A,
        "inheritance_record_sha256": sha256_file(evidence / "INHERITED_A.json"),
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
        "claim_boundary": "repository-state gate over exact inherited A; not hostile-process isolation",
    }


def write_signed_receipt(evidence: Path, payload: dict[str, Any]) -> Path:
    key = ensure_key(key_path(evidence))
    record = sign(payload, key)
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    path = receipts_dir(evidence) / f"decision-{stamp}.json"
    write_json(path, record)
    return path


def evaluate_candidate(repo: Path, evidence: Path, candidate: str) -> Path:
    state = load_state(evidence)
    base = state["accepted_commit"]
    candidate = git(repo, "rev-parse", candidate)
    paths = require_candidate_scope(repo, base, candidate)
    objective = load_objective(repo / ".airlock" / "objective.json")
    config = load_config(repo / ".airlock" / "config.json")
    row = {
        "candidate_id": "autoresearch-live004-candidate",
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
        baseline=state["accepted_measurement"],
        objective=objective,
        protected_paths=list(config.get("protected_paths", [])),
        objective_relative_path=".airlock/objective.json",
    )
    payload = build_receipt_payload(
        repo,
        evidence,
        base=base,
        candidate=candidate,
        paths=paths,
        baseline=state["accepted_measurement"],
        evaluation=evaluation,
    )
    return write_signed_receipt(evidence, payload)


def verify_receipt_binding(repo: Path, evidence: Path, record: dict[str, Any], *, expected_base: str, expected_candidate: str) -> dict[str, Any]:
    key = key_path(evidence).read_bytes()
    if not verify_signature(record, key):
        raise RuntimeError("decision receipt signature invalid")
    payload = record.get("payload", {})
    if payload.get("schema") != SCHEMA:
        raise RuntimeError("decision receipt schema invalid")
    if payload.get("experiment_id") != "AUTORESEARCH-LIVE-004":
        raise RuntimeError("decision receipt experiment mismatch")
    if payload.get("inherited_a_commit") != INHERITED_A:
        raise RuntimeError("decision receipt inherited-A binding mismatch")
    if payload.get("inheritance_record_sha256") != sha256_file(evidence / "INHERITED_A.json"):
        raise RuntimeError("decision receipt inheritance-record binding mismatch")
    if payload.get("base_commit") != expected_base or payload.get("candidate_commit") != expected_candidate:
        raise RuntimeError("decision receipt exact base/candidate binding mismatch")
    actual_paths = require_candidate_scope(repo, expected_base, expected_candidate)
    if actual_paths != payload.get("changed_paths"):
        raise RuntimeError("decision receipt changed-path binding mismatch")
    if payload.get("objective_sha256") != sha256_file(repo / ".airlock" / "objective.json"):
        raise RuntimeError("decision receipt objective binding mismatch")
    if payload.get("config_sha256") != sha256_file(repo / ".airlock" / "config.json"):
        raise RuntimeError("decision receipt config binding mismatch")
    return payload


def promote(repo: Path, evidence: Path, receipt_path: Path, candidate: str) -> dict[str, Any]:
    state = load_state(evidence)
    candidate = git(repo, "rev-parse", candidate)
    record = read_json(receipt_path)
    payload = verify_receipt_binding(repo, evidence, record, expected_base=state["accepted_commit"], expected_candidate=candidate)
    if payload.get("decision") != "ACCEPT":
        raise RuntimeError("receiver receipt does not authorize promotion")
    evaluation = payload.get("evaluation", {})
    if evaluation.get("disposition") != "ELIGIBLE" or evaluation.get("reason") != "OBJECTIVE_CLEARED":
        raise RuntimeError("receipt does not contain an eligible receiver evaluation")
    base = state["accepted_commit"]
    git(repo, "update-ref", ACCEPTED_REF, candidate, base)
    state["accepted_commit"] = candidate
    state["accepted_measurement"] = evaluation["measurement"]
    state["last_receipt"] = str(receipt_path.resolve())
    save_state(evidence, state)
    return state


def status(repo: Path, evidence: Path) -> dict[str, Any]:
    state = deepcopy(load_state(evidence))
    state["accepted_ref"] = git(repo, "rev-parse", ACCEPTED_REF)
    return state
