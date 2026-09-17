"""Offline end-to-end fixtures: fake provider, real tasks, real evaluation.

No network, no spend. Every verdict path must fire deterministically,
including pre-contact reservation refusal and unresolved exposure.
"""
import json
import re
import sys

sys.path.insert(0, "src")

from econ import acquire, attempt as attempt_mod
from econ import corpus, evaluate, extract, ledger as ledger_mod
from econ import orchestrate, prompts, report, tokens, worker

FIXED_CLOCK = lambda: 1700000000.0  # noqa: E731


def payload(text, in_tok=100, out_tok=50, cached=0, cw=0, reasoning=0,
            rid="resp_test"):
    return {
        "id": rid, "object": "response", "status": "completed",
        "output": [{"type": "message", "id": "m1", "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text,
                                 "annotations": []}]}],
        "usage": {"input_tokens": in_tok,
                  "input_tokens_details": {"cached_tokens": cached,
                                           "cache_write_tokens": cw},
                  "output_tokens": out_tok,
                  "output_tokens_details": {"reasoning_tokens": reasoning},
                  "total_tokens": in_tok + out_tok},
    }


class FuncProvider(worker.Provider):
    def __init__(self, fn):
        self.fn = fn
        self.requests = 0

    def post(self, body, headers, timeout):
        self.requests += 1
        return self.fn(body, headers, self.requests)


def envelopes():
    return {
        "solving": {"name": "solving", "max_input_tokens": 5000,
                    "max_output_tokens": 3000, "reservation_usd": 0.11},
        "proposal": {"name": "proposal", "max_input_tokens": 7000,
                     "max_output_tokens": 2000, "reservation_usd": 0.11},
        "preflight": {"name": "preflight", "max_input_tokens": 128,
                      "max_output_tokens": 100, "reservation_usd": 0.01},
    }


def ledger(path="/tmp/econ_test_ledger.jsonl", budget=50.0):
    import os
    if os.path.exists(path):
        os.remove(path)
    return ledger_mod.Ledger(budget, path, clock=FIXED_CLOCK)


def norm(obj):
    s = json.dumps(obj, sort_keys=True, default=str)
    s = re.sub(r"inv_[0-9a-f]{12}", "inv_X", s)
    s = re.sub(r"rsv_[0-9a-f]{12}", "rsv_X", s)
    s = re.sub(r"acq_[0-9a-f]{8}", "acq_X", s)
    s = re.sub(r"resp_[A-Za-z0-9]+", "resp_X", s)
    s = re.sub(r"econ001_[0-9a-f]{8}", "econ_X", s)
    return s


results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f" -- {detail}" if detail and not cond else ""))


# 1. Settlement math -------------------------------------------------------
u = {"input_tokens": 1000,
     "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 50},
     "output_tokens": 200, "output_tokens_details": {"reasoning_tokens": 40}}
expect = ((1000 - 100 - 50) * 4.00 + 100 * 0.40 + 50 * 5.00 + 200 * 20.00) / 1e6
check("settle_math", abs(worker.settle_cost(u) - expect) < 1e-12, worker.settle_cost(u))

# 2. Pre-contact refusal: input over cap -> no request, no reservation ------
lg = ledger()
fp = worker.FakeProvider([("ok", payload("x"))])
env = dict(envelopes()["solving"]); env["max_input_tokens"] = 10
r = worker.invoke(instructions="i", input_text="0123456789ABCDEF" * 20,
                  envelope=env, ledger=lg, provider=fp, invocation_id="t2")
check("refused_precontact_no_request",
      r.status == "refused_precontact" and fp.requests == 0 and lg.encumbered == 0.0,
      f"{r.status} reqs={fp.requests} enc={lg.encumbered}")

# 3. No retry: HTTP 500 -> exactly one request, unresolved, retained --------
lg = ledger()
fp = worker.FakeProvider([("http_error", 500, {"error": "boom"})])
r = worker.invoke(instructions="i", input_text="t", envelope=envelopes()["solving"],
                  ledger=lg, provider=fp, invocation_id="t3")
