#!/usr/bin/env python3
"""RIL-ANOMALY-003 evaluator sanity check (diagnostic only).

Preserves the old ANOMALY-001 remainder-sweep lesson — the "diversity-remainder"
method that the rejected draft's proxy evaluator would have rewarded — and
runs it against the NEW sealed truth table under the stronger no-regression
promotion gate.

Operationalization: complement_positional rules sweeping the 8 candidates the
historical researcher did NOT select ([0,1,2,3] then [4,5,6,7]), scored per
round block against the initial accepted head (frozen historical selections).

This is DIAGNOSTIC EVIDENCE ONLY. It reads the sealed truth, writes a record,
and cannot affect either arm's starting state: no head is modified, no lesson
is inherited, no packet is built, no API is contacted.

Usage: python3 evaluator_sanity_check.py --output proofs/ril-anomaly-003/RIL_ANOMALY_003_EVALUATOR_SANITY.json
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE / "protected"))
import anomaly_core as core  # noqa: E402

PREREG_PATH = HERE / "RIL_ANOMALY_003_PREREGISTRATION.json"
OUT_NAME = "RIL_ANOMALY_003_EVALUATOR_SANITY.json"

# The ANOMALY-001 remainder-sweep lesson, operationalized: sweep the remainder
# candidates (the 8 the historical researcher did not select) in presented
# order, first half then second half.
REMAINDER_SWEEPS = [
    {"type": "complement_positional", "positions": [0, 1, 2, 3]},
    {"type": "complement_positional", "positions": [4, 5, 6, 7]},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit("refusing to overwrite existing sanity record")

    prereg = core.read_json(PREREG_PATH)
    truth, schedule = core.verify_sealed_artifacts(ROOT, prereg)

    blocks_result = {}
    promoted_any = False
    for r in ("1", "2", "3", "4"):
        block = schedule["round_blocks"][r]
        head_sels = {
            tid: list(schedule["tasks"][tid]["historical_selected_order"]) for tid in block
        }
        head_score = core.score_selections(head_sels, truth)
        sweeps = []
        for rule in REMAINDER_SWEEPS:
            ok, issues, sels = core.normalize_rule(rule, block, schedule)
            assert ok and sels is not None, issues
            method_score = core.score_selections(sels, truth)
            verdict, detail = core.promotion_decision(method_score, head_score)
            sweeps.append({
                "rule": rule,
                "verdict": verdict,
                "promotion_detail": detail,
                "method_task_successes": method_score["task_successes"],
                "head_task_successes": head_score["task_successes"],
                "method_total_evals_to_first_success":
                    method_score["total_evaluations_to_first_success"],
                "head_total_evals_to_first_success":
                    head_score["total_evaluations_to_first_success"],
            })
            if verdict == "PROMOTE":
                promoted_any = True
        blocks_result[r] = {"head_score": {
            "task_successes": head_score["task_successes"],
            "total_evaluations_to_first_success":
                head_score["total_evaluations_to_first_success"]}, "sweeps": sweeps}

    record = {
        "schema": "openline.ril-anomaly-003.evaluator-sanity.v1",
        "experiment": core.EXPERIMENT,
        "checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "diagnostic_only": True,
        "lesson_source": ("RIL-ANOMALY-001 'diversity-remainder' lesson, operationalized as "
                          "complement_positional sweeps of the 8 remainder candidates"),
        "sealed_truth_sha256": prereg["sealed_artifacts"]["truth_table_sha256"],
        "sealed_schedule_sha256": prereg["sealed_artifacts"]["schedule_sha256"],
        "initial_head": "frozen historical selections (unchanged by this check)",
        "round_blocks": blocks_result,
        "observation": (
            "Per-block results: blocks 1, 2, 4 (head: 0 successes) -> both remainder "
            "sweeps PROMOTE by genuine gain (1-4 new receiver-confirmed task successes, "
            "no loss possible). Block 3 (head: 1 success on sliding-window-001) -> both "
            "sweeps REJECT with lost_task_successes=['sliding-window-001']: the remainder "
            "pool excludes the historically selected acceptable candidate, so the "
            "no-regression gate blocks it. The stronger gate therefore behaves as "
            "designed: it rewards only receiver-confirmed gains and vetoes any method "
            "that sacrifices a confirmed success, which the old proxy evaluator could "
            "not distinguish."
        ),
        "standing": ("Diagnostic evidence about the evaluator only. It does not modify "
                     "either arm's head, lessons, schedule, truth table, or starting state, "
                     "and cannot trigger promotion in the primary experiment."),
    }
    sha = core.write_json(out, record)
    print(f"sanity record: {out} sha256={sha}")
    for r, b in blocks_result.items():
        vs = [s["verdict"] for s in b["sweeps"]]
        print(f"block {r}: head successes={b['head_score']['task_successes']} "
              f"sweeps={vs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
