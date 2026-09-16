"""Study orchestrator: calibration, then 3 independent lineages.

Schedule per repetition (128 invocations):
  G1: acquisition on the common method (3 discovery + 1 proposal + 6 promotion)
      then 12 measurement tasks x 3 arms (matched task IDs)
  G2: acquisition on arm C's method, then 12 x 3 measurement
  G3: 12 x 3 measurement (no acquisition)
Plus 4 calibration invocations (1 preflight + 3 family tasks).
Total: 4 + 3*128 = 388 invocations.

A repetition aborts (recorded, spend kept) on budget refusal; the study
continues with the next lineage. A cost overrun aborts the whole study:
fail closed.
"""
from __future__ import annotations

import json
import os
import uuid

from . import acquire, attempt as attempt_mod
from . import ledger as ledger_mod
from . import prompts, worker

STRATEGY_THRESHOLD_T = 8.00


def load_envelopes(config_path: str) -> dict:
    with open(config_path) as f:
        cfg = json.load(f)
    envs = {}
    for name in ("solving", "proposal", "preflight"):
        e = dict(cfg["envelopes"][name])
        e["name"] = name
        envs[name] = e
    return envs


def spend_of(a: dict) -> float:
    """Actual if settled, else the retained reservation. Never zero."""
    if a.get("actual_usd") is not None:
        return float(a["actual_usd"])
    return float(a.get("reservation_usd", 0.0))


def _run_calibration(calib_tasks, envelopes, ledger, provider, outdir,
                     timeout_s=300.0) -> dict:
    rec = {"invocations": []}
    # 1. Telemetry preflight: usage must be present; local count must track
    #    the provider's count within 2%.
    instructions, input_text = prompts.build_preflight_prompt()
    res = worker.invoke(
        instructions=instructions, input_text=input_text,
        envelope=envelopes["preflight"], ledger=ledger, provider=provider,
        invocation_id="calib_preflight", timeout_s=timeout_s)
    if res.status != "ok" or not res.usage:
        raise RuntimeError(f"calibration preflight failed: {res.status} {res.error}")
    pin = res.usage["input_tokens"]
    drift = abs(res.local_input_tokens - pin) / max(pin, 1)
    rec["preflight"] = {
        "status": res.status, "actual_usd": res.actual_usd,
        "local_input_tokens": res.local_input_tokens,
        "provider_input_tokens": pin,
        "tokenizer_drift": drift,
    }
    if drift > 0.02:
        raise RuntimeError(f"tokenizer drift {drift:.3%} exceeds 2%: abort")
    rec["invocations"].append("calib_preflight")
    # 2. One solving call per family with the baseline method.
    c_max = 0.0
    for i, t in enumerate(calib_tasks):
        a = attempt_mod.attempt(
            t, prompts.BASE_METHOD, ledger=ledger, provider=provider,
            envelopes=envelopes, invocation_id=f"calib_solve{i}",
            timeout_s=timeout_s)
        rec["invocations"].append(a["invocation_id"])
        if a["status"] == "overrun_abort":
            raise worker.OverrunAbort("calibration overrun")
        c_max = max(c_max, spend_of(a))
        a["role"] = "calibration"
    rec["c_max_observed"] = c_max
    rec["strategy_threshold_T"] = STRATEGY_THRESHOLD_T
    return rec


def _acq_invocation_ids(acq: dict | None) -> list[str]:
    if not acq:
        return []
    ids = [acq.get("acquisition_id", "") + "_proposal"]
    for a in acq.get("discovery", []) + acq.get("promotion_parent", []) + acq.get("promotion_candidate", []):
        ids.append(a["invocation_id"])
    return ids


