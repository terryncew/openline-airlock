#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "dogfood" / "nightshift-cold-adoption-v040"
RECEIPT = EVIDENCE / "receipt.json"
REPORT = EVIDENCE / "report.json"
GENERATION = EVIDENCE / "generation-01.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify() -> tuple[dict, dict, dict]:
    receipt = load(RECEIPT)
    report = load(REPORT)
    generation = load(GENERATION)

    errors: list[str] = []
    evidence = receipt.get("evidence", {})

    if receipt.get("verdict") != "NIGHTSHIFT_COLD_ADOPTION_EARNED":
        errors.append("receipt verdict is not earned")
    if sha256(REPORT) != evidence.get("report_sha256"):
        errors.append("report SHA-256 mismatch")
    if sha256(GENERATION) != evidence.get("generation_receipt_sha256"):
        errors.append("generation SHA-256 mismatch")

    boundary = receipt.get("authority_boundary", {})
    for key in (
        "worker_state_controls_objective",
        "worker_state_controls_evaluator",
        "worker_state_controls_promotion",
    ):
        if boundary.get(key) is not False:
            errors.append(f"authority boundary failed: {key}")

    ns = receipt.get("nightshift", {})
    if ns.get("decision") != "UNIQUE_WINNER":
        errors.append("Nightshift decision was not UNIQUE_WINNER")
    if ns.get("accepted_generations") != 1:
        errors.append("expected exactly one accepted generation")
    if ns.get("starting_ref_updated_by_airlock") is not False:
        errors.append("starting ref was unexpectedly moved")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)

    return receipt, report, generation


def pause(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def line(text: str = "", pace: float = 0) -> None:
    print(text, flush=True)
    pause(pace)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify and replay the frozen Airlock v0.4.0 Nightshift cold-adoption receipt."
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        help="seconds to pause after each beat for screen recording",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify the frozen evidence and exit",
    )
    args = parser.parse_args()

    receipt, _report, generation = verify()

    if args.verify_only:
        print("NIGHTSHIFT_COLD_ADOPTION_EARNED")
        return 0

    target = receipt["outside_target"]
    worker = receipt["worker"]
    ns = receipt["nightshift"]
    boundary = receipt["authority_boundary"]
    candidate = generation["payload"]["candidates"][0]
    agent_tail = candidate["worker"]["agent_execution"].get("stdout_tail", "").strip().splitlines()
    implementation = agent_tail[0] if agent_tail else "Hermes produced a bounded candidate."

    line("$ python demo/nightshift-v040/show.py", args.pace)
    line("", args.pace / 2)
    line("AIRLOCK v0.4.0 — VERIFIED OUTSIDE-REPO NIGHTSHIFT", args.pace)
    line(f"target       {target['repository']} @ {target['frozen_commit'][:7]}", args.pace)
    line(f"baseline     {target['baseline_tests']['passed']} tests passed", args.pace)
    line("starter rules cold init, zero tuning", args.pace)
    line("", args.pace / 2)

    line(f"worker       Hermes @ {worker['source_commit'][:7]}", args.pace)
    line("generations  1 attempted", args.pace)
    line(f"change       {ns['diff']['changed_files']} file, {ns['diff']['changed_lines']} changed lines", args.pace)
    line(f"              {implementation}", args.pace)
    line("", args.pace / 2)

    line("Airlock reran the repository checks.", args.pace)
    line(f"objective    {ns['baseline_measurement']} -> {ns['final_measurement']} {ns['unit']}", args.pace)
    line(f"decision     {ns['decision']}", args.pace)
    line(f"candidate    {ns['candidate_disposition']} / {ns['candidate_reason']}", args.pace)
    line("", args.pace / 2)

    line("worker controls:", args.pace)
    line(f"  objective  {'YES' if boundary['worker_state_controls_objective'] else 'NO'}", args.pace)
    line(f"  evaluator  {'YES' if boundary['worker_state_controls_evaluator'] else 'NO'}", args.pace)
    line(f"  promotion  {'YES' if boundary['worker_state_controls_promotion'] else 'NO'}", args.pace)
    line(f"main moved   {'YES' if ns['starting_ref_updated_by_airlock'] else 'NO'}", args.pace)
    line("", args.pace / 2)

    line("NIGHTSHIFT_COLD_ADOPTION_EARNED", args.pace)
    line(f"receipt      {receipt['evidence']['generation_receipt_sha256'][:16]}…", 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
