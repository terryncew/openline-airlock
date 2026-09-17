"""Three separate economic calculations. Their conditions are not
interchangeable, and success-rate ratios alone never establish payback.

(1) Descriptive unit-cost advantage: pooled $/verified per arm over
    completed reps, with the output-preservation condition stated.
    A description of what happened; says nothing about debt.
(2) Observed acquisition payback: the COST-FORM inequality
    D1 + C_B <= C_A with V_B >= V_A (pooled), plus the per-rep
    breakdown. Earned only if the pooled inequality holds AND at least
    2 completed reps satisfy the per-rep inequality. The debt was
    actually covered in-horizon; says nothing about the future.
(3) Projected future payback: rep-level per-task savings extrapolated
    to a break-even horizon k*, with a CI that MUST extend to +infinity
    whenever any completed rep shows non-positive savings. A projection,
    never an observed verdict.

Aborted repetitions and unresolved exposure are reported alongside
completed-run economics, never folded into them.
"""
from __future__ import annotations

from .orchestrate import _acq_spend, spend_of


def _arm_totals(rep: dict) -> dict:
    out = {}
    for arm in ("A", "B", "C"):
        atts = [a for a in rep["attempts"] if a.get("arm") == arm]
        out[arm] = {
            "n": len(atts),
            "verified": sum(a.get("verdict", 0) for a in atts),
            "cost": sum(spend_of(a) for a in atts),
        }
    return out


def _payback_block(completed: list[dict], debt_key: str,
                   arm_lo: str, arm_hi: str, n_meas: int = 36) -> dict:
    """debt_key: 'G1_acquisition' (B vs A) or 'G2_acquisition' (C vs B)."""
    per_rep = []
    for rep in completed:
        at = _arm_totals(rep)
        d = _acq_spend(rep.get(debt_key))
        lo, hi = at[arm_lo], at[arm_hi]
        holds = (d + hi["cost"] <= lo["cost"] + 1e-9) and (hi["verified"] >= lo["verified"])
        per_rep.append({
            "rep": rep["rep"],
            "debt": d,
            "cost_lo": lo["cost"], "cost_hi": hi["cost"],
            "verified_lo": lo["verified"], "verified_hi": hi["verified"],
            "holds": holds,
        })
    D = sum(r["debt"] for r in per_rep)
    C_lo = sum(r["cost_lo"] for r in per_rep)
    C_hi = sum(r["cost_hi"] for r in per_rep)
    V_lo = sum(r["verified_lo"] for r in per_rep)
    V_hi = sum(r["verified_hi"] for r in per_rep)
    pooled_holds = (D + C_hi <= C_lo + 1e-9) and (V_hi >= V_lo)
    n_hold = sum(1 for r in per_rep if r["holds"])
    earned = (len(completed) >= 2 and pooled_holds and n_hold >= 2)
    return {
        "comparison": f"{arm_hi}_vs_{arm_lo}",
        "pooled": {"D": D, "C_lo": C_lo, "C_hi": C_hi,
                   "V_lo": V_lo, "V_hi": V_hi,
                   "inequality": f"{D:.6f} + {C_hi:.6f} <= {C_lo:.6f}",
                   "holds": pooled_holds},
        "per_rep": per_rep,
        "reps_holding": n_hold,
        "observed_payback_earned": earned,
        "note": ("Earned = debt actually covered in-horizon by the cost-form "
                 "inequality. Success-rate ratios were not used."),
    }


def _projection_block(completed: list[dict], debt_key: str,
                      arm_lo: str, arm_hi: str, n_meas: int = 36) -> dict:
    per_rep = []
    for rep in completed:
        at = _arm_totals(rep)
        d = _acq_spend(rep.get(debt_key))
        s = (at[arm_lo]["cost"] - at[arm_hi]["cost"]) / n_meas
        k = (d / s) if s > 0 else float("inf")
        per_rep.append({"rep": rep["rep"], "debt": d,
                        "per_task_saving": s, "k_star": k})
    finite = [r["k_star"] for r in per_rep if r["k_star"] != float("inf")]
    if finite and len(finite) == len(per_rep):
        med = sorted(finite)[len(finite) // 2]
        ci = [min(finite), max(finite)]
    else:
        med = sorted(finite)[len(finite) // 2] if finite else float("inf")
        ci = [(min(finite) if finite else float("inf")), float("inf")]
    return {
        "comparison": f"{arm_hi}_vs_{arm_lo}",
        "per_rep": per_rep,
        "median_k_star": med,
        "ci_k_star": ci,
        "ci_extends_to_infinity": ci[1] == float("inf"),
        "note": ("Projection from observed rep-level savings; permits no "
                 "finite break-even whenever any rep shows non-positive "
                 "savings. Not an observed verdict."),
    }


def build_report(study: dict) -> dict:
    completed = [r for r in study["reps"] if r["status"] == "completed"]
    aborted = [{"rep": r["rep"], "reason": r["abort_reason"],
                "spend_usd": r["spend_usd"],
                "invocations": len(r["invocations"])}
               for r in study["reps"] if r["status"] != "completed"]

    per_arm, units = {}, {}
    for arm in ("A", "B", "C"):
        pc = sum(_arm_totals(r)[arm]["cost"] for r in completed)
        pv = sum(_arm_totals(r)[arm]["verified"] for r in completed)
        per_arm[arm] = {"pooled_cost": pc, "pooled_verified": pv,
                        "n_reps": len(completed)}
        units[arm] = pc / pv if pv else None

    unit_cost = {
        "per_arm": per_arm,
        "pooled_usd_per_verified": units,
        "output_preservation": {
            "B_ge_A": per_arm["B"]["pooled_verified"] >= per_arm["A"]["pooled_verified"],
            "C_ge_B": per_arm["C"]["pooled_verified"] >= per_arm["B"]["pooled_verified"],
        },
        "note": ("Descriptive only: pooled $/verified over completed reps. "
                 "A lower $/verified is not payback; the acquisition debt "
                 "is accounted in block (2), not here."),
    }

    payback = {
        "G1_B_vs_A": _payback_block(completed, "G1_acquisition", "A", "B"),
        "G2_C_vs_B": _payback_block(completed, "G2_acquisition", "B", "C"),
    }
    projection = {
        "G1_B_vs_A": _projection_block(completed, "G1_acquisition", "A", "B"),
        "G2_C_vs_B": _projection_block(completed, "G2_acquisition", "B", "C"),
    }

    unresolved = [
        {"invocation_id": a["invocation_id"], "task_id": a.get("task_id"),
         "retained_usd": a.get("reservation_usd"), "reason": a.get("error")}
        for r in study["reps"] for a in r["attempts"]
        if a.get("status") == "unresolved"
    ]

    return {
        "study_id": study.get("study_id"),
        "completed_reps": len(completed),
        "aborted_reps": aborted,
        "invocation_count": study.get("invocation_count"),
        "ledger": study.get("ledger_summary"),
        "unit_cost_advantage_descriptive": unit_cost,
        "observed_acquisition_payback": payback,
        "projected_future_payback": projection,
        "unresolved_exposure": {
            "count": len(unresolved),
            "retained_usd": sum(u["retained_usd"] or 0 for u in unresolved),
            "items": unresolved,
        },
    }