check("no_retry_single_request_unresolved_retained",
      fp.requests == 1 and r.status == "unresolved"
      and abs(lg.summary()["unresolved_retained"] - 0.11) < 1e-9,
      f"{r.status} reqs={fp.requests} {lg.summary()}")

# 4. Timeout -> unresolved, reservation retained ----------------------------
lg = ledger()
fp = worker.FakeProvider([("timeout",)])
r = worker.invoke(instructions="i", input_text="t", envelope=envelopes()["solving"],
                  ledger=lg, provider=fp, invocation_id="t4")
check("timeout_unresolved_retains",
      r.status == "unresolved" and abs(lg.summary()["unresolved_retained"] - 0.11) < 1e-9,
      r.status)

# 5. 200 without usage -> unresolved ----------------------------------------
lg = ledger()
p = payload("x"); del p["usage"]
fp = worker.FakeProvider([("ok", p)])
r = worker.invoke(instructions="i", input_text="t", envelope=envelopes()["solving"],
                  ledger=lg, provider=fp, invocation_id="t5")
check("missing_usage_unresolved",
      r.status == "unresolved" and lg.summary()["unresolved_retained"] == 0.11, r.status)

# 6. Overrun -> abort --------------------------------------------------------
lg = ledger()
# usage implying actual $0.20 > reservation $0.11
fp = worker.FakeProvider([("ok", payload("x", in_tok=1000, out_tok=9500))])
try:
    worker.invoke(instructions="i", input_text="t", envelope=envelopes()["solving"],
                  ledger=lg, provider=fp, invocation_id="t6")
    check("overrun_abort", False, "no exception")
except worker.OverrunAbort:
    check("overrun_abort", True)

# 7. Extraction --------------------------------------------------------------
check("extract_ok", extract.extract_file_block("```python\nX=1\n```") == "X=1")
check("extract_missing", extract.extract_file_block("no block") is None)
check("extract_multi", extract.extract_file_block("```python\na\n```\n```python\nb\n```") is None)
check("extract_delta", extract.extract_delta("```delta\nADD_STEP: hi\n```") == "ADD_STEP: hi")

# 8. Delta cap ----------------------------------------------------------------
big = "\n".join(f"ADD_STEP: {'y' * 200}" for _ in range(60))
try:
    prompts.apply_delta(prompts.BASE_METHOD, big)
    check("delta_cap", False, "no cap")
except tokens.CapExceeded:
    check("delta_cap", True)

# 9. Ledger accounting ---------------------------------------------------------
lg = ledger(budget=1.0)
rsv = lg.reserve(0.11, "a", "solving")
lg.settle(rsv["reservation_id"], "a", 0.11, 0.05, {"input_tokens": 1}, "ok")
lg2note = lg.note("x", foo=1)
try:
    lg.reserve(0.96, "b", "solving")
    check("ledger_budget_gate", False, "reserve succeeded over budget")
except ledger_mod.InsufficientBudget:
    s = lg.summary()
    check("ledger_budget_gate",
          abs(s["settled"] - 0.05) < 1e-9 and abs(s["headroom"] - 0.95) < 1e-9, s)

# 10. Corpus integrity (reference passes / buggy fails / packet caps) -----------
pools = corpus.build_corpus(master_seed=7, n_dev=9, n_eval=54, n_calib=3)
viol = 0
for pool, tasks in pools.items():
    for t in tasks:
        vr, _ = evaluate.evaluate(corpus.TARGET_FILENAME, t.reference_code, {}, t.hidden_tests)
        vb, _ = evaluate.evaluate(corpus.TARGET_FILENAME, t.target_code, {}, t.hidden_tests)
        t.packet()
        if not (vr == 1 and vb == 0):
            viol += 1
check("corpus_integrity", viol == 0, f"violations={viol}")

