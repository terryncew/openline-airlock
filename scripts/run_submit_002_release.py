#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from airlock_submit.opener import open_pr
from airlock_submit.seal import load_verified
from airlock_submit.store import Store
from airlock_submit.worker import process_one

FINAL = {"BLOCKED", "NEEDS_EVIDENCE", "SURVIVED", "PR_OPENED", "REOPEN", "ERROR"}


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_manifest(path: Path) -> dict:
    obj = json.loads(path.read_text())
    if obj.get("schema") != "airlock.submit.release.v1":
        raise SystemExit("manifest schema must be airlock.submit.release.v1")
    arms = obj.get("arms") or []
    if len(arms) != 3:
        raise SystemExit("release manifest must contain exactly three arms")
    names = {row.get("name") for row in arms}
    if names != {"survivor", "protected-cheat", "insufficient-evidence"}:
        raise SystemExit("arms must be named survivor, protected-cheat, insufficient-evidence")
    expected = {row["name"]: row.get("expected_decision") for row in arms}
    required = {
        "survivor": "SURVIVED",
        "protected-cheat": "BLOCKED",
        "insufficient-evidence": "NEEDS_EVIDENCE",
    }
    if expected != required:
        raise SystemExit(f"expected decisions must be frozen as {required}")
    for row in arms:
        if not row.get("submission_id"):
            raise SystemExit(f"{row['name']} is missing submission_id")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the frozen three-arm Airlock public-contribution release gate")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--config", type=Path, default=Path(".airlock/submit.json"))
    ap.add_argument("--db", type=Path, default=Path(".airlock/submit.sqlite3"))
    ap.add_argument("--data", type=Path, default=Path(".airlock/submit-data"))
    ap.add_argument("--report", type=Path, default=Path("airlock-submit-002-release-report.json"))
    ap.add_argument("--open-survivor-pr", action="store_true")
    ap.add_argument("--cap-proof", type=Path, help="JSON emitted by scripts/probe_submit_caps.py")
    ap.add_argument("--require-cap-proof", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("AIRLOCK_EVALUATION_KEY", "")
    if not key:
        raise SystemExit("AIRLOCK_EVALUATION_KEY is required")

    manifest = load_manifest(args.manifest)
    manifest_sha = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    by_id = {row["submission_id"]: row for row in manifest["arms"]}

    store = Store(args.db)
    try:
        for sid, arm in by_id.items():
            row = store.get(sid)
            if row["state"] not in {"QUEUED", "EVALUATING"}:
                raise SystemExit(f"{arm['name']} must be queued before release run; got {row['state']}")
            if arm.get("source_sha") and arm["source_sha"] != row["source_sha"]:
                raise SystemExit(f"{arm['name']} source SHA differs from preregistered manifest")
            if arm.get("base_sha") and arm["base_sha"] != row["base_sha"]:
                raise SystemExit(f"{arm['name']} base SHA differs from preregistered manifest")
    finally:
        store.close()

    remaining = set(by_id)
    while remaining:
        row = process_one(config_path=args.config, db_path=args.db, data_dir=args.data)
        if row is None:
            raise SystemExit("queue emptied before all preregistered arms were evaluated")
        if row["id"] in remaining and row["state"] in FINAL:
            remaining.remove(row["id"])

    results = {}
    store = Store(args.db)
    try:
        for sid, arm in by_id.items():
            row = store.get(sid)
            expected = arm["expected_decision"]
            if row["state"] != expected:
                raise SystemExit(f"{arm['name']} expected {expected}, got {row['state']}")
            if not row.get("artifact_dir"):
                raise SystemExit(f"{arm['name']} has no artifact directory")
            outcome_path = Path(row["artifact_dir"]) / "outcome.json"
            outcome = load_verified(outcome_path, key)
            if outcome.get("decision") != expected:
                raise SystemExit(f"{arm['name']} signed outcome disagrees with database state")
            if arm["name"] == "protected-cheat":
                if outcome.get("execution_attempted"):
                    raise SystemExit("protected-cheat reached execution; protected-file preflight failed")
                if not outcome.get("protected_touches"):
                    raise SystemExit("protected-cheat did not record the protected path it touched")
            if arm["name"] != "survivor" and row.get("detail", {}).get("pr_url"):
                raise SystemExit(f"{arm['name']} unexpectedly has a PR URL")
            results[arm["name"]] = {
                "submission_id": sid,
                "state": row["state"],
                "base_sha": row["base_sha"],
                "source_sha": row["source_sha"],
                "outcome": str(outcome_path),
                "outcome_sha256": hashlib.sha256(outcome_path.read_bytes()).hexdigest(),
                "execution_attempted": bool(outcome.get("execution_attempted")),
                "reason": outcome.get("reason"),
            }
    finally:
        store.close()

    if args.open_survivor_pr:
        sid = next(row["submission_id"] for row in manifest["arms"] if row["name"] == "survivor")
        pr = open_pr(submission_id=sid, config_path=args.config, db_path=args.db, evaluation_key=key)
        if pr.get("state") == "REOPEN":
            raise SystemExit("base moved after evaluation; survivor correctly REOPENed and requires a fresh submission")
        if pr.get("state") != "PR_OPENED":
            raise SystemExit(f"survivor did not open a PR: {pr}")
        results["survivor"]["pr_url"] = pr["pr_url"]
        results["survivor"]["receipt"] = pr["receipt"]
        results["survivor"]["receipt_sha256"] = pr["receipt_sha256"]

    cap_proof = None
    if args.cap_proof:
        cap_proof = json.loads(args.cap_proof.read_text())
        if cap_proof.get("schema") != "airlock.submit.cap-proof.v1" or not cap_proof.get("passed"):
            raise SystemExit("cap proof is missing, malformed, or failed")
    if args.require_cap_proof and cap_proof is None:
        raise SystemExit("--require-cap-proof was set but no passing cap proof was supplied")

    report = {
        "schema": "airlock.submit.release.report.v1",
        "manifest_sha256": manifest_sha,
        "release_gate": "AIRLOCK-SUBMIT-002",
        "checks": {
            "protected_cheat_rejected_before_execution": True,
            "blocked_arm_created_no_pr": True,
            "insufficient_evidence_arm_created_no_pr": True,
            "all_three_arms_have_signed_outcomes": True,
            "survivor_pr_requested": bool(args.open_survivor_pr),
            "spam_controls_live_probe": bool(cap_proof),
        },
        "cap_proof": cap_proof,
        "arms": results,
    }
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
