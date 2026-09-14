#!/usr/bin/env python3
"""RIL-ANOMALY-003 contract tests. Fully offline: no network, no credential.

Unit tests use synthetic schedules/truths. The sealed-artifact integration
checks (determinism, cross-validation, no-leakage on real packets) live in
`anomaly_driver.py self-check`.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "protected"))
import anomaly_core as core

FAILURES = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILURES.append(name)


def synth_schedule():
    # 4 tasks, 2 families x 2 tasks; 12 candidates each; presented order = c00..c11.
    tasks = {}
    fams = {"t-dedupe-0": "dedupe-stream", "t-dedupe-1": "dedupe-stream",
            "t-join-0": "normalized-join", "t-join-1": "normalized-join"}
    for tid, fam in fams.items():
        cids = [f"{tid}-c{i:02d}" for i in range(12)]
        tasks[tid] = {
            "family": fam,
            "presented_order": cids,
            "historical_selected_order": [cids[8], cids[6], cids[2], cids[1]],
        }
    return {"tasks": tasks,
            "round_blocks": {"1": ["t-dedupe-0", "t-join-0"],
                             "2": ["t-dedupe-1", "t-join-1"],
                             "3": [], "4": []}}


def synth_truth(accepted_map):
    # accepted_map: tid -> set of accepted cids
    tasks = {}
    for tid, acc in accepted_map.items():
        tasks[tid] = {"accepted": {f"{tid}-c{i:02d}": (f"{tid}-c{i:02d}" in acc)
                                  for i in range(12)}}
    return {"tasks": tasks}


BLOCK = ["t-dedupe-0", "t-join-0"]


def test_rule_explicit_ids_valid():
    s = synth_schedule()
    tid = "t-dedupe-0"
    ids = [f"{tid}-c{i:02d}" for i in (0, 3, 5, 11)]
    rule = {"type": "explicit_ids",
            "selections": {t: [f"{t}-c{i:02d}" for i in (0, 3, 5, 11)] for t in BLOCK}}
    ok, issues, sels = core.normalize_rule(rule, BLOCK, s)
    check("explicit_ids valid", ok and not issues and sels[tid] == ids)


def test_rule_positional_valid():
    s = synth_schedule()
    ok, issues, sels = core.normalize_rule({"type": "positional", "positions": [0, 3, 7, 11]}, BLOCK, s)
    tid = "t-dedupe-0"
    check("positional valid",
          ok and sels[tid] == [f"{tid}-c{i:02d}" for i in (0, 3, 7, 11)])


def test_rule_complement_positional_valid():
    s = synth_schedule()
    ok, issues, sels = core.normalize_rule(
        {"type": "complement_positional", "positions": [0, 1, 2, 3]}, BLOCK, s)
    tid = "t-dedupe-0"
    presented = [f"{tid}-c{i:02d}" for i in range(12)]
    hist = {f"{tid}-c{i:02d}" for i in (8, 6, 2, 1)}
    rest = [c for c in presented if c not in hist]
    check("complement_positional valid", ok and sels[tid] == rest[:4])


def test_rule_quarantine_cases():
    s = synth_schedule()
    tid = "t-dedupe-0"
    cases = {
        "unknown type": ({"type": "mystery"}, BLOCK),
        "non-dict rule": ("positional", BLOCK),
        "invented label": ({"type": "explicit_ids",
                            "selections": {t: ["A", "B", "C", "D"] for t in BLOCK}}, BLOCK),
        "id outside pool": ({"type": "explicit_ids",
                             "selections": {t: [f"{t}-c00", f"{t}-c01", f"{t}-c02", "deadbeef"] for t in BLOCK}}, BLOCK),
        "three ids": ({"type": "explicit_ids",
                       "selections": {t: [f"{t}-c{i:02d}" for i in (0, 1, 2)] for t in BLOCK}}, BLOCK),
        "duplicate ids": ({"type": "explicit_ids",
                           "selections": {t: [f"{t}-c00"] * 4 for t in BLOCK}}, BLOCK),
        "positional out of range": ({"type": "positional", "positions": [0, 1, 2, 12]}, BLOCK),
        "positional dupes": ({"type": "positional", "positions": [0, 1, 2, 2]}, BLOCK),
        "complement out of range": ({"type": "complement_positional", "positions": [0, 1, 2, 8]}, BLOCK),
        "missing block task": ({"type": "explicit_ids",
                                "selections": {"t-dedupe-0": [f"t-dedupe-0-c{i:02d}" for i in (0, 1, 2, 3)]}}, BLOCK),
    }
    for name, (rule, block) in cases.items():
        ok, issues, _ = core.normalize_rule(rule, block, s)
        check(f"quarantine: {name}", (not ok) and bool(issues))


def test_scoring_semantics():
    tid = "t-dedupe-0"
    truth = synth_truth({tid: {f"{tid}-c05"}, "t-join-0": set()})
    sels = {tid: [f"{tid}-c{i:02d}" for i in (0, 5, 9, 11)], "t-join-0": [f"t-join-0-c{i:02d}" for i in range(4)]}
    sc = core.score_selections(sels, truth)
    check("task success detected", sc["per_task"][tid]["found_acceptable"] is True)
    check("evals-to-first-success is ordered position",
          sc["per_task"][tid]["evaluations_to_first_success"] == 2)
    check("no-success task null", sc["per_task"]["t-join-0"]["evaluations_to_first_success"] is None)
    check("success count", sc["task_successes"] == 1)


def _scores(method_acc, head_acc):
    # helper: one task each; accepted sets determine found/evals
    tid = "t-dedupe-0"
    truth = synth_truth({tid: method_acc | head_acc})
    msel = {tid: [f"{tid}-c{i:02d}" for i in range(4)]}
    hsel = {tid: [f"{tid}-c{i:02d}" for i in range(4)]}
    # force which positions hold accepted candidates via ordering
    return truth, msel, hsel


def test_promotion_gain():
    tid = "t-dedupe-0"
    truth = synth_truth({tid: {f"{tid}-c01", f"{tid}-c03"}})
    msel = {tid: [f"{tid}-c{i:02d}" for i in (1, 4, 5, 6)]}   # success at position 1
    hsel = {tid: [f"{tid}-c{i:02d}" for i in (4, 5, 6, 7)]}   # no success
    v, d = core.promotion_decision(core.score_selections(msel, truth),
                                   core.score_selections(hsel, truth))
    check("gain of task success promotes", v == "PROMOTE" and d["reason"] == "gained_task_success")


def test_promotion_preserve_with_fewer_evals():
    tid = "t-dedupe-0"
    truth = synth_truth({tid: {f"{tid}-c05"}})
    msel = {tid: [f"{tid}-c{i:02d}" for i in (5, 0, 1, 2)]}   # success at position 1
    hsel = {tid: [f"{tid}-c{i:02d}" for i in (0, 1, 5, 2)]}   # success at position 3
    v, d = core.promotion_decision(core.score_selections(msel, truth),
                                   core.score_selections(hsel, truth))
    check("preserve + fewer evals promotes",
          v == "PROMOTE" and d["reason"] == "preserved_successes_reduced_evaluations")


def test_promotion_no_loss_required():
    t1, t2 = "t-dedupe-0", "t-join-0"
    truth = synth_truth({t1: {f"{t1}-c00"}, t2: {f"{t2}-c00"}})
    msel = {t1: [f"{t1}-c{i:02d}" for i in (4, 5, 6, 7)],     # loses head's success
            t2: [f"{t2}-c{i:02d}" for i in (0, 1, 2, 3)]}     # gains one
    hsel = {t1: [f"{t1}-c{i:02d}" for i in (0, 1, 2, 3)],
            t2: [f"{t2}-c{i:02d}" for i in (4, 5, 6, 7)]}
    v, d = core.promotion_decision(core.score_selections(msel, truth),
                                   core.score_selections(hsel, truth))
    check("lost head success rejects even with equal count",
          v == "REJECT" and d["lost_task_successes"] == [t1])


def test_promotion_tie_no_improvement_rejects():
    tid = "t-dedupe-0"
    truth = synth_truth({tid: {f"{tid}-c05"}})
    same = [f"{tid}-c{i:02d}" for i in (0, 1, 5, 2)]
    v, _ = core.promotion_decision(core.score_selections({tid: same}, truth),
                                   core.score_selections({tid: same}, truth))
    check("identical method rejects", v == "REJECT")


def test_promotion_zero_zero_rejects():
    tid = "t-dedupe-0"
    truth = synth_truth({tid: set()})
    same = [f"{tid}-c{i:02d}" for i in range(4)]
    v, _ = core.promotion_decision(core.score_selections({tid: same}, truth),
                                   core.score_selections({tid: same}, truth))
    check("zero vs zero rejects", v == "REJECT")


def test_no_proxy_in_scoring():
    # Scoring uses only acceptance + order; remainder coverage is not consulted.
    tid = "t-dedupe-0"
    truth = synth_truth({tid: {f"{tid}-c08"}})  # historical pick, also acceptable
    hist = [f"{tid}-c{i:02d}" for i in (8, 6, 2, 1)]
    sc = core.score_selections({tid: hist}, truth)
    check("historical selection scored on acceptance, not coverage",
          sc["per_task"][tid]["found_acceptable"] is True
          and sc["per_task"][tid]["evaluations_to_first_success"] == 1)


def test_packet_has_no_truth():
    s = synth_schedule()
    public_contexts = {t: {"family": s["tasks"][t]["family"]} for t in s["tasks"]}
    candidate_public = {t: {c: {"description": "d", "features": {}} for c in s["tasks"][t]["presented_order"]}
                        for t in s["tasks"]}
    head = {"per_block": {"1": {t: list(s["tasks"][t]["historical_selected_order"])
                                for t in ["t-dedupe-0", "t-join-0"]}}}
    packet = core.build_packet("anomaly_interview", 1, s, head,
                               {"accepted_lessons": [], "round_outcomes": []},
                               public_contexts, candidate_public)
    core.assert_no_truth_leakage(packet)  # raises on leakage
    check("packet builds with no truth leakage", True)
    blob = str(packet)
    check("packet names no acceptance field", '"accepted"' not in blob)


def test_general_rule_executes_on_any_block():
    s = synth_schedule()
    rule = {"type": "positional", "positions": [11, 10, 9, 8]}
    ok1, _, sels1 = core.normalize_rule(rule, ["t-dedupe-0", "t-join-0"], s)
    ok2, _, sels2 = core.normalize_rule(rule, ["t-dedupe-1", "t-join-1"], s)
    check("general rule executes on multiple blocks",
          ok1 and ok2 and sels1["t-dedupe-0"][0] == "t-dedupe-0-c11"
          and sels2["t-join-1"][0] == "t-join-1-c11")


def test_scoring_respects_accepted_boolean_in_records():
    # Regression: sealed truth stores per-candidate RECORDS (dicts), not bare
    # bools. A truthy dict must not count as acceptable; only
    # record["accepted"] is True counts.
    tid = "t-dedupe-0"
    truth = {"tasks": {tid: {"accepted": {
        f"{tid}-c{i:02d}": {"accepted": (i == 5), "correct": True,
                            "operations": 10, "baseline_operations": 20,
                            "operation_ratio": 0.5, "gain": 0.5, "reason": "x"}
        for i in range(12)}}}}
    sels = {tid: [f"{tid}-c{i:02d}" for i in (0, 1, 2, 3)]}  # no acceptable inside
    sc = core.score_selections(sels, truth)
    check("dict records: unacceptable candidates do not count",
          sc["per_task"][tid]["found_acceptable"] is False
          and sc["task_successes"] == 0)
    sels2 = {tid: [f"{tid}-c{i:02d}" for i in (0, 5, 9, 11)]}
    sc2 = core.score_selections(sels2, truth)
    check("dict records: accepted record counts at ordered position",
          sc2["per_task"][tid]["found_acceptable"] is True
          and sc2["per_task"][tid]["evaluations_to_first_success"] == 2)


def test_cost_math():
    c = core.computed_cost_usd(301, 133)
    check("cost math matches -002 receipt", abs(c - 0.00966) < 1e-9)


def _shape_fixture():
    fams = ["dedupe-stream", "normalized-join", "sliding-window", "transient-fetch"]
    truth = {"schema": core.SCHEMA_TRUTH, "experiment": core.EXPERIMENT, "tasks": {}}
    schedule = {"schema": core.SCHEMA_SCHEDULE, "experiment": core.EXPERIMENT,
                "round_blocks": {}, "tasks": {}}
    tids = []
    for fi, fam in enumerate(fams):
        for ti in range(4):
            tid = f"{fam}-{ti}"
            tids.append(tid)
            truth["tasks"][tid] = {"family": fam,
                                   "accepted": {f"{tid}-c{i:02d}": True for i in range(12)}}
            schedule["tasks"][tid] = {"family": fam}
    for r in (1, 2, 3, 4):
        schedule["round_blocks"][str(r)] = [tids[fi * 4 + (r - 1)] for fi in range(4)]
    return truth, schedule


def test_truth_shape_invariant():
    truth, schedule = _shape_fixture()
    n = core.check_truth_shape(truth, schedule)
    check("truth shape 16x12 returns 192", n == 192)
    # Tamper: drop one candidate -> must raise.
    bad = json.loads(json.dumps(truth))
    first_tid = next(iter(bad["tasks"]))
    bad["tasks"][first_tid]["accepted"].pop(next(iter(bad["tasks"][first_tid]["accepted"])))
    try:
        core.check_truth_shape(bad, schedule)
        check("truth shape rejects 191 evaluations", False)
    except RuntimeError:
        check("truth shape rejects 191 evaluations", True)
    # Tamper: break block partition -> must raise.
    bad_s2 = json.loads(json.dumps(schedule))
    bad_s2["round_blocks"]["1"] = bad_s2["round_blocks"]["1"][:3] + [bad_s2["round_blocks"]["2"][0]]
    try:
        core.check_truth_shape(truth, bad_s2)
        check("truth shape rejects broken partition", False)
    except RuntimeError:
        check("truth shape rejects broken partition", True)


def test_isolation_lineage():
    root = Path(__file__).resolve().parents[3]
    info = core.verify_isolation_lineage(root)
    check("isolation receipt hash frozen",
          info["receipt_sha256"] == "37b636a1d515d4b8c4b539327d8392c0859211e48d1edd7cd7c85d0a25aa27dd")
    check("isolation model lineage exactly gpt-6-astra x4",
          info["call_records"] == 4
          and all(m == "gpt-6-astra" for m in info["provider_returned_models"]))


def main():
    test_rule_explicit_ids_valid()
    test_rule_positional_valid()
    test_rule_complement_positional_valid()
    test_rule_quarantine_cases()
    test_scoring_semantics()
    test_promotion_gain()
    test_promotion_preserve_with_fewer_evals()
    test_promotion_no_loss_required()
    test_promotion_tie_no_improvement_rejects()
    test_promotion_zero_zero_rejects()
    test_no_proxy_in_scoring()
    test_packet_has_no_truth()
    test_general_rule_executes_on_any_block()
    test_cost_math()
    test_scoring_respects_accepted_boolean_in_records()
    test_truth_shape_invariant()
    test_isolation_lineage()
    print(f"\n{len(FAILURES)} failures")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
