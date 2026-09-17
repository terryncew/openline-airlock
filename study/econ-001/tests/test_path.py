"""Path-revision proof fixtures: raw persistence, malformed-delta rejection,
stop-before-next-call control, and exposure accounting.

All offline: fake provider, real tasks, zero spend. Each fixture proves a
property the 2026-09-16 pause showed was missing.
"""
import json
import os
import sys

sys.path.insert(0, "src")

from econ import acquire, attempt as attempt_mod
from econ import corpus, ledger as ledger_mod
from econ import orchestrate, prompts, tokens, worker

FIXED_CLOCK = lambda: 1700000000.0  # noqa: E731
BASE = "/tmp/econ_path"


def payload(text, in_tok=100, out_tok=50, rid="resp_test"):
    return {
        "id": rid, "object": "response", "status": "completed",
        "output": [{"type": "message", "id": "m1", "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text,
                                 "annotations": []}]}],
        "usage": {"input_tokens": in_tok,
                  "input_tokens_details": {"cached_tokens": 0,
                                           "cache_write_tokens": 0},
                  "output_tokens": out_tok,
                  "output_tokens_details": {"reasoning_tokens": 0},
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


def fresh(path):
    import shutil
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)
    return path


def ledger(path, budget=50.0):
    return ledger_mod.Ledger(budget, fresh(path), clock=FIXED_CLOCK)


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name
          + (f" -- {detail}" if detail and not cond else ""))


def invoke_kwargs(**kw):
    d = dict(instructions="do the task", input_text="TASK x",
             envelope=envelopes()["solving"], ledger=kw.pop("ledger"),
             provider=kw.pop("provider"), invocation_id=kw.pop("invocation_id"),
             clock=FIXED_CLOCK)
    d.update(kw)
    return d


# 1. Raw response persisted before parsing --------------------------------
raw_dir = fresh(BASE + "_raw") + "_d"
os.makedirs(raw_dir, exist_ok=True)
lg = ledger(BASE + "_raw_ledger.jsonl")
body_text = "```python\nX=1\n```"
fp = FuncProvider(lambda b, h, n: (200, payload(body_text, rid="resp_raw1")))
res = worker.invoke(**invoke_kwargs(ledger=lg, provider=fp,
                                    invocation_id="raw_call1", raw_dir=raw_dir))
raw_path = os.path.join(raw_dir, "raw_call1.json")
check("raw_written_ok_path", os.path.exists(raw_path), raw_path)
doc = json.load(open(raw_path))
check("raw_matches_payload_verbatim",
      doc["response"]["id"] == "resp_raw1"
      and doc["http_status"] == 200
      and doc["response"]["usage"]["output_tokens"] == 50,
      "payload mismatch")
check("raw_before_parse_link", res.raw_path == raw_path, res.raw_path)

# raw written even when no parsing/settlement happens (non-200)
fp2 = FuncProvider(lambda b, h, n: (400, {"error": "bad"}))
res2 = worker.invoke(**invoke_kwargs(
    ledger=ledger(BASE + "_raw_ledger2.jsonl"), provider=fp2,
    invocation_id="raw_call2", raw_dir=raw_dir))
check("raw_written_non200",
      os.path.exists(os.path.join(raw_dir, "raw_call2.json"))
      and res2.status == "unresolved",
      f"{res2.status}")
d2 = json.load(open(os.path.join(raw_dir, "raw_call2.json")))
check("raw_non200_content", d2["http_status"] == 400
      and d2["response"] == {"error": "bad"}, "content mismatch")

# raw written when usage is missing (unresolved path: parse never reached)
no_usage = {"id": "resp_nu", "object": "response", "status": "completed",
            "output": []}
fp3 = FuncProvider(lambda b, h, n: (200, no_usage))
res3 = worker.invoke(**invoke_kwargs(
    ledger=ledger(BASE + "_raw_ledger3.jsonl"), provider=fp3,
    invocation_id="raw_call3", raw_dir=raw_dir))
check("raw_written_missing_usage",
      os.path.exists(os.path.join(raw_dir, "raw_call3.json"))
      and res3.status == "unresolved",
      f"{res3.status}")

