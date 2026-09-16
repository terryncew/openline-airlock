"""Acquisition pipeline: discovery -> proposal -> promotion -> accept/reject.

Acceptance is strict improvement only: the candidate must be strictly
better on at least one axis (verified output, cost) and worse on none.
Equal-equal is a rejection: no change without evidence.
"""
from __future__ import annotations

import uuid

from . import attempt as attempt_mod
from . import extract, prompts, tokens, worker


def _feedback(task, att: dict) -> str:
    code = att.get("code") or ""
    return (
        f"task_id={task.task_id} family={task.family}\n"
        f"verdict={'PASS' if att.get('verdict') else 'FAIL'} "
        f"({att.get('reason', '?')}) "
        f"settled_cost=${(att.get('actual_usd') or 0):.6f}\n"
        f"TASK STATEMENT (<=600):\n{tokens.truncate_to(task.statement, 600)}\n"
        f"ATTEMPTED PATCH (<=800):\n{tokens.truncate_to(code, 800)}\n"
    )


def run_acquisition(*, name: str, parent_method: str,
                    discovery_tasks: list, promotion_tasks: list,
                    ledger, provider, envelopes,
                    timeout_s: float = 300.0) -> dict:
    assert len(discovery_tasks) == 3 and len(promotion_tasks) == 6
    rec: dict = {"name": name, "decision": "reject", "reason": ""}
    aid = "acq_" + uuid.uuid4().hex[:8]
    rec["acquisition_id"] = aid

    # 1. Discovery with the parent method.
    disc = []
    for i, t in enumerate(discovery_tasks):
        a = attempt_mod.attempt(
            t, parent_method, ledger=ledger, provider=provider,
            envelopes=envelopes,
            invocation_id=f"{aid}_disc{i}", timeout_s=timeout_s)
        disc.append(a)
    rec["discovery"] = disc
    if any(a["status"] in ("overrun_abort",) for a in disc):
        rec["reason"] = "aborted_in_discovery"
        return rec

    # 2. Proposal.
    fb = [_feedback(t, a) for t, a in zip(discovery_tasks, disc)]
    instructions, input_text = prompts.build_proposal_prompt(parent_method, fb)
    try:
        pres = worker.invoke(
            instructions=instructions, input_text=input_text,
            envelope=envelopes["proposal"], ledger=ledger, provider=provider,
            invocation_id=f"{aid}_proposal", timeout_s=timeout_s)
    except worker.OverrunAbort as e:
        rec["reason"] = f"proposal_overrun: {e}"
        raise
    rec["proposal"] = {
        "status": pres.status,
        "reservation_usd": pres.reservation_usd,
        "actual_usd": pres.actual_usd,
        "request_id": pres.request_id,
    }
    if pres.status != "ok" or not pres.text:
        rec["reason"] = f"proposal_{pres.status}"
        return rec
    delta = extract.extract_delta(pres.text)
    if delta is None:
        rec["reason"] = "delta_extraction_failed"
        return rec
    try:
        candidate = prompts.apply_delta(parent_method, delta)
    except tokens.CapExceeded as e:
        rec["reason"] = f"rendered_method_over_cap: {e}"
        return rec
    except ValueError as e:
        # Malformed directive: the model failed to produce a usable delta.
        # Same category as delta_extraction_failed -- reject, never crash.
        rec["reason"] = f"delta_malformed: {e}"
        return rec
    rec["candidate_method_tokens"] = tokens.count(candidate)

    # 3. Promotion: 3 parent + 3 candidate on disjoint tasks.
    parent_tasks, cand_tasks = promotion_tasks[:3], promotion_tasks[3:]
    promo_p, promo_c = [], []
    for i, t in enumerate(parent_tasks):
        promo_p.append(attempt_mod.attempt(
            t, parent_method, ledger=ledger, provider=provider,
            envelopes=envelopes,
            invocation_id=f"{aid}_promoP{i}", timeout_s=timeout_s))
    for i, t in enumerate(cand_tasks):
        promo_c.append(attempt_mod.attempt(
            t, candidate, ledger=ledger, provider=provider,
            envelopes=envelopes,
            invocation_id=f"{aid}_promoC{i}", timeout_s=timeout_s))
    rec["promotion_parent"] = promo_p
    rec["promotion_candidate"] = promo_c

    vp = sum(a.get("verdict", 0) for a in promo_p)
    vc = sum(a.get("verdict", 0) for a in promo_c)
    cp = sum(a.get("actual_usd") or a.get("reservation_usd", 0) for a in promo_p)
    cc = sum(a.get("actual_usd") or a.get("reservation_usd", 0) for a in promo_c)
    rec["promotion_score"] = {"vp": vp, "vc": vc, "cp": cp, "cc": cc}

    # 4. Strict-improvement acceptance.
    if (vc > vp) or (vc == vp and cc < cp):
        rec["decision"] = "accept"
        rec["method"] = candidate
        rec["reason"] = f"vc={vc} vp={vp} cc={cc:.6f} cp={cp:.6f}"
    else:
        rec["reason"] = (f"no_strict_improvement "
                         f"(vc={vc} vp={vp} cc={cc:.6f} cp={cp:.6f})")
    return rec
