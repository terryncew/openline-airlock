"""PAYBACK-001 runner: one bounded improvement investment vs a frozen horizon.

Two modes:
  python payback_run.py --offline
      Verify every freezable artifact with ZERO provider contact.
  python payback_run.py --authorize-paid-contact [--preflight]
      Execute the frozen study. NOT authorized until explicit approval
      after remote verification.

Frozen design (see PREREGISTRATION.md):
  acquisition: 3 discovery (parent) + 1 proposal + 12x2 promotion
  gate: parent 12/12, candidate 12/12, zero regressions,
        candidate promo cost <= 1.5x parent (operational safety bound)
  operating: 450 paired tasks, frozen arm order (225 CT / 225 TC)
  A(t) = sum(control_i - treatment_i) - D ; strong positive needs
  A(450) > NULL_MARGIN_99 with quality preserved.

Reuses preserved ECON primitives: attempt, evaluate, worker, ledger,
prompts/apply_delta, extract, corpus, envelopes. No router, no recursion,
no new provider integration, no self-modifying acceptance rule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/econ-001/src")
sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/payback-001")
sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/payback-001/scripts")
from econ import attempt as attempt_mod  # noqa: E402
from econ import corpus as corpus_mod  # noqa: E402
from econ import evaluate  # noqa: E402
from econ import extract  # noqa: E402
from econ import ledger as ledger_mod  # noqa: E402
from econ import orchestrate  # noqa: E402
from econ import prompts  # noqa: E402
from econ import worker  # noqa: E402
import frozen as F  # noqa: E402

STUDY = "/home/hatch/workspace/openline-airlock/study/payback-001"
CORPUS = STUDY + "/corpus/corpus.json"
RUNS = STUDY + "/runs/" + F.STUDY_ID

PROPOSAL_PROMPT = (
    "You are improving a bug-fixing method. Propose ONE bounded change to the "
    "CURRENT METHOD below that could reduce the cost of fixing bugs while "
    "preserving correctness. Output ONLY a fenced block of the form:\n"
    "```delta\n<precise edit instructions>\n```\n"
    "The delta must be appliable by textual replacement. Do not include any "
    "other text outside the fenced block."
)


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def load_artifacts():
    data = json.load(open(CORPUS))
    tasks = {t["task_id"]: corpus_mod.Task(**t) for t in data["tasks"]}
    alloc = json.load(open(STUDY + "/corpus/ALLOCATION.json"))
    order = json.load(open(STUDY + "/corpus/OPERATING_ORDER.json"))
    arm = json.load(open(STUDY + "/corpus/ARM_ORDER.json"))
    promo = json.load(open(STUDY + "/corpus/PROMOTION_ORDER.json"))
    null = json.load(open(STUDY + "/null/NULL_CALIBRATION.json"))
    return tasks, alloc, order, arm, promo, null


def check_stop(path: str):
    if os.path.exists(path):
        raise worker.OperatorStop("operator stop file present: " + path)


def offline() -> dict:
    """Verify everything freezable with zero provider contact."""
    tasks, alloc, order, arm, promo, null = load_artifacts()
    assert _sha(CORPUS) == F.CORPUS_SHA256, "corpus SHA mismatch"
    assert _sha(STUDY + "/corpus/ARM_ORDER.json") == F.ARM_ORDER_SHA256
    assert len(alloc["discovery"]) == 3 and len(alloc["promotion"]) == 12
    assert len(alloc["operating_pool"]) == 450
    assert len(order["order"]) == 450 and sorted(order["order"]) == list(range(450))
    assert arm["balance"] == {"CT": 225, "TC": 225} and len(arm["order"]) == 450
    assert len(promo["order"]) == 12
    assert null["margin"]["p99"] == F.NULL_MARGIN_99, "null margin mismatch"
    inv = F.CALL_INVENTORY
    sci = inv["discovery"] + inv["proposal"] + inv["promotion"] + inv["operating"]
    assert sci == 928, sci
    assert inv["preflight"] == 1
    worst_plausible = F.ACQUISITION_CAP + 900 * 0.013134  # cap + frozen mean
    assert F.BUDGET_TOTAL == 18.00 and worst_plausible < 18.00
    assert F.PROMO_COST_CAP == 1.5 and F.K_MAX == 1 and F.H == 450
    head = os.popen("git -C " + STUDY + "/../.. rev-parse HEAD").read().strip()
    assert head, "no git HEAD"
    return {"ok": True, "scientific_calls": sci, "total_calls": sci + 1,
            "head": head, "corpus_sha": F.CORPUS_SHA256}


def _attempt(task, method_text, invocation_id, cx):
    check_stop(cx["stop"])
    a = attempt_mod.attempt(task, method_text, ledger=cx["ledger"],
                            provider=cx["provider"], envelopes=cx["envs"],
                            invocation_id=invocation_id, stop_file=cx["stop"],
                            raw_dir=cx["raw"])
    a.pop("code", None)
    return a


def acquisition(tasks, alloc, cx):
    """Bounded acquisition. Returns (candidate_method|None, note)."""
    disc_ids = [list(tasks)[i] for i in alloc["discovery"]]
    promo_ids = [list(tasks)[i] for i in alloc["promotion"]]
    promo_order = json.load(open(STUDY + "/corpus/PROMOTION_ORDER.json"))["order"]
    parent = prompts.BASE_METHOD
    disc = [_attempt(tasks[t], parent, f"{F.P_DISC}-{i:02d}", cx)
            for i, t in enumerate(disc_ids)]
    fb = "\n\n".join(f"--- DISCOVERY {i+1} ---\n{tasks[t].task_id}: "
                      f"verdict={a['verdict']} cost={a.get('actual_usd')}"
                      for i, (t, a) in enumerate(zip(disc_ids, disc)))
    res = worker.invoke(instructions=PROPOSAL_PROMPT,
                        input_text="CURRENT METHOD:\n" + parent + "\n\n" + fb,
                        envelope=cx["envs"]["proposal"], ledger=cx["ledger"],
                        provider=cx["provider"], invocation_id=F.P_PROP,
                        stop_file=cx["stop"], raw_dir=cx["raw"])
    if res.status != "ok" or not res.text:
        return None, f"proposal_{res.status}"
    delta = extract.extract_delta(res.text)
    if delta is None:
        return None, "delta_extraction_failed"  # malformed = charged rejection
    try:
        cand = prompts.apply_delta(parent, delta)
    except Exception as e:
        return None, f"delta_rejected: {e}"
    # promotion: 12 tasks x 2 arms, frozen per-pair order
    vp = vc = cp = cc = regr = 0
    for i, t in enumerate(promo_ids):
        seq = [("P", parent), ("C", cand)] if promo_order[i] == "PC" \
            else [("C", cand), ("P", parent)]
        r = {}
        for tag, m in seq:
            a = _attempt(tasks[t], m, f"{F.P_PROMO_P if tag=='P' else F.P_PROMO_C}-{i:02d}", cx)
            r[tag] = a
        vp += r["P"]["verdict"]; vc += r["C"]["verdict"]
        cp += r["P"].get("actual_usd") or 0; cc += r["C"].get("actual_usd") or 0
        if r["P"]["verdict"] == 1 and r["C"]["verdict"] == 0:
            regr += 1
    ok = (vp == 12 and vc == 12 and regr == 0 and cc <= F.PROMO_COST_CAP * cp)
    note = {"vp": vp, "vc": vc, "regressions": regr, "parent_cost": cp,
            "cand_cost": cc, "ratio": cc / cp if cp else None,
            "decision": "accept" if ok else "reject"}
    json.dump(note, open(cx["run"] + "/promotion.json", "w"), indent=1)
    if not ok:
        return None, "promotion_rejected"
    with open(cx["run"] + "/candidate_method.txt", "w") as f:
        f.write(cand)
    note["candidate_sha256"] = _sha(cx["run"] + "/candidate_method.txt")
    json.dump(note, open(cx["run"] + "/promotion.json", "w"), indent=1)
    return cand, "accepted"


def operating(tasks, alloc, order, arm, candidate, cx):
    """450 paired operating tasks, frozen arm order. Writes TASKS.jsonl."""
    pool_ids = [list(tasks)[i] for i in alloc["operating_pool"]]
    out = open(cx["run"] + "/TASKS.jsonl", "w")
    for i, pos in enumerate(order["order"]):
        t = pool_ids[pos]
        seq = [("C", prompts.BASE_METHOD), ("T", candidate)] \
            if arm["order"][i] == "CT" else [("T", candidate), ("C", prompts.BASE_METHOD)]
        r = {}
        for tag, m in seq:
            a = _attempt(tasks[t], m, f"{F.P_OP_C if tag=='C' else F.P_OP_T}-{i:04d}", cx)
            r[tag] = {"verdict": a["verdict"], "cost": a.get("actual_usd")}
        out.write(json.dumps({"i": i, "task": t, "order": arm["order"][i],
                              "control": r["C"], "treatment": r["T"]}) + "\n")
        out.flush()
    out.close()


def paid(args):
    rep = offline()  # frozen artifacts must verify before any contact
    os.makedirs(RUNS, exist_ok=True)
    raw = RUNS + "/raw"
    os.makedirs(raw, exist_ok=True)
    stop = RUNS + "/STOP"
    led = ledger_mod.Ledger(F.BUDGET_TOTAL, RUNS + "/ledger.jsonl")
    prov = worker.Provider()
    envs = orchestrate.load_envelopes(
        "/home/hatch/workspace/openline-airlock/study/econ-001/CONFIG.json")
    cx = {"ledger": led, "provider": prov, "envs": envs, "stop": stop,
          "raw": raw, "run": RUNS}
    json.dump({"offline_report": rep, "preflight": bool(args.preflight)},
              open(RUNS + "/MANIFEST.json", "w"), indent=1)
    if args.preflight:
        check_stop(stop)
        worker.invoke(instructions="ping", input_text="ping",
                      envelope=envs["preflight"], ledger=led, provider=prov,
                      invocation_id=f"{F.P_PRE}-00", stop_file=stop, raw_dir=raw)
        led.note(kind="preflight", note="non-scientific; excluded from D and A(t)")
    tasks, alloc, order, arm, promo, null = load_artifacts()
    task_list = list(tasks.values())
    tmap = {t.task_id: t for t in task_list}
    try:
        cand, note = acquisition(tmap, alloc, cx)
    except (worker.OperatorStop, ledger_mod.InsufficientBudget) as e:
        led.note(kind="halt", reason=str(e))
        json.dump({"status": "halted", "reason": str(e), "phase": "acquisition"},
                  open(RUNS + "/RUN_STATUS.json", "w"))
        return {"outcome": "INCOMPLETE", "reason": str(e)}
    led.note(kind="acquisition", result=note)
    if cand is None:
        json.dump({"status": "completed", "phase": "acquisition",
                   "note": "no accepted successor; operating skipped"},
                  open(RUNS + "/RUN_STATUS.json", "w"))
        led.note(kind="terminal", verdict="NO_PAYBACK",
                 reason="no accepted successor; operating skipped; debt only")
        return {"outcome": "NO_PAYBACK", "reason": note}
    try:
        operating(tmap, alloc, order, arm, cand, cx)
    except (worker.OperatorStop, ledger_mod.InsufficientBudget) as e:
        led.note(kind="halt", reason=str(e))
        json.dump({"status": "halted", "reason": str(e), "phase": "operating"},
                  open(RUNS + "/RUN_STATUS.json", "w"))
        return {"outcome": "INCOMPLETE", "reason": str(e)}
    json.dump({"status": "completed", "phase": "operating"},
              open(RUNS + "/RUN_STATUS.json", "w"))
    import payback_acct
    r = payback_acct.compute(RUNS + "/ledger.jsonl", RUNS + "/TASKS.jsonl", RUNS)
    led.note(kind="terminal", verdict=r["verdict"], A_H=r["A_H"], D=r["D"])
    json.dump(r, open(RUNS + "/verdict.json", "w"), indent=1)
    return {"outcome": r["verdict"], "A_H": r["A_H"], "D": r["D"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--authorize-paid-contact", action="store_true")
    ap.add_argument("--preflight", action="store_true")
    args = ap.parse_args()
    if args.offline:
        print(json.dumps(offline(), indent=1))
    elif args.authorize_paid_contact:
        print(json.dumps(paid(args), indent=1))
    else:
        raise SystemExit("refusing: pass --offline or --authorize-paid-contact")


if __name__ == "__main__":
    main()