# 2. Malformed delta rejects without crashing -----------------------------
pools = corpus.load_corpus("corpus/corpus.json")
dev9 = pools["dev"][0:9]
by_id = {t.task_id: t.reference_code for t in dev9}
MALFORMED = "```delta\nREPLACE_STEP\n  recheck the file before finishing\n```"


def acq_fn(body, headers, n):
    if "method delta" in body.get("instructions", ""):
        return 200, payload(MALFORMED, in_tok=600, out_tok=60)
    m = __import__("re").search(r"TASK (\S+)", body["input"])
    tid = m.group(1) if m else ""
    return 200, payload(f"```python\n{by_id.get(tid, 'X=1')}\n```",
                        in_tok=800, out_tok=120)


os.makedirs(fresh(BASE + "_malformed_raw") + "_d", exist_ok=True)
crashed = False
try:
    rec = acquire.run_acquisition(
        name="malformed_test", parent_method=prompts.BASE_METHOD,
        discovery_tasks=dev9[0:3], promotion_tasks=dev9[3:9],
        ledger=ledger(BASE + "_malformed_ledger.jsonl"),
        provider=FuncProvider(acq_fn), envelopes=envelopes(),
        raw_dir=os.path.join(fresh(BASE + "_malformed_raw") + "_d", ""))
except Exception as e:  # noqa: BLE001 -- any escape is the failure
    crashed = True
    rec = {"reason": f"CRASH: {type(e).__name__}: {e}"}
check("malformed_no_crash", not crashed, rec.get("reason", ""))
check("malformed_rejects",
      str(rec.get("reason", "")).startswith("delta_malformed"),
      rec.get("reason", ""))
check("malformed_raw_preserved",
      rec.get("proposal", {}).get("raw_path") is not None
      and os.path.exists(rec["proposal"]["raw_path"]),
      "proposal raw response not persisted")

# 3. Stop-before-next-call control -----------------------------------------
STOP = fresh(BASE + "_STOP")
lg = ledger(BASE + "_stop_ledger.jsonl")
fp = FuncProvider(lambda b, h, n: (200, payload("```python\nX=1\n```")))
r1 = worker.invoke(**invoke_kwargs(ledger=lg, provider=fp,
                                   invocation_id="stop_call1",
                                   stop_file=STOP))
check("stop_first_call_ok", r1.status == "ok" and fp.requests == 1,
      f"{r1.status} reqs={fp.requests}")
open(STOP, "w").write("operator stop\n")
r2 = worker.invoke(**invoke_kwargs(ledger=lg, provider=fp,
                                   invocation_id="stop_call2",
                                   stop_file=STOP))
check("stop_second_call_blocked", r2.status == "stopped"
      and fp.requests == 1, f"{r2.status} reqs={fp.requests}")
reserves2 = [e for e in lg.entries
             if e.get("kind") == "reserve"
             and e.get("invocation_id") == "stop_call2"]
check("stop_no_reservation", reserves2 == [], f"{len(reserves2)} reserves")
notes = [e for e in lg.entries if e.get("kind") == "stopped_before_contact"]
check("stop_noted", len(notes) == 1, f"{len(notes)} notes")

# stop halts an attempt loop mid-run via OperatorStop
STOP2 = fresh(BASE + "_STOP2")
lg2 = ledger(BASE + "_stop_ledger2.jsonl")
fp_b = FuncProvider(lambda b, h, n: (200, payload(
    f"```python\n{by_id[dev9[0].task_id]}\n```", in_tok=800, out_tok=120)))
task = dev9[0]
a1 = attempt_mod.attempt(task, prompts.BASE_METHOD, ledger=lg2,
                         provider=fp_b, envelopes=envelopes(),
                         invocation_id="loop1", stop_file=STOP2)
open(STOP2, "w").write("stop\n")
halted = False
try:
    attempt_mod.attempt(task, prompts.BASE_METHOD, ledger=lg2,
                        provider=fp_b, envelopes=envelopes(),
                        invocation_id="loop2", stop_file=STOP2)
except worker.OperatorStop:
    halted = True
