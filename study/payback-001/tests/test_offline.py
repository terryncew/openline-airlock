"""PAYBACK-001 offline tests: zero provider contact.

Run: ~/workspace/.venvs/econ/bin/python tests/test_offline.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/payback-001")
sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/payback-001/scripts")
import frozen as F  # noqa: E402
import payback_acct  # noqa: E402

STUDY = "/home/hatch/workspace/openline-airlock/study/payback-001"
VENV = "/home/hatch/workspace/.venvs/econ/bin/python"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("ok  " if cond else "FAIL") + " " + name + (" " + str(detail) if detail and not cond else ""))


def run_offline():
    p = subprocess.run([VENV, STUDY + "/scripts/payback_run.py", "--offline"],
                       capture_output=True, text=True, timeout=120)
    check("offline exits 0", p.returncode == 0, p.stderr[-500:])
    return json.loads(p.stdout) if p.returncode == 0 else {}


def main():
    rep = run_offline()
    check("offline report ok", rep.get("ok") is True)
    check("scientific call inventory = 928", rep.get("scientific_calls") == 928)
    check("base SHA frozen", F.BASE_SHA == "9ccd19d853083b97f8aed4d30d8ff00c553a1f12")

    # arm order frozen + balanced
    arm = json.load(open(STUDY + "/corpus/ARM_ORDER.json"))
    check("arm order 225/225", arm["balance"] == {"CT": 225, "TC": 225})
    check("arm order hashed", F.ARM_ORDER_SHA256 ==
          hashlib.sha256(open(STUDY + "/corpus/ARM_ORDER.json", "rb").read()).hexdigest())

    # null margin present and sane
    null = json.load(open(STUDY + "/null/NULL_CALIBRATION.json"))
    m = null["V1_primary"]
    check("null margin frozen", F.NULL_MARGIN_99 == null["margin"]["p99"]
          and null["margin"]["p99"] > 0)
    check("null percentiles ordered",
          m["median"] <= m["p90"] <= m["p95"] <= m["p99"] <= m["max"])
    check("null n_sim=20000", null["n_sim"] == 20000)

    # accounting on synthetic ledgers: all terminal states
    tmp = "/tmp/pb1_acct_test"
    os.makedirs(tmp, exist_ok=True)
    D, H = 0.37, 450

    def ledger(deltas, verdicts=None, skip=(), halted=False, run_status=True):
        lines = []
        rid = 0
        # full acquisition debt D across discovery(3)+proposal(1) settles
        for j, name in enumerate(["pb1-d-00", "pb1-d-01", "pb1-d-02", "pb1-p"]):
            lines.append({"kind": "settle", "invocation_id": name, "actual": D / 4,
                          "reservation_id": f"r{rid}"}); rid += 1
        for i, d in enumerate(deltas):
            if i in skip:
                continue
            c = 0.013
            lines.append({"kind": "settle", "invocation_id": f"pb1-o-C-{i:04d}",
                          "actual": c, "reservation_id": f"r{rid}"}); rid += 1
            lines.append({"kind": "settle", "invocation_id": f"pb1-o-T-{i:04d}",
                          "actual": c - d, "reservation_id": f"r{rid}"}); rid += 1
        p = tmp + "/ledger.jsonl"
        open(p, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
        tp = None
        if verdicts:
            tp = tmp + "/TASKS.jsonl"
            open(tp, "w").write("\n".join(
                json.dumps({"i": i, "control": {"verdict": vc, "cost": 0.013},
                            "treatment": {"verdict": vt, "cost": 0.012}})
                for i, (vc, vt) in enumerate(verdicts)) + "\n")
        rd = tmp + "/run"
        os.makedirs(rd, exist_ok=True)
        if run_status:
            json.dump({"status": "halted" if halted else "completed"},
                      open(rd + "/RUN_STATUS.json", "w"))
        for f in [p, tp]:
            if f:
                import shutil
                shutil.copy(f, rd + "/" + os.path.basename(f))
        return rd + "/ledger.jsonl", (rd + "/TASKS.jsonl") if tp else None, rd

    # strong positive: steady savings beat debt + null margin
    p, _, rd = ledger([0.002] * H)
    r = payback_acct.compute(p, None, rd)
    check("strong positive detected", r["verdict"] == "STRONG_POSITIVE", r["verdict"])
    check("A(0) = -D", abs(r["curve"][0] - (0.002 - D)) < 1e-9,
          f"curve[0]={r['curve'][0]}")

    # no payback
    p, _, rd = ledger([0.0001] * H)
    r = payback_acct.compute(p, None, rd)
    check("no payback detected", r["verdict"] == "NO_PAYBACK", r["verdict"])

    # nominal within null
    per = (D + m["p99"] / 2) / H
    p, _, rd = ledger([per] * H)
    r = payback_acct.compute(p, None, rd)
    check("nominal-not-beyond-null detected",
          r["verdict"] == "NOMINAL_NOT_BEYOND_NULL", r["verdict"])

    # quality void: treatment fails where control passes
    p, tp, rd = ledger([0.002] * H, verdicts=[(1, 1)] * H)
    lines = open(tp).read().strip().split("\n")
    bad = json.loads(lines[10]); bad["treatment"]["verdict"] = 0
    lines[10] = json.dumps(bad)
    open(tp, "w").write("\n".join(lines) + "\n")
    r = payback_acct.compute(p, tp, rd)
    check("quality regression voids", r["verdict"] == "VOID_QUALITY_REGRESSION", r["verdict"])

    # incomplete horizon (halted status)
    p, _, rd = ledger([0.002] * 100, halted=True)
    r = payback_acct.compute(p, None, rd)
    check("incomplete detected", r["verdict"] == "INCOMPLETE", r["verdict"])

    # debt-only (no operating): negative
    lines = [{"kind": "settle", "invocation_id": "pb1-d-00", "actual": D,
              "reservation_id": "r0"}]
    rd2 = tmp + "/run2"
    os.makedirs(rd2, exist_ok=True)
    p2 = rd2 + "/ledger.jsonl"
    open(p2, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
    json.dump({"status": "completed", "phase": "acquisition",
               "note": "no accepted successor; operating skipped"},
              open(rd2 + "/RUN_STATUS.json", "w"))
    r = payback_acct.compute(p2, None, rd2)
    check("debt-only terminal states sane",
          r["verdict"] in ("NO_PAYBACK", "INCOMPLETE"), r["verdict"])
    check("A_H = -D when nothing operated", abs(r["A_H"] + D) < 1e-9)

    # breakeven present on strong positive
    p, _, rd = ledger([0.002] * H)
    r = payback_acct.compute(p, None, rd)
    check("breakeven found", r["breakeven_t"] is not None and r["breakeven_t"] <= H)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