def _run_rep(rep_idx: int, rep_tasks: list, envelopes, ledger, provider,
             outdir, timeout_s=300.0) -> dict:
    rid = f"rep{rep_idx + 1}"
    rec = {"rep": rid, "status": "completed", "abort_reason": None,
           "invocations": [], "attempts": []}
    meas_tasks = rep_tasks[0:36]
    g1_tasks = rep_tasks[36:45]
    g2_tasks = rep_tasks[45:54]

    class _RepAbort(Exception):
        pass

    def note_attempt(a):
        rec["invocations"].append(a["invocation_id"])
        rec["attempts"].append(a)
        if a["status"] == "refused_precontact":
            rec["status"] = "aborted"
            rec["abort_reason"] = f"budget_refusal at {a['invocation_id']}"
            raise _RepAbort()

    try:
        # G1 acquisition on the common baseline method.
        g1 = acquire.run_acquisition(
            name=f"{rid}_G1", parent_method=prompts.BASE_METHOD,
            discovery_tasks=g1_tasks[0:3], promotion_tasks=g1_tasks[3:9],
            ledger=ledger, provider=provider, envelopes=envelopes,
            timeout_s=timeout_s)
        rec["G1_acquisition"] = g1
        rec["invocations"].extend(_acq_invocation_ids(g1))
        m_b = g1.get("method") if g1["decision"] == "accept" else prompts.BASE_METHOD
        rec["G1_accepted"] = g1["decision"] == "accept"

        # G2 acquisition on arm C's method (inherits arm B's method).
        g2 = acquire.run_acquisition(
            name=f"{rid}_G2", parent_method=m_b,
            discovery_tasks=g2_tasks[0:3], promotion_tasks=g2_tasks[3:9],
            ledger=ledger, provider=provider, envelopes=envelopes,
            timeout_s=timeout_s)
        rec["G2_acquisition"] = g2
        rec["invocations"].extend(_acq_invocation_ids(g2))
        m_c = g2.get("method") if g2["decision"] == "accept" else m_b
        rec["G2_accepted"] = g2["decision"] == "accept"

        # Measurement: 12 tasks/generation x 3 generations, matched A/B/C.
        methods = {"A": prompts.BASE_METHOD, "B": m_b, "C": m_c}
        for gi in range(3):
            for ti, t in enumerate(meas_tasks[gi * 12:(gi + 1) * 12]):
                for arm in ("A", "B", "C"):
                    a = attempt_mod.attempt(
                        t, methods[arm], ledger=ledger, provider=provider,
                        envelopes=envelopes,
                        invocation_id=f"{rid}_g{gi+1}_{arm}_{t.task_id}",
                        timeout_s=timeout_s)
                    a["arm"] = arm
                    a["generation"] = gi + 1
                    note_attempt(a)
    except _RepAbort:
        pass
    rec["spend_usd"] = sum(spend_of(a) for a in rec["attempts"])
    rec["spend_usd"] += _acq_spend(rec.get("G1_acquisition")) + _acq_spend(rec.get("G2_acquisition"))
    return rec


def _acq_spend(acq: dict | None) -> float:
    if not acq:
        return 0.0
    s = 0.0
    for a in acq.get("discovery", []) + acq.get("promotion_parent", []) + acq.get("promotion_candidate", []):
        s += spend_of(a)
    p = acq.get("proposal") or {}
    s += float(p.get("actual_usd") if p.get("actual_usd") is not None
               else p.get("reservation_usd", 0.0))
    return s


def run_study(*, eval_tasks: list, calib_tasks: list, config_path: str,
              ledger, provider, outdir: str,
              timeout_s: float = 300.0) -> dict:
    os.makedirs(outdir, exist_ok=True)
    envelopes = load_envelopes(config_path)
    study_id = "econ001_" + uuid.uuid4().hex[:8]
    study = {"study": "ECON-001", "study_id": study_id, "reps": []}

    calib = _run_calibration(calib_tasks, envelopes, ledger, provider,
                             outdir, timeout_s)
    study["calibration"] = calib
    with open(os.path.join(outdir, "calibration.json"), "w") as f:
        json.dump(calib, f, indent=1, sort_keys=True)

    ordered = sorted(eval_tasks, key=lambda t: t.task_id)
    assert len(ordered) >= 162, f"need 162 eval tasks, have {len(ordered)}"
    for r in range(3):
        try:
            rep = _run_rep(r, ordered[r * 54:(r + 1) * 54], envelopes,
                           ledger, provider, outdir, timeout_s)
        except worker.OverrunAbort as e:
            study["study_aborted"] = f"cost overrun at rep{r + 1}: {e}"
            ledger.note("study_aborted", reason=str(e))
            break
        study["reps"].append(rep)
        with open(os.path.join(outdir, f"{rep['rep']}.json"), "w") as f:
            json.dump(rep, f, indent=1, sort_keys=True)
        ledger.note("rep_finished", rep=rep["rep"], status=rep["status"],
                    spend_usd=round(rep["spend_usd"], 6))

    study["ledger_summary"] = ledger.summary()
    n_inv = (len(study["calibration"]["invocations"])
             + sum(len(r["invocations"]) for r in study["reps"]))
    study["invocation_count"] = n_inv
    with open(os.path.join(outdir, "study.json"), "w") as f:
        json.dump({k: v for k, v in study.items() if k != "reps"},
                  f, indent=1, sort_keys=True)
    return study
