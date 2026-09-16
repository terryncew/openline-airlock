"""One measured attempt: worker invocation + extraction + local evaluation.

Cost is incurred (settled or retained) regardless of verdict. The
economics count all spend; the verdict counts only verified output.
"""
from __future__ import annotations

from . import evaluate, extract, prompts, worker
from .corpus import TARGET_FILENAME


def attempt(task, method_text, *, ledger, provider, envelopes,
            invocation_id: str, timeout_s: float = 300.0,
            stop_file: str | None = None,
            raw_dir: str | None = None) -> dict:
    instructions, input_text = prompts.build_solving_prompt(
        method_text, task.packet())
    rec = {
        "invocation_id": invocation_id,
        "task_id": task.task_id,
        "family": task.family,
    }
    try:
        res = worker.invoke(
            instructions=instructions, input_text=input_text,
            envelope=envelopes["solving"], ledger=ledger, provider=provider,
            invocation_id=invocation_id, timeout_s=timeout_s,
            stop_file=stop_file, raw_dir=raw_dir)
    except worker.OverrunAbort as e:
        rec.update(status="overrun_abort", verdict=0, error=str(e))
        raise
    if res.status == "stopped":
        # Operator stop: no call issued, no reservation. Halt the study
        # before the next paid invocation.
        rec.update(status="stopped", verdict=0, reason="operator_stop",
                   error=res.error)
        raise worker.OperatorStop(f"operator stop before {invocation_id}")
    rec.update(
        status=res.status,
        reservation_usd=res.reservation_usd,
        actual_usd=res.actual_usd,
        local_input_tokens=res.local_input_tokens,
        provider_input_tokens=(res.usage or {}).get("input_tokens"),
        request_id=res.request_id,
        raw_path=res.raw_path,
    )
    if res.status == "refused_precontact":
        rec.update(verdict=0, reason="refused_precontact", error=res.error)
        return rec
    if res.status == "unresolved":
        # Reservation retained as exposure; no verified output.
        rec.update(verdict=0, reason="unresolved_exposure", error=res.error)
        return rec
    # status ok from here.
    code = extract.extract_file_block(res.text or "")
    rec["extracted_chars"] = len(code) if code else 0
    if code is None:
        rec.update(verdict=0, reason="extraction_failed")
        return rec
    rec["code"] = code
    v, why = evaluate.evaluate(TARGET_FILENAME, code, task.support_files,
                               task.hidden_tests)
    rec.update(verdict=v, reason=why)
    return rec
