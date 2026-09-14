#!/usr/bin/env python3
"""RIL-ANOMALY-003 driver.

Rebuilt 2026-09-14: the live research loop is implemented (the old draft only
had a safety stub), but it stays spend-gated.

Subcommands:
  self-check   Offline: verify preregistration, sealed truth+schedule hashes,
               cross-validation of the sealed truth against the frozen rows,
               packet building for all 8 rounds with no-truth-leakage
               assertion. No network.
  preflight    Offline: fail-closed gate for primary contact. Checks isolation
               receipt hash + provider-returned model lineage, sealed hashes,
               exactly 192 truth evaluations, identical starting state for
               both arms, no existing primary receipt, frozen spend ceilings.
               No network.
  prepare      Offline: verify the existing seal and write all 8 round packets
               to an output dir. NEVER regenerates tasks or reruns candidate
               evaluations. No API.
  run --spend  LIVE: 4 rounds x 2 arms = 8 fresh independent Chat Completions
               calls to gpt-6-astra. Requires --spend plus a passing preflight.
               Writes the receipt.

Credential handling: the OpenAI API key is NEVER read from files, environment
variables, chat, or logs. It is obtained only as a Sentinel-managed surrogate
via the bundled dynamic_credentials helper (connector `custom.openai`,
bearer_header placement, api.openai.com allowlist).

Anti-rescue: begins with the first primary API request. After that, any change
to the seed failure, protocols, rounds, ceilings, promotion rule, researcher
substrate, evaluator (truth table), schedule, or scoring under this
experiment ID is forbidden; the driver re-verifies every frozen input before
each call and refuses on drift.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
import dynamic_credentials as dc  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP_DIR = HERE.parent
sys.path.insert(0, str(HERE))
import anomaly_core as core  # noqa: E402

PREREG_PATH = EXP_DIR / "RIL_ANOMALY_003_PREREGISTRATION.json"
HTTP_TIMEOUT = 120
MAX_COMPLETION_TOKENS = 4000
CREDENTIAL_NAME = "custom.openai"
API_HOST = "api.openai.com"

ARM_PROTOCOL_FILES = {
    "anomaly_interview": EXP_DIR / "ANOMALY_PROTOCOL.md",
    "ordinary_search": EXP_DIR / "CONTROL_PROTOCOL.md",
}

RECEIPT_FILENAME = "RIL_ANOMALY_003_RECEIPT.json"

VERDICT_PASS = "PASS_RIL_ANOMALY_003_EARNED_RESEARCH_RATCHET"
VERDICT_REVERSE = "REVERSE_RIL_ANOMALY_003_ORDINARY_SEARCH_ADVANTAGE"
VERDICT_NONE = "NO_OBSERVED_RIL_ANOMALY_003_ADVANTAGE"


class FailClosed(Exception):
    def __init__(self, verdict: str, detail: str = ""):
        super().__init__(detail or verdict)
        self.verdict = verdict


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Frozen-input verification
# ---------------------------------------------------------------------------

def load_prereg() -> dict:
    if not PREREG_PATH.exists():
        raise FailClosed("FAIL_PREREG_MISSING", str(PREREG_PATH))
    p = core.read_json(PREREG_PATH)
    if p.get("experiment") != core.EXPERIMENT:
        raise FailClosed("FAIL_PREREG_MISMATCH", "wrong experiment in preregistration")
    if p.get("schema") != core.SCHEMA_PREREG:
        raise FailClosed("FAIL_PREREG_MISMATCH", "wrong preregistration schema")
    return p


def verify_frozen_inputs(prereg: dict) -> tuple[dict, dict]:
    """Verify sealed truth + schedule against preregistration. Returns them."""
    try:
        return core.verify_sealed_artifacts(ROOT, prereg)
    except RuntimeError as exc:
        raise FailClosed("FAIL_SEALED_ARTIFACT", str(exc)) from exc


def verify_isolation(prereg: dict) -> dict:
    """Verify the frozen RIL-API-ISOLATION-002 lineage binding."""
    try:
        return core.verify_isolation_lineage(ROOT)
    except RuntimeError as exc:
        raise FailClosed("FAIL_ISOLATION_LINEAGE", str(exc)) from exc


def starting_states_identical(schedule: dict) -> dict:
    """Prove both arms start from exactly the same state and resources."""
    states = {}
    for arm in core.ARMS:
        states[arm] = {
            "head_state": initial_head_state(schedule),
            "arm_history": {"accepted_lessons": [], "round_outcomes": []},
            "arm_budget_usd": core.ARM_BUDGET_USD,
            "rounds": list(core.ROUNDS),
            "model": core.MODEL_ID,
        }
    blobs = {arm: core.canonical_json(states[arm]) for arm in core.ARMS}
    if len(set(blobs.values())) != 1:
        raise FailClosed("FAIL_MATCHED_START", "arms do not start from identical state/resources")
    return {"arms": list(core.ARMS), "identical": True,
            "head_source": "frozen_historical_selection",
            "accepted_lessons": "empty for both arms"}


def no_primary_receipt_exists(output: str | None = None) -> None:
    """Fail closed if any primary API receipt already exists."""
    hits = [str(p) for p in ROOT.rglob(RECEIPT_FILENAME)]
    if output:
        cand = Path(output) / RECEIPT_FILENAME
        if cand.exists() and str(cand) not in hits:
            hits.append(str(cand))
    if hits:
        raise FailClosed("FAIL_RECEIPT_EXISTS",
                         f"primary API receipt already exists: {hits[0]}; refusing a second run")


def ceilings_frozen() -> dict:
    """Assert the spend ceilings are exactly the frozen values."""
    expected = {"per_arm_usd": 4.0, "total_usd": 8.0, "per_call_hard_ceiling_usd": 1.0}
    actual = {"per_arm_usd": core.ARM_BUDGET_USD, "total_usd": core.TOTAL_BUDGET_USD,
              "per_call_hard_ceiling_usd": core.PER_CALL_HARD_CEILING_USD}
    if actual != expected:
        raise FailClosed("FAIL_CEILINGS", f"spend ceilings drifted: {actual}")
    return actual


def cmd_preflight(output: str | None = None) -> int:
    """Fail-closed gate for primary contact. Offline: no network, no API."""
    prereg = load_prereg()
    isolation = verify_isolation(prereg)
    print(f"isolation : receipt {isolation['receipt_sha256'][:12]}... OK; "
          f"provider-returned models {isolation['provider_returned_models']} OK")
    truth, schedule = verify_frozen_inputs(prereg)
    n_evals = sum(len(t["accepted"]) for t in truth["tasks"].values())
    if n_evals != 192:
        raise FailClosed("FAIL_TRUTH_COUNT", f"truth holds {n_evals} evaluations, need 192")
    print(f"seal      : truth+schedule hashes verify; {n_evals} truth evaluations OK")
    starting_states_identical(schedule)
    print("matched   : both arms identical starting state/resources OK")
    no_primary_receipt_exists(output)
    print("receipt   : no primary API receipt exists OK")
    ceilings_frozen()
    print("ceilings  : $4/arm, $8 total, $1/call frozen OK")
    print("preflight: PASS")
    return 0


def load_public_inputs(schedule: dict) -> tuple[dict, dict]:
    public_contexts, candidate_public = {}, {}
    for tid, t in schedule["tasks"].items():
        public_contexts[tid] = t["public_context"]
        candidate_public[tid] = t["candidates_public"]
    return public_contexts, candidate_public


# ---------------------------------------------------------------------------
# API layer (fresh independent request per call; -002 substrate conventions)
# ---------------------------------------------------------------------------

def _authed_post(payload: dict) -> tuple[urllib.request.Request, bytes]:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        f"https://{API_HOST}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        dc.add_surrogate_to_request(req, CREDENTIAL_NAME, allowed_hosts=[API_HOST])
    except dc.DynamicCredentialError as exc:
        raise FailClosed("FAIL_CREDENTIAL_UNAVAILABLE", str(exc)) from exc
    return req, body


def api_call(prompt_text: str) -> dict:
    """One fresh independent Chat Completions request. Returns call record."""
    payload = {
        "model": core.MODEL_ID,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }
    req, req_bytes = _authed_post(payload)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = resp.status
            raw = dc.read_response_body(resp)
    except urllib.error.HTTPError as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"chat completions -> HTTP {exc.code}")
    except OSError as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"chat completions transport error: {exc}")
    if status != 200:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"chat completions -> HTTP {status}")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"non-JSON API response: {exc}")
    returned_model = str(body.get("model", ""))
    if returned_model != core.MODEL_ID:
        raise FailClosed(
            "FAIL_MODEL_BINDING",
            f"provider returned model {returned_model!r}, pinned {core.MODEL_ID!r}",
        )
    try:
        content = body["choices"][0]["message"]["content"]
        usage = dict(body.get("usage", {}) or {})
    except (KeyError, IndexError, TypeError) as exc:
        raise FailClosed("PROTOCOL_FAILURE_UNCLASSIFIED", f"unexpected chat response shape: {exc}")
    return {
        "request_sha256": core.sha256_bytes(req_bytes),
        "response_sha256": core.sha256_bytes(raw),
        "model_returned": returned_model,
        "http_status": status,
        "raw_content": content,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        },
        "computed_cost_usd": core.computed_cost_usd(
            int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        ),
    }


def extract_json(content: str) -> tuple[dict, bool]:
    """Extract the response JSON object. Returns (obj, had_fencing)."""
    text = content.strip()
    had_fencing = text.startswith("```")
    if had_fencing:
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FailClosed("FAIL_RESPONSE_NOT_JSON", f"response is not a JSON object: {exc}")
    if not isinstance(obj, dict):
        raise FailClosed("FAIL_RESPONSE_NOT_JSON", "response JSON is not an object")
    return obj, had_fencing


# ---------------------------------------------------------------------------
# Round execution
# ---------------------------------------------------------------------------

def build_prompt(arm: str, packet: dict) -> str:
    protocol = ARM_PROTOCOL_FILES[arm].read_text(encoding="utf-8")
    return (
        protocol
        + "\n\n## This round's packet (the ONLY evidence and history you may use)\n\n"
        + json.dumps(packet, indent=2, ensure_ascii=False)
    )


def initial_head_state(schedule: dict) -> dict:
    per_block = {}
    for r in ("1", "2", "3", "4"):
        per_block[r] = {
            tid: list(schedule["tasks"][tid]["historical_selected_order"])
            for tid in schedule["round_blocks"][r]
        }
    return {"general_rule": None, "per_block": per_block, "source": "frozen_historical_selection"}


def head_selections_for_block(head_state: dict, block_no: int, schedule: dict) -> dict[str, list[str]]:
    block = schedule["round_blocks"][str(block_no)]
    if head_state["general_rule"] is not None:
        ok, issues, sels = core.normalize_rule(head_state["general_rule"], block, schedule)
        if not ok or sels is None:
            raise FailClosed("FAIL_HEAD_RULE", f"accepted general rule no longer executes: {issues}")
        return sels
    return {tid: list(head_state["per_block"][str(block_no)][tid]) for tid in block}


def run_arm_round(
    arm: str,
    round_no: int,
    prereg: dict,
    truth: dict,
    schedule: dict,
    head_state: dict,
    arm_history: dict,
    arm_spend: float,
    public_contexts: dict,
    candidate_public: dict,
) -> tuple[dict, float, dict]:
    """Execute one arm-round: build packet, one API call, receiver scoring."""
    block = schedule["round_blocks"][str(round_no)]
    head_sels = head_selections_for_block(head_state, round_no, schedule)
    packet = core.build_packet(
        arm, round_no, schedule,
        {"per_block": {str(round_no): head_sels}}, arm_history,
        public_contexts, candidate_public,
    )
    core.assert_no_truth_leakage(packet)
    prompt = build_prompt(arm, packet)

    # Budget pre-check with a conservative token estimate (chars/3, x2 margin).
    est_input_tokens = len(prompt) // 3 * 2
    est_cost = core.computed_cost_usd(est_input_tokens, MAX_COMPLETION_TOKENS)
    if arm_spend + est_cost > core.ARM_BUDGET_USD:
        raise FailClosed("FAIL_BUDGET_PRECHECK", f"arm {arm} round {round_no} may exceed ${core.ARM_BUDGET_USD}")

    call = api_call(prompt)
    arm_spend += call["computed_cost_usd"]
    if arm_spend > core.ARM_BUDGET_USD:
        raise FailClosed("FAIL_BUDGET_EXCEEDED", f"arm {arm} exceeded ${core.ARM_BUDGET_USD}")
    if call["computed_cost_usd"] > core.PER_CALL_HARD_CEILING_USD:
        raise FailClosed("FAIL_CALL_CEILING", "single call exceeded hard ceiling")

    response, had_fencing = extract_json(call["raw_content"])
    round_record: dict = {
        "arm": arm,
        "round": round_no,
        "call": {k: v for k, v in call.items() if k != "raw_content"},
        "response_had_markdown_fencing": had_fencing,
        "response_contract_ok": True,
    }

    # Contract shape check (presence; content scored only receiver-side).
    contract = core.RESPONSE_CONTRACT
    contract_issues = []
    for field in contract["required"]:
        if field not in response:
            contract_issues.append(f"missing field: {field}")
    if response.get("experiment") != core.EXPERIMENT:
        contract_issues.append("experiment mismatch")
    if response.get("arm") != arm or response.get("round") != round_no:
        contract_issues.append("arm/round mismatch")

    rule = response.get("rule")
    ok, issues, selections = core.normalize_rule(rule, block, schedule) if not contract_issues else (False, contract_issues, None)
    if not ok:
        round_record.update({
            "verdict": "QUARANTINE",
            "quarantine_issues": (contract_issues or []) + (issues or []),
            "method_score": None,
            "head_score": None,
        })
        return round_record, arm_spend, head_state

    method_score = core.score_selections(selections, truth)
    head_score = core.score_selections(head_sels, truth)
    verdict, detail = core.promotion_decision(method_score, head_score)
    round_record.update({
        "verdict": verdict,
        "promotion_detail": detail,
        "method_score": method_score,
        "head_score": head_score,
        "proposed_lesson": response.get("proposed_lesson"),
    })
    if verdict == "PROMOTE":
        new_head = {"general_rule": head_state["general_rule"], "per_block": {
            r: dict(s) for r, s in head_state["per_block"].items()}, "source": head_state["source"]}
        new_head["per_block"][str(round_no)] = {tid: list(selections[tid]) for tid in block}
        if rule.get("type") in core.GENERAL_RULE_TYPES:
            new_head["general_rule"] = rule
            new_head["source"] = f"promoted_general_rule_round_{round_no}"
        else:
            new_head["source"] = f"promoted_block_rule_round_{round_no}"
        head_state = new_head
    return round_record, arm_spend, head_state


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_self_check() -> int:
    prereg = load_prereg()
    truth, schedule = verify_frozen_inputs(prereg)
    print(f"preregistration : {core.SCHEMA_PREREG} OK")
    print(f"truth table     : 16 tasks x 12 candidates sealed OK")
    print(f"schedule        : 4 disjoint round blocks OK")
    # Integrity check WITHOUT re-executing the receiver (the 192 evaluations
    # were done once at seal time): score the frozen historical selections
    # against the sealed truth and require all 32 frozen rows to reproduce
    # exactly. This proves the sealed bytes are the frozen engine's output.
    sys.path.insert(0, str(EXP_DIR))
    import build_truth_table as btt  # noqa: E402
    engine = btt.load_engine()
    rows = core.read_json(btt.ROWS_PATH)
    seal_tasks_src = {t["task_id"]: t for t in core.read_json(btt.SEAL_PATH)["tasks"]}
    checked, mismatches = btt.cross_validate(engine, truth, rows, seal_tasks_src)
    if checked != 32 or mismatches:
        print(f"FAIL: cross-validation {checked} rows, {mismatches} mismatches (need 32/0)")
        return 2
    print(f"cross-validation: {checked} frozen rows reproduced, {mismatches} mismatches OK")
    # Packet build for all 8 rounds + leakage assertion.
    public_contexts, candidate_public = load_public_inputs(schedule)
    for arm in core.ARMS:
        head = initial_head_state(schedule)
        for rnd in core.ROUNDS:
            block = schedule["round_blocks"][str(rnd)]
            head_sels = {tid: list(schedule["tasks"][tid]["historical_selected_order"]) for tid in block}
            packet = core.build_packet(
                arm, rnd, schedule, {"per_block": {str(rnd): head_sels}},
                {"accepted_lessons": [], "round_outcomes": []},
                public_contexts, candidate_public,
            )
            core.assert_no_truth_leakage(packet)
    print("packets         : 8/8 built, no truth leakage OK")
    print("self-check: PASS")
    return 0


def cmd_prepare(output: str) -> int:
    """Offline prepare: verify the EXISTING seal, write the 8 round packets.

    This command NEVER regenerates tasks, NEVER reruns candidate evaluations,
    and NEVER contacts the API. It only reads the sealed schedule/truth and
    verifies their hashes. If the seal is absent or fails verification, it
    fails closed instead of building anything.
    """
    prereg = load_prereg()
    truth, schedule = verify_frozen_inputs(prereg)
    public_contexts, candidate_public = load_public_inputs(schedule)
    out = Path(output)
    if out.exists():
        raise SystemExit("refusing to reuse output path")
    out.mkdir(parents=True)
    manifest = []
    for arm in core.ARMS:
        for rnd in core.ROUNDS:
            block = schedule["round_blocks"][str(rnd)]
            head_sels = {tid: list(schedule["tasks"][tid]["historical_selected_order"]) for tid in block}
            packet = core.build_packet(
                arm, rnd, schedule, {"per_block": {str(rnd): head_sels}},
                {"accepted_lessons": [], "round_outcomes": []},
                public_contexts, candidate_public,
            )
            core.assert_no_truth_leakage(packet)
            prompt = build_prompt(arm, packet)
            p = out / f"packet-{arm}-round-{rnd}.json"
            core.write_json(p, packet)
            (out / f"prompt-{arm}-round-{rnd}.txt").write_text(prompt, encoding="utf-8")
            manifest.append({"arm": arm, "round": rnd, "prompt_chars": len(prompt),
                             "est_input_tokens_chars_over_4": len(prompt) // 4})
    core.write_json(out / "prepare-manifest.json", manifest)
    print(f"wrote 8 packets + prompts to {out} (no API contact)")
    return 0


def cmd_run(spend: bool, output: str) -> int:
    if not spend:
        print("refusing: live run requires --spend (8 paid API calls, "
              f"${core.TOTAL_BUDGET_USD} total ceiling). Nothing was executed.")
        return 2
    prereg = load_prereg()
    # Preflight gate: every condition must hold before the first primary call.
    if cmd_preflight(output) != 0:
        raise FailClosed("FAIL_PREFLIGHT", "preflight did not pass")
    truth, schedule = verify_frozen_inputs(prereg)
    verify_isolation(prereg)
    ceilings_frozen()
    public_contexts, candidate_public = load_public_inputs(schedule)
    out = Path(output)
    if out.exists():
        raise FailClosed("FAIL_OUTPUT_EXISTS", "refusing to reuse output path")

    receipt: dict = {
        "schema": core.SCHEMA_RECEIPT,
        "experiment": core.EXPERIMENT,
        "started_utc": utcnow(),
        "preregistration_sha256": core.sha256_bytes(PREREG_PATH.read_bytes()),
        "sealed_artifacts": prereg["sealed_artifacts"],
        "model_binding": {"pinned_model_id": core.MODEL_ID,
                          "isolation_receipt": core.ISOLATION_002_RECEIPT,
                          "isolation_receipt_sha256": core.ISOLATION_002_RECEIPT_SHA256,
                          "isolation_commit": core.ISOLATION_002_COMMIT,
                          "rule": "provider-returned model lineage must be exactly gpt-6-astra "
                                  "in the frozen isolation receipt; every primary response's "
                                  "provider-returned model must equal the pinned id"},
        "budget": {"per_arm_usd": core.ARM_BUDGET_USD, "total_usd": core.TOTAL_BUDGET_USD},
        "anti_rescue": "began with the first primary API request of this run",
        "arms": {},
        "key_material_in_receipt": False,
    }

    total_spend = 0.0
    try:
        for arm in core.ARMS:
            head_state = initial_head_state(schedule)
            arm_history: dict = {"accepted_lessons": [], "round_outcomes": []}
            arm_spend = 0.0
            rounds = []
            for rnd in core.ROUNDS:
                # Re-verify frozen inputs before EVERY primary contact.
                verify_frozen_inputs(prereg)
                rec, arm_spend, head_state = run_arm_round(
                    arm, rnd, prereg, truth, schedule, head_state, arm_history,
                    arm_spend, public_contexts, candidate_public,
                )
                rounds.append(rec)
                arm_history["round_outcomes"].append({
                    "round": rnd, "verdict": rec["verdict"],
                    "method_task_successes": (rec.get("method_score") or {}).get("task_successes"),
                    "head_task_successes": (rec.get("head_score") or {}).get("task_successes"),
                })
                if rec["verdict"] == "PROMOTE":
                    arm_history["accepted_lessons"].append(rec.get("proposed_lesson"))
            total_spend += arm_spend
            if total_spend > core.TOTAL_BUDGET_USD:
                raise FailClosed("FAIL_BUDGET_EXCEEDED", "total budget exceeded")
            # Arm summary: receiver-confirmed results, API usage, final head.
            final_sels: dict[str, list[str]] = {}
            for r in ("1", "2", "3", "4"):
                final_sels.update(head_selections_for_block(head_state, int(r), schedule))
            final_head_score = core.score_selections(final_sels, truth)
            prompt_tokens = sum(r["call"]["usage"]["prompt_tokens"] for r in rounds)
            completion_tokens = sum(r["call"]["usage"]["completion_tokens"] for r in rounds)
            receipt["arms"][arm] = {
                "rounds": rounds,
                "promotions": sum(1 for r in rounds if r["verdict"] == "PROMOTE"),
                "quarantines": sum(1 for r in rounds if r["verdict"] == "QUARANTINE"),
                "rejections": sum(1 for r in rounds if r["verdict"] == "REJECT"),
                "receiver_confirmed_task_successes_final_head": final_head_score["task_successes"],
                "receiver_confirmed_total_evals_to_first_success_final_head":
                    final_head_score["total_evaluations_to_first_success"],
                "receiver_evaluations_shared_truth_table": 192,
                "api_prompt_tokens": prompt_tokens,
                "api_completion_tokens": completion_tokens,
                "api_dollars_computed": round(arm_spend, 6),
                "final_accepted_head": head_state,
            }
    except FailClosed as exc:
        receipt["terminal_failure"] = {"verdict": exc.verdict, "detail": str(exc)}
        receipt["ended_utc"] = utcnow()
        out.mkdir(parents=True)
        core.write_json(out / RECEIPT_FILENAME, receipt)
        print(f"terminal: {exc.verdict}: {exc}")
        return 2

    a = receipt["arms"]["anomaly_interview"]["promotions"]
    o = receipt["arms"]["ordinary_search"]["promotions"]
    diff = a - o
    if diff >= 2:
        verdict = VERDICT_PASS
    elif diff <= -2:
        verdict = VERDICT_REVERSE
    else:
        verdict = VERDICT_NONE
    receipt.update({
        "promotion_difference_anomaly_minus_ordinary": diff,
        "formal_verdict": verdict,
        "total_spend_usd": round(total_spend, 6),
        "ended_utc": utcnow(),
    })
    out.mkdir(parents=True)
    rsha = core.write_json(out / RECEIPT_FILENAME, receipt)
    print(f"verdict: {verdict} (anomaly_interview {a} vs ordinary_search {o}; spend ${total_spend:.6f})")
    print(f"receipt sha256: {rsha}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-check")
    pf = sub.add_parser("preflight")
    pf.add_argument("--output", default=None)
    p = sub.add_parser("prepare")
    p.add_argument("--output", required=True)
    r = sub.add_parser("run")
    r.add_argument("--spend", action="store_true")
    r.add_argument("--output", required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "self-check":
            return cmd_self_check()
        if args.cmd == "preflight":
            return cmd_preflight(args.output)
        if args.cmd == "prepare":
            return cmd_prepare(args.output)
        if args.cmd == "run":
            return cmd_run(args.spend, args.output)
    except FailClosed as exc:
        print(f"terminal: {exc.verdict}: {exc}")
        return 2
    raise SystemExit("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
