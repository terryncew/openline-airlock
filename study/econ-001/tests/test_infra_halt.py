"""Infrastructure-halt proof fixtures: credential-service / pre-dispatch
failure stops the study immediately with zero subsequent dispatches.

All offline: fake provider, real tasks, zero spend. Each fixture proves a
property the 2026-09-16 ECON-001-R2 egress outage showed was missing: the
frozen transport rule (record-unresolved-and-continue) turned 301
consecutive pre-dispatch failures into 301 retained reservations.
"""
import json
import os
import re
import socket
import sys
import urllib.error

sys.path.insert(0, "src")

from econ import corpus, ledger as ledger_mod
from econ import orchestrate, tokens, worker

FIXED_CLOCK = lambda: 1700000000.0  # noqa: E731
BASE = "/tmp/econ_infrahalt"


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


class OutageProvider(worker.Provider):
    """Succeeds until `fail_at`, then raises `exc` on every later call."""

    def __init__(self, fn, fail_at=None, exc=None):
        self.fn = fn
        self.fail_at = fail_at
        self.exc = exc
        self.requests = 0

    def post(self, body, headers, timeout):
        self.requests += 1
        if self.fail_at is not None and self.requests >= self.fail_at \
                and self.exc is not None:
            raise self.exc
        return self.fn(body, headers, self.requests)


def refused_exc():
    # Exactly what urllib raises when the egress connect() is refused.
    return urllib.error.URLError(
        ConnectionRefusedError(111, "Connection refused"))


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


pools = corpus.load_corpus("corpus/corpus.json")
by_id = {t.task_id: t.reference_code for t in pools["eval"]}
by_c = {t.task_id: t.reference_code for t in pools["calib"]}


def study_fn(body, headers, n):
    if "connectivity check" in body.get("instructions", ""):
        i, x = body["instructions"], body["input"]
        return 200, payload("OK",
                            in_tok=tokens.count(i) + tokens.count(x) + 10,
                            out_tok=5)
    m = re.search(r"TASK (\S+)", body.get("input", ""))
    tid = m.group(1) if m else ""
    code = by_id.get(tid) or by_c.get(tid) or "X=1"
    return 200, payload(f"```python\n{code}\n```", in_tok=800, out_tok=120)


def run_halted_study(tag, fail_at, exc):
    outdir = fresh(f"{BASE}_{tag}_out")
    os.makedirs(outdir, exist_ok=True)
    raw_dir = os.path.join(outdir, "raw")
    lg = ledger(f"{BASE}_{tag}_ledger.jsonl")
    prov = OutageProvider(study_fn, fail_at=fail_at, exc=exc)
    study = orchestrate.run_study(
        eval_tasks=pools["eval"], calib_tasks=pools["calib"],
        config_path="CONFIG.json", ledger=lg, provider=prov, outdir=outdir,
        raw_dir=raw_dir)
    return study, lg, prov, outdir, raw_dir


# 1. Egress refused during calibration: halt, no subsequent dispatches -----
s1, lg1, p1, od1, raw1 = run_halted_study("calib", fail_at=2,
                                         exc=refused_exc())
check("halt_status", s1.get("status") == "halted_infrastructure",
      s1.get("status"))
check("halt_reason", bool(s1.get("stop_reason")), str(s1.get("stop_reason")))
check("halt_no_subsequent_dispatches", p1.requests == 2,
      f"requests={p1.requests}")
check("halt_study_json",
      json.load(open(os.path.join(od1, "study.json")))["status"]
      == "halted_infrastructure", "study.json mismatch")
notes1 = [e for e in lg1.entries
          if e.get("kind") == "study_halted_infrastructure"]
check("halt_noted", len(notes1) == 1, f"{len(notes1)}")
kinds1 = [e.get("kind") for e in lg1.entries]
check("halt_failed_call_recorded_unresolved",
      "unresolved" in kinds1 and "settle" in kinds1, str(kinds1))
raw_files1 = os.listdir(raw1)
check("halt_received_response_preserved", len(raw_files1) == 1,
      f"raw files={raw_files1}")

# 2. Outage mid-rep: everything received so far is preserved ---------------
s2, lg2, p2, od2, raw2 = run_halted_study("midrep", fail_at=11,
                                         exc=refused_exc())
check("midrep_halt_status", s2.get("status") == "halted_infrastructure",
      s2.get("status"))
check("midrep_no_subsequent_dispatches", p2.requests == 11,
      f"requests={p2.requests}")
settles2 = [e for e in lg2.entries if e.get("kind") == "settle"]
unres2 = [e for e in lg2.entries if e.get("kind") == "unresolved"]
check("midrep_ledger_shape",
      len(settles2) == 10 and len(unres2) == 1,
      f"settles={len(settles2)} unresolved={len(unres2)}")
check("midrep_raw_preserved", len(os.listdir(raw2)) == 10,
      f"raw files={len(os.listdir(raw2))}")

# 3. Credential-service failure halts the same way --------------------------
s3, lg3, p3, od3, raw3 = run_halted_study(
    "credsvc", fail_at=3,
    exc=worker.CredentialServiceError("authd down"))
check("credsvc_halt_status", s3.get("status") == "halted_infrastructure",
      s3.get("status"))
check("credsvc_no_subsequent_dispatches", p3.requests == 3,
      f"requests={p3.requests}")

# 4. Non-infra failures do NOT halt: timeout continues ----------------------
lg4 = ledger(f"{BASE}_timeout_ledger.jsonl")


class FlakyTimeout(worker.Provider):
    def __init__(self):
        self.requests = 0

    def post(self, body, headers, timeout):
        self.requests += 1
        if self.requests == 1:
            raise socket.timeout("scripted timeout")
        return 200, payload("```python\nX=1\n```", in_tok=100, out_tok=50)


ft = FlakyTimeout()
r1 = worker.invoke(**invoke_kwargs(ledger=lg4, provider=ft,
                                  invocation_id="to1"))
r2 = worker.invoke(**invoke_kwargs(ledger=lg4, provider=ft,
                                  invocation_id="to2"))
check("timeout_no_halt",
      r1.status == "unresolved" and r2.status == "ok"
      and ft.requests == 2,
      f"r1={r1.status} r2={r2.status} reqs={ft.requests}")

# 5. Non-infra failures do NOT halt: HTTP 500 continues ---------------------
lg5 = ledger(f"{BASE}_http500_ledger.jsonl")


class Once500(worker.Provider):
    def __init__(self):
        self.requests = 0

    def post(self, body, headers, timeout):
        self.requests += 1
        if self.requests == 1:
            return 500, {"error": "boom"}
        return 200, payload("```python\nX=1\n```", in_tok=100, out_tok=50)


o5 = Once500()
h1 = worker.invoke(**invoke_kwargs(ledger=lg5, provider=o5,
                                  invocation_id="h1"))
h2 = worker.invoke(**invoke_kwargs(ledger=lg5, provider=o5,
                                  invocation_id="h2"))
check("http500_no_halt",
      h1.status == "unresolved" and h2.status == "ok"
      and o5.requests == 2,
      f"h1={h1.status} h2={h2.status} reqs={o5.requests}")

n_fail = sum(1 for _, ok, _ in results if not ok)
print(f"\n{len(results) - n_fail}/{len(results)} infra-halt fixtures pass")
sys.exit(1 if n_fail else 0)
