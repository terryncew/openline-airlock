"""PAYBACK-002 cumulative accounting layer (offline).

Byte-equivalent logic to PAYBACK-001's accounting; the only change is the
invocation-ID namespace (pb2-*), parameterized via F.INV_PREFIX instead of
the hardcoded "pb1".

Reads the study ledger and computes the frozen terminal states:

  D      = all treatment acquisition settled cost
         + all retained unresolved acquisition reservations
         (+ any other preregistered acquisition-side cost classified as
            treatment investment; preflight is EXCLUDED: separate accounting)
  d_i    = control_cost_i - treatment_cost_i   (operating task i)
  A(t)   = sum_{i<=t} d_i - D ;  A(0) = -D
  break-even = first t with A(t) > 0

Terminal states (frozen):
  A(H) <= 0                          -> NO_PAYBACK (negative)
  0 < A(H) <= NULL_MARGIN_99         -> NOMINAL_NOT_BEYOND_NULL (not strong)
  A(H) > NULL_MARGIN_99              -> STRONG_POSITIVE (iff quality holds)
  treatment fails a task control passes -> strong positive VOID
  no accepted successor              -> operating skipped; debt-only negative
  horizon incomplete                 -> INCOMPLETE (never rescued)
  preflight not clean                -> INCOMPLETE_PREFLIGHT (fail-closed gate)

No provider contact. Pure function of preserved ledger evidence.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/home/hatch/workspace/openline-airlock/study/payback-002")
import frozen as F  # noqa: E402


def _is_acq(inv: str) -> bool:
    return inv.startswith(F.P_DISC) or inv == F.P_PROP or \
        inv.startswith(F.P_PROMO_P) or inv.startswith(F.P_PROMO_C)


def _op_index(inv: str):
    # pb2-o-C-<i> / pb2-o-T-<i>
    p = inv.split("-")
    if len(p) == 4 and p[0] == F.INV_PREFIX and p[1] == "o" and p[2] in ("C", "T"):
        return p[2], int(p[3])
    return None, None


def compute(ledger_path: str, tasks_path: str | None = None,
            run_dir: str | None = None) -> dict:
    settles, retained = {}, {}
    for line in open(ledger_path):
        e = json.loads(line)
        k = e.get("kind")
        if k == "settle":
            settles[e["invocation_id"]] = e["actual"]
        elif k == "unresolved":
            retained[e["invocation_id"]] = e["retained"]

    # --- Acquisition debt D ---
    D_settled = sum(v for i, v in settles.items() if _is_acq(i))
    D_retained = sum(v for i, v in retained.items() if _is_acq(i))
    D = D_settled + D_retained

    # --- Operating paired differences ---
    deltas, missing, void_tasks = [], [], []
    op_c = {int(i.split("-")[3]): v for i, v in settles.items()
            if i.startswith(F.P_OP_C)}
    op_t = {int(i.split("-")[3]): v for i, v in settles.items()
            if i.startswith(F.P_OP_T)}
    # Receiver-quality verdicts come from the runner's per-task records.
    task_verdicts = {}
    if tasks_path and os.path.exists(tasks_path):
        for line in open(tasks_path):
            r = json.loads(line)
            task_verdicts[r["i"]] = (r["control"]["verdict"],
                                     r["treatment"]["verdict"])
    # a task is void if treatment fails a task the control passes.
    for i in range(F.H):
        c, t = op_c.get(i), op_t.get(i)
        if c is None or t is None:
            missing.append(i)
            deltas.append(0.0)
            if c is not None and t is None:
                void_tasks.append(i)
        else:
            deltas.append(c - t)
        v = task_verdicts.get(i)
        if v == (1, 0) and i not in void_tasks:
            void_tasks.append(i)

    A, curve = -D, []
    for d in deltas:
        A += d
        curve.append(A)
    breakeven = next((t + 1 for t, a in enumerate(curve) if a > 0), None)

    # Completeness: the runner is the authority. Halted or short horizon
    # -> INCOMPLETE, never rescued. Unresolved-but-continued tasks contribute
    # delta 0 (their reservations are retained exposure, not silent gains).
    halted, rows = False, None
    if run_dir and os.path.exists(run_dir + "/RUN_STATUS.json"):
        status = json.load(open(run_dir + "/RUN_STATUS.json")).get("status")
        halted = status not in ("completed",)
        preflight_gate = status == "incomplete_preflight"
    else:
        preflight_gate = False
    if tasks_path and os.path.exists(tasks_path):
        rows = sum(1 for _ in open(tasks_path))
    both_settled = sum(1 for i in range(F.H)
                       if i in op_c and i in op_t)
    if preflight_gate:
        verdict = "INCOMPLETE_PREFLIGHT"
    elif halted or (rows is not None and rows < F.H) or \
            (rows is None and run_dir is None and both_settled < F.H):
        verdict = "INCOMPLETE"
    elif void_tasks:
        verdict = "VOID_QUALITY_REGRESSION"
    elif curve[-1] <= 0:
        verdict = "NO_PAYBACK"
    elif curve[-1] <= F.NULL_MARGIN_99:
        verdict = "NOMINAL_NOT_BEYOND_NULL"
    else:
        verdict = "STRONG_POSITIVE"

    return {
        "D": D, "D_settled": D_settled, "D_retained": D_retained,
        "H_completed": both_settled, "halted": halted,
        "A_H": curve[-1] if curve else -D,
        "breakeven_t": breakeven, "missing_tasks": missing,
        "void_tasks": void_tasks, "verdict": verdict,
        "null_margin_99": F.NULL_MARGIN_99,
        "curve": curve,
    }


if __name__ == "__main__":
    r = compute(sys.argv[1])
    curve = r.pop("curve")
    print(json.dumps(r, indent=1))
