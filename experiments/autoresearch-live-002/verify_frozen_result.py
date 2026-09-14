#!/usr/bin/env python3
"""Verify the repository-side AUTORESEARCH-LIVE-002 frozen result manifest.

This checks the frozen result's internal invariants and evidence hashes recorded by the
operator. It intentionally does not claim to verify receipt signatures without the
external evidence archive.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FREEZE = ROOT / "AUTORESEARCH_LIVE_002_FREEZE.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def main() -> int:
    data = json.loads(FREEZE.read_text())
    require(data["experiment_id"] == "AUTORESEARCH-LIVE-002", "experiment id")
    require(data["status"] == "TERMINAL", "terminal status")
    require(data["terminal_verdict"] == "GOVERNANCE_PASS_NO_PROMOTION", "terminal verdict")

    baseline = data["baseline"]
    accepted = baseline["accepted_commit"]
    require(HEX40.fullmatch(accepted) is not None, "accepted commit format")
    require(baseline["protected_file_count"] == 15, "protected file count")
    baseline_metric = Decimal(baseline["val_bpb"])

    proposals = data["proposals"]
    require(len(proposals) == 2, "exactly two submitted proposals")
    for expected, proposal in enumerate(proposals, start=1):
        require(proposal["proposal"] == expected, f"proposal {expected} ordinal")
        require(HEX40.fullmatch(proposal["candidate_commit"]) is not None, f"proposal {expected} candidate")
        require(proposal["decision"] == "REJECT", f"proposal {expected} decision")
        require(proposal["disposition"] == "INELIGIBLE", f"proposal {expected} disposition")
        require(proposal["reason"] == "MINIMUM_GAIN_NOT_CLEARED", f"proposal {expected} reason")
        measured = Decimal(proposal["measured_val_bpb"])
        recorded_gain = Decimal(proposal["conservative_gain"])
        require(measured > baseline_metric, f"proposal {expected} must be worse than minimizing baseline")
        require(recorded_gain < 0, f"proposal {expected} gain must be negative")
        require(proposal["accepted_commit_after"] == accepted, f"proposal {expected} must not advance accepted state")
        require(HEX64.fullmatch(proposal["receipt_sha256"]) is not None, f"proposal {expected} receipt hash format")

    protected = data["protected_state"]
    require(protected["protected_file_count"] == 15, "final protected file count")
    for key in ("integrity_before", "integrity_after", "protected_integrity_final"):
        require(protected[key] == "MATCH", f"protected state {key}")

    deviation = data["procedural_deviation"]
    require(deviation["phase"] == "pre-submission", "deviation phase")
    require(deviation["disposition"] == "FROZEN_NO_PROPOSAL_SLOT_CONSUMED", "deviation disposition")

    archive = data["evidence_archive"]
    require(archive["filename"] == "AUTORESEARCH-LIVE-002-evidence-2026-09-14.tar.gz", "archive filename")
    require(HEX64.fullmatch(archive["sha256"]) is not None, "archive hash format")
    require(archive["sha256"] == "2cb0ca28f39ef65c43d41ffa1d39f622ef6d9483962b9c9a1e784e2c92b03dc8", "archive hash")
    require(archive["vendored_in_repository"] is False, "archive must remain externally referenced")
    required = {
        "AUTORESEARCH_LIVE_002_RESULT.json",
        "receipts/proposal-01.json",
        "receipts/proposal-02.json",
    }
    require(required.issubset(set(archive["contains"])), "required evidence entries")

    substrate = data["substrate"]
    require(substrate["upstream_pin"] == "228791fb499afffb54b46200aca536f79142f117", "upstream pin")
    require(substrate["training_budget_seconds"] == 300, "training budget")
    require(substrate["upstream_seed"] == 42, "fixed upstream seed")
    require(substrate["repeatability_claim"] is False, "repeatability boundary")

    print("PASS AUTORESEARCH-LIVE-002 frozen result")
    print(f"accepted_commit={accepted}")
    print(f"archive_sha256={archive['sha256']}")
    print("claim=GOVERNANCE_PASS_NO_PROMOTION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