# 11. Acquisition accept vs reject ----------------------------------------------
def acq_provider_factory(usage_p, usage_c):
    ref_by_task = {}
    def fn(body, headers, n):
        inv = headers.get("X-Client-Request-Id", "")
        txt = body["input"]
        m = re.search(r"TASK (\S+)", txt)
        if "proposal" in body.get("instructions", "") or "method delta" in body.get("instructions", ""):
            return 200, payload("```delta\nADD_STEP: Re-verify the fixed file against the statement before output.\n```",
                                in_tok=500, out_tok=60)
        tid = m.group(1) if m else ""
        code = ref_by_task.get(tid, "X=1")
        if "_promoP" in inv:
            return 200, payload(f"```python\n{code}\n```", **usage_p)
        if "_promoC" in inv:
            return 200, payload(f"```python\n{code}\n```", **usage_c)
        return 200, payload(f"```python\n{code}\n```", in_tok=400, out_tok=60)
    fn.ref_by_task = ref_by_task
    return fn

dev9 = pools["dev"]
for name, up, uc, want in [
    ("acq_reject_equal", {"in_tok": 400, "out_tok": 60}, {"in_tok": 400, "out_tok": 60}, "reject"),
    ("acq_accept_cheaper", {"in_tok": 900, "out_tok": 300}, {"in_tok": 200, "out_tok": 40}, "accept"),
]:
    lg = ledger()
    fac = acq_provider_factory(up, uc)
    for t in dev9:
        fac.ref_by_task[t.task_id] = t.reference_code
    fp = FuncProvider(fac)
    rec = acquire.run_acquisition(
        name=name, parent_method=prompts.BASE_METHOD,
        discovery_tasks=dev9[0:3], promotion_tasks=dev9[3:9],
        ledger=lg, provider=fp, envelopes=envelopes())
    check(name, rec["decision"] == want, f"got {rec['decision']}: {rec['reason']}")

# 12. Deterministic rep ----------------------------------------------------------
def perfect_provider_factory(tasks):
    by_id = {t.task_id: t.reference_code for t in tasks}
    def fn(body, headers, n):
        if "connectivity check" in body.get("instructions", ""):
            i, x = body["instructions"], body["input"]
            return 200, payload("OK", in_tok=tokens.count(i) + tokens.count(x), out_tok=5)
        if "method delta" in body.get("instructions", ""):
            return 200, payload("```delta\nADD_STEP: Re-verify the fixed file against the statement before output.\n```",
                                in_tok=600, out_tok=60)
        m = re.search(r"TASK (\S+)", body["input"])
        tid = m.group(1) if m else ""
        return 200, payload(f"```python\n{by_id.get(tid, 'X=1')}\n```", in_tok=800, out_tok=120)
    return fn

rep_tasks = pools["eval"]  # 54 tasks
calib_tasks = pools["calib"]
def run_once(tag):
    lg = ledger(path=f"/tmp/econ_det_{tag}.jsonl", budget=50.0)
    fp = FuncProvider(perfect_provider_factory(rep_tasks + calib_tasks))
    rep = orchestrate._run_rep(0, rep_tasks, envelopes(), lg, fp, "/tmp/econ_det")
    return rep, lg.summary()

rep1, sum1 = run_once("a")
rep2, sum2 = run_once("b")
check("rep_deterministic", norm(rep1) == norm(rep2),
      "rep records differ")
check("rep_all_verified", all(a["verdict"] == 1 for a in rep1["attempts"]),
      f'{sum(a["verdict"] for a in rep1["attempts"])}/{len(rep1["attempts"])}')
check("rep_invocation_count", len(rep1["invocations"]) == 128, len(rep1["invocations"]))

# 13. Report blocks separate ------------------------------------------------------
study = {"study_id": "t", "reps": [rep1], "ledger_summary": sum1,
         "invocation_count": 128}
rp = report.build_report(study)
check("report_blocks",
      "unit_cost_advantage_descriptive" in rp
      and "observed_acquisition_payback" in rp
      and "projected_future_payback" in rp
      and rp["observed_acquisition_payback"]["G1_B_vs_A"]["observed_payback_earned"] in (True, False))

print()
fails = [n for n, ok, d in results if not ok]
print(f"{len(results) - len(fails)}/{len(results)} fixtures pass")
sys.exit(1 if fails else 0)