check("stop_raises_operator_stop", halted and fp_b.requests == 1,
      f"halted={halted} reqs={fp_b.requests}")

# 4. Full run_study stops cleanly mid-run, zero further paid calls ---------
STOP3 = fresh(BASE + "_STOP3")
outdir = fresh(BASE + "_studyout")
os.makedirs(outdir, exist_ok=True)
calib_tasks = pools["calib"]
by_c = {t.task_id: t.reference_code for t in calib_tasks}
import re as _re


def study_fn(body, headers, n):
    if n == 2:
        # operator places the stop file DURING the second call's flight
        open(STOP3, "w").write("stop\n")
    if "connectivity check" in body.get("instructions", ""):
        i, x = body["instructions"], body["input"]
        # provider bills local count + 10 framing tokens (frozen finding)
        return 200, payload("OK",
                            in_tok=tokens.count(i) + tokens.count(x) + 10,
                            out_tok=5)
    m = _re.search(r"TASK (\S+)", body["input"])
    tid = m.group(1) if m else ""
    return 200, payload(f"```python\n{by_c.get(tid, 'X=1')}\n```",
                        in_tok=800, out_tok=120)


lg3 = ledger(BASE + "_stop_ledger3.jsonl")
fp_c = FuncProvider(study_fn)
study = orchestrate.run_study(
    eval_tasks=pools["eval"], calib_tasks=calib_tasks,
    config_path="CONFIG.json", ledger=lg3, provider=fp_c, outdir=outdir,
    stop_file=STOP3, raw_dir=os.path.join(outdir, "raw"))
check("study_stops_cleanly", study.get("status") == "stopped_operator"
      and study.get("stop_reason"), study.get("status"))
check("study_no_further_calls", fp_c.requests == 2, f"reqs={fp_c.requests}")
check("study_json_records_stop",
      json.load(open(os.path.join(outdir, "study.json")))["status"]
      == "stopped_operator", "study.json mismatch")
stopped_notes = [e for e in lg3.entries
                 if e.get("kind") == "study_stopped_operator"]
check("study_stop_noted", len(stopped_notes) == 1, f"{len(stopped_notes)}")
check("study_exposure_buckets",
      set(study["exposure"]) == {"settled_usd", "unresolved_retained_usd",
                                 "in_flight_open_usd", "encumbered_usd"},
      str(study["exposure"]))

# 5. Exposure accounting: settled + unresolved + in-flight ------------------
lg4 = ledger(BASE + "_exp_ledger.jsonl")
fp_ok = FuncProvider(lambda b, h, n: (200, payload("```python\nX=1\n```",
                                                  in_tok=100, out_tok=50)))
worker.invoke(**invoke_kwargs(ledger=lg4, provider=fp_ok,
                              invocation_id="exp_settled"))
fp_nu = FuncProvider(lambda b, h, n: (200, no_usage))
worker.invoke(**invoke_kwargs(ledger=lg4, provider=fp_nu,
                              invocation_id="exp_unresolved"))
rsv = lg4.reserve(0.11, "exp_inflight", "solving")  # open: never settled
s = lg4.summary()
check("exposure_settled", s["settled"] > 0, str(s))
check("exposure_unresolved", s["unresolved_retained"] == 0.11, str(s))
check("exposure_inflight", s["reserved_open"] == 0.11, str(s))
check("exposure_encumbered_sums",
      abs(s["encumbered"] - (s["settled"] + s["unresolved_retained"]
                             + s["reserved_open"])) < 1e-9, str(s))

# 6. Prior open reserves surfaced at startup -------------------------------
opens = lg4.open_reserves()
check("open_reserves_listed",
      len(opens) == 1 and opens[0]["invocation_id"] == "exp_inflight",
      f"{len(opens)}")
lg5 = ledger_mod.Ledger(50.0, BASE + "_exp_ledger.jsonl", clock=FIXED_CLOCK)
check("open_reserves_survive_replay",
      [e["invocation_id"] for e in lg5.open_reserves()] == ["exp_inflight"],
      "replay lost the open reserve")

n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"\n{len(results) - n_fail}/{len(results)} path fixtures pass")
sys.exit(1 if n_fail else 0)
