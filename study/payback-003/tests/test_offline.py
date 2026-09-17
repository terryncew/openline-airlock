"""PAYBACK-003 offline tests + apparatus-repair fault qualification.

Zero provider contact. Two parts:

PART A — frozen-contract checks (adapted from PAYBACK-002):
  1. live path constructs RealProvider; base cannot satisfy live contract.
  2. clean preflight (usage + settled) -> gate passes.
  3-8. every dirty preflight state -> INCOMPLETE_PREFLIGHT, zero scientific.
  9. exactly one provider post in preflight; 10. no retries.
  11. preflight excluded from acquisition debt D.
  12. fresh pb3 corpus: new SHA, 465 tasks, declared disjointness holds.
  13. 928 scientific-call inventory unchanged.
  14. H == 450; 15. NULL_MARGIN_99 == 0.26926 (null carried forward
      byte-identical); 16. K_MAX == 1; 17. $18.00 ceiling.
  18. INFRA_BREAKER_N == 3 frozen.
  19. study identity payback003 / fresh pb3-* namespace.
  20. all PAYBACK terminal-state/accounting tests still pass.

PART B — apparatus-repair fault qualification (earned by PAYBACK-002):
  B1. unresolved real-format ledger entry ("reservation" key) -> accounting
      produces correct settled + retained totals, no KeyError; "retained"
      key still accepted; frozen formulas unchanged.
  B2. transport circuit breaker: 3 consecutive transport failures trip;
      a success resets the streak; HTTP errors and credential failures do
      not count; trip is one-way; _attempt raises InfraCircuitBreaker once
      tripped; a breaker-halted run reads INCOMPLETE in accounting.
  B3. supervisor: runner death (nonzero exit, no RUN_STATUS.json) ->
      INFRA_TERMINAL.json classifies unexpected termination; missing
      RUN_STATUS.json on exit 0 -> unexpected; clean completion (exit 0
      with RUN_STATUS.json) -> expected, no infra record.
  B4. durable stdout/stderr capture from process start.
  B5. infra terminal record schema: infrastructure evidence only, no
      scientific observation invented, no scientific artifact rewritten.
  B6. idempotency: finalize twice -> byte-identical records; compute()
      twice on one ledger -> identical results (exact replay).
"""
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

SYS = "/home/hatch/workspace/openline-airlock/study/econ-001/src"
PB3 = "/home/hatch/workspace/openline-airlock/study/payback-003"
PB2 = "/home/hatch/workspace/openline-airlock/study/payback-002"
sys.path.insert(0, SYS)
sys.path.insert(0, PB3)
sys.path.insert(0, PB3 + "/scripts")

from econ import ledger as ledger_mod  # noqa: E402
from econ import orchestrate  # noqa: E402
from econ import worker  # noqa: E402
import frozen as F  # noqa: E402 (payback-003)
import payback_acct  # noqa: E402
import payback_run  # noqa: E402
import supervise  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name, detail if not cond else "")
    if not cond:
        FAILURES.append(name)


OK_PAYLOAD = {"id": "resp-test",
              "usage": {"input_tokens": 120, "output_tokens": 40},
              "output": []}


def make_cx(tmp, provider):
    led = ledger_mod.Ledger(F.BUDGET_TOTAL, tmp + "/ledger.jsonl")
    envs = orchestrate.load_envelopes(
        "/home/hatch/workspace/openline-airlock/study/econ-001/CONFIG.json")
    os.makedirs(tmp + "/raw", exist_ok=True)
    return {"ledger": led, "provider": provider, "envs": envs,
            "stop": tmp + "/STOP", "raw": tmp + "/raw", "run": tmp + "/run"}


def fresh_tmp(prefix="pb3_test"):
    tmp = tempfile.mkdtemp(prefix=prefix)
    os.makedirs(tmp + "/run", exist_ok=True)
    return tmp


class BoomProvider(worker.Provider):
    """Test double raising a chosen exception on post."""

    def __init__(self, exc):
        self.exc = exc
        self.requests = 0

    def post(self, body, headers, timeout):
        self.requests += 1
        raise self.exc


class ScriptedTransportProvider(worker.Provider):
    """Cycles a script of post() outcomes (no one-post limit).

    Script items: ("raise", exc) | ("ok", status, payload).
    """

    def __init__(self, script):
        self.script = list(script)
        self.requests = 0

    def post(self, body, headers, timeout):
        self.requests += 1
        kind = self.script[min(self.requests - 1, len(self.script) - 1)]
        if kind[0] == "raise":
            raise kind[1]
        _, status, payload = kind
        return status, payload


def scientific_touched(ledger_path):
    for line in open(ledger_path):
        e = json.loads(line)
        inv = e.get("invocation_id", "")
        if e.get("kind") not in ("reserve", "settle", "unresolved"):
            continue
        if inv == F.P_PROP:
            return True, inv
        if inv.startswith((F.P_DISC + "-", F.P_PROMO_P + "-",
                           F.P_PROMO_C + "-", F.P_OP_C + "-", F.P_OP_T + "-")):
            return True, inv
    return False, ""


def gate_outcome(provider):
    tmp = fresh_tmp("pb3_gate_test")
    cx = make_cx(tmp, provider)
    out = payback_run.run_preflight_gate(cx, tmp + "/ledger.jsonl")
    return tmp, out


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def content_hash(t):
    canon = json.dumps({k: t[k] for k in ("statement", "target_code",
                                         "hidden_tests")}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


# ============================ PART A ============================

def part_a():
    # ---- 1. live provider is RealProvider ----
    prov = payback_run.make_live_provider()
    check("live path constructs RealProvider",
          isinstance(prov, worker.RealProvider)
          and type(prov) is not worker.Provider)
    try:
        worker.Provider().post({}, {}, 1.0)
        base_raises = False
    except NotImplementedError:
        base_raises = True
    check("base Provider cannot satisfy live contract", base_raises)

    # ---- 2. clean preflight passes ----
    fake = worker.FakeProvider([("ok", OK_PAYLOAD)])
    tmp, out = gate_outcome(fake)
    check("clean preflight passes gate", out is None, out)
    check("exactly one provider post in preflight", fake.requests == 1,
          fake.requests)
    kinds = set()
    for line in open(tmp + "/ledger.jsonl"):
        e = json.loads(line)
        if e.get("invocation_id") == "pb3-pre-00":
            kinds.add(e.get("kind"))
    check("preflight reservation settled", "settle" in kinds and
          "unresolved" not in kinds, kinds)
    raw_files = os.listdir(tmp + "/raw")
    check("preflight raw response persisted", len(raw_files) == 1, raw_files)

    # ---- 3..8. dirty preflights -> INCOMPLETE_PREFLIGHT ----
    dirty = [
        ("missing-usage", worker.FakeProvider([("no_usage", {"output": []})])),
        ("timeout", worker.FakeProvider([("timeout",)])),
        ("http-error", worker.FakeProvider([("http_error", 500,
                                             {"error": "boom"})])),
        ("credential-failure",
         BoomProvider(worker.CredentialServiceError("scripted"))),
        ("provider-exception", BoomProvider(RuntimeError("boom"))),
    ]
    for name, provider in dirty:
        tmp, out = gate_outcome(provider)
        ok = isinstance(out, dict) and out.get("outcome") == "INCOMPLETE_PREFLIGHT"
        check(f"{name} preflight -> INCOMPLETE_PREFLIGHT", ok, out)
        touched, inv = scientific_touched(tmp + "/ledger.jsonl")
        check(f"{name} preflight: zero scientific calls", not touched, inv)
        status = json.load(open(tmp + "/run/RUN_STATUS.json"))
        check(f"{name} preflight: run status recorded",
              status.get("status") == "incomplete_preflight", status)

    tmp, out = gate_outcome(worker.FakeProvider([("no_usage", {"output": []})]))
    check("unresolved preflight reason recorded",
          out is not None and "unresolved" in out.get("reason", ""), out)

    fake = worker.FakeProvider([("timeout",)])
    tmp, out = gate_outcome(fake)
    check("no retries on preflight failure", fake.requests == 1, fake.requests)

    # ---- paid() refuses without --preflight ----
    tmp = fresh_tmp()
    real_runs = payback_run.RUNS
    payback_run.RUNS = tmp + "/runs"
    try:
        import argparse
        args = argparse.Namespace(offline=False,
                                  authorize_paid_contact=True, preflight=False)
        try:
            payback_run.paid(args)
            refused = False
        except SystemExit as e:
            refused = "preflight" in str(e)
        check("paid() refuses without --preflight", refused)
    finally:
        payback_run.RUNS = real_runs
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 11. preflight excluded from D ----
    tmp = fresh_tmp()
    lines = [
        {"kind": "settle", "invocation_id": "pb3-pre-00", "actual": 0.000408,
         "reservation_id": "r0", "reservation": 0.11, "usage": {}, "status": "ok"},
        {"kind": "settle", "invocation_id": "pb3-d-00", "actual": 0.10,
         "reservation_id": "r1", "reservation": 0.11, "usage": {}, "status": "ok"},
        {"kind": "settle", "invocation_id": "pb3-p", "actual": 0.05,
         "reservation_id": "r2", "reservation": 0.11, "usage": {}, "status": "ok"},
        {"kind": "unresolved", "invocation_id": "pb3-d-01",
         "reservation": 0.11, "reservation_id": "r3",
         "reason": "timeout_no_usage: scripted"},
    ]
    p = tmp + "/ledger.jsonl"
    open(p, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
    r = payback_acct.compute(p)
    check("preflight excluded from D",
          abs(r["D"] - (0.10 + 0.05 + 0.11)) < 1e-9, r["D"])
    check("retained unresolved counted in D",
          abs(r["D_retained"] - 0.11) < 1e-9, r["D_retained"])

    # ---- 12. fresh corpus, declared disjointness ----
    check("corpus SHA matches frozen",
          sha(f"{PB3}/corpus/corpus.json") == F.CORPUS_SHA256)
    check("arm-order SHA matches frozen",
          sha(f"{PB3}/corpus/ARM_ORDER.json") == F.ARM_ORDER_SHA256)
    check("corpus is fresh (differs from pb2)",
          sha(f"{PB3}/corpus/corpus.json") != sha(f"{PB2}/corpus/corpus.json"))
    data = json.load(open(f"{PB3}/corpus/corpus.json"))
    check("465 tasks", len(data["tasks"]) == 465, len(data["tasks"]))
    check("task ids use pb3 namespace",
          all(t["task_id"].startswith("pb3-") for t in data["tasks"]))
    check("all 465 content-distinct",
          len({content_hash(t) for t in data["tasks"]}) == 465)
    alloc = json.load(open(f"{PB3}/corpus/ALLOCATION.json"))
    order = json.load(open(f"{PB3}/corpus/OPERATING_ORDER.json"))
    arm = json.load(open(f"{PB3}/corpus/ARM_ORDER.json"))
    promo = json.load(open(f"{PB3}/corpus/PROMOTION_ORDER.json"))
    check("allocation 3/12/450",
          alloc["discovery"] == [0, 1, 2] and alloc["promotion"] == list(range(3, 15))
          and alloc["operating_pool"] == list(range(15, 465)))
    check("operating order is a permutation of 450",
          sorted(order["order"]) == list(range(450)))
    check("arm order 225/225 balanced",
          arm["balance"] == {"CT": 225, "TC": 225} and len(arm["order"]) == 450)
    check("promotion order 12", len(promo["order"]) == 12)
    # declared disjointness, re-verified here
    pb2 = json.load(open(f"{PB2}/corpus/corpus.json"))["tasks"]
    pb2_alloc = json.load(open(f"{PB2}/corpus/ALLOCATION.json"))
    pb2_order = json.load(open(f"{PB2}/corpus/OPERATING_ORDER.json"))["order"]
    pb2_hashes = [content_hash(t) for t in pb2]
    contacted = set(pb2_alloc["discovery"]) | set(pb2_alloc["promotion"])
    for pos in range(171):
        contacted.add(pb2_alloc["operating_pool"][pb2_order[pos]])
    contacted_hashes = {pb2_hashes[i] for i in contacted}
    hashes = [content_hash(t) for t in data["tasks"]]
    check("operating corpus disjoint from pb2-contacted",
          not (set(hashes[15:]) & contacted_hashes))
    prior = set()
    for pp in ("corpus.json", "corpus_r2.json", "corpus_r3.json"):
        d = json.load(open(f"/home/hatch/workspace/openline-airlock/study/econ-001/corpus/{pp}"))
        for pool in ("eval", "calib", "dev"):
            for t in d.get(pool, []):
                prior.add(content_hash(t))
    d = json.load(open("/home/hatch/workspace/openline-airlock/study/econ-002/corpus/corpus.json"))
    for pool in ("eval", "calib", "dev"):
        for t in d.get(pool, []):
            prior.add(content_hash(t))
    check("discovery+promotion disjoint from prior ECON and pb2-contacted",
          not (set(hashes[:15]) & (prior | contacted_hashes)))

    # ---- 13..19. scientific constants carried forward ----
    inv = F.CALL_INVENTORY
    sci = inv["discovery"] + inv["proposal"] + inv["promotion"] + inv["operating"]
    check("928 scientific-call inventory", sci == 928, sci)
    check("H == 450", F.H == 450, F.H)
    check("NULL_MARGIN_99 == 0.26926", F.NULL_MARGIN_99 == 0.26926)
    check("null calibration byte-identical to pb2",
          sha(f"{PB3}/null/NULL_CALIBRATION.json") ==
          sha(f"{PB2}/null/NULL_CALIBRATION.json"))
    check("K_MAX == 1", F.K_MAX == 1)
    check("$18.00 ceiling", F.BUDGET_TOTAL == 18.00)
    check("PROMO_COST_CAP == 1.5", F.PROMO_COST_CAP == 1.5)
    check("INFRA_BREAKER_N == 3 frozen", F.INFRA_BREAKER_N == 3)
    check("study identity is payback003",
          F.STUDY_ID == "payback003" and F.INV_PREFIX == "pb3")
    check("pb3 namespace fresh",
          F.P_PRE == "pb3-pre" and F.P_OP_C == "pb3-o-C"
          and F.P_OP_T == "pb3-o-T")

    # ---- 20. terminal-state/accounting tests ----
    D, H = 0.37, 450
    m = json.load(open(PB3 + "/null/NULL_CALIBRATION.json"))["V1_primary"]

    def ledger(deltas, verdicts=None, halted=False):
        tmp = fresh_tmp()
        lines = []
        for j, name in enumerate(["pb3-d-00", "pb3-d-01", "pb3-d-02", "pb3-p"]):
            lines.append({"kind": "settle", "invocation_id": name,
                          "actual": D / 4, "reservation_id": f"r{j}",
                          "reservation": 0.11, "usage": {}, "status": "ok"})
        rid = 4
        for i, d in enumerate(deltas):
            c = 0.013
            lines.append({"kind": "settle",
                          "invocation_id": f"pb3-o-C-{i:04d}",
                          "actual": c, "reservation_id": f"r{rid}",
                          "reservation": 0.11, "usage": {}, "status": "ok"})
            rid += 1
            lines.append({"kind": "settle",
                          "invocation_id": f"pb3-o-T-{i:04d}",
                          "actual": c - d, "reservation_id": f"r{rid}",
                          "reservation": 0.11, "usage": {}, "status": "ok"})
            rid += 1
        rd = tmp + "/run"
        os.makedirs(rd, exist_ok=True)
        lp = rd + "/ledger.jsonl"
        open(lp, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
        tp = None
        if verdicts:
            tp = rd + "/TASKS.jsonl"
            open(tp, "w").write("\n".join(
                json.dumps({"i": i, "control": {"verdict": vc, "cost": 0.013},
                            "treatment": {"verdict": vt, "cost": 0.012}})
                for i, (vc, vt) in enumerate(verdicts)) + "\n")
        json.dump({"status": "halted" if halted else "completed"},
                  open(rd + "/RUN_STATUS.json", "w"))
        return lp, tp, rd

    p, _, rd = ledger([0.002] * H)
    r = payback_acct.compute(p, None, rd)
    check("strong positive detected", r["verdict"] == "STRONG_POSITIVE")
    check("A(0) = -D", abs(r["curve"][0] - (0.002 - D)) < 1e-9)

    p, _, rd = ledger([0.0001] * H)
    r = payback_acct.compute(p, None, rd)
    check("no payback detected", r["verdict"] == "NO_PAYBACK")

    per = (D + m["p99"] / 2) / H
    p, _, rd = ledger([per] * H)
    r = payback_acct.compute(p, None, rd)
    check("nominal-not-beyond-null detected",
          r["verdict"] == "NOMINAL_NOT_BEYOND_NULL")

    p, tp, rd = ledger([0.002] * H, verdicts=[(1, 1)] * H)
    lines = open(tp).read().strip().split("\n")
    bad = json.loads(lines[10])
    bad["treatment"]["verdict"] = 0
    lines[10] = json.dumps(bad)
    open(tp, "w").write("\n".join(lines) + "\n")
    r = payback_acct.compute(p, tp, rd)
    check("quality regression voids",
          r["verdict"] == "VOID_QUALITY_REGRESSION")

    p, _, rd = ledger([0.002] * 100, halted=True)
    r = payback_acct.compute(p, None, rd)
    check("incomplete detected", r["verdict"] == "INCOMPLETE")

    rd2 = fresh_tmp() + "/run"
    os.makedirs(rd2, exist_ok=True)
    p2 = rd2 + "/ledger.jsonl"
    open(p2, "w").write(json.dumps(
        {"kind": "settle", "invocation_id": "pb3-d-00", "actual": D,
         "reservation_id": "r0", "reservation": 0.11,
         "usage": {}, "status": "ok"}) + "\n")
    json.dump({"status": "incomplete_preflight",
               "reason": "t", "phase": "preflight"},
              open(rd2 + "/RUN_STATUS.json", "w"))
    r = payback_acct.compute(p2, None, rd2)
    check("INCOMPLETE_PREFLIGHT recognized by accounting",
          r["verdict"] == "INCOMPLETE_PREFLIGHT", r["verdict"])

    p, _, rd = ledger([0.002] * H)
    r = payback_acct.compute(p, None, rd)
    check("breakeven found",
          r["breakeven_t"] is not None and r["breakeven_t"] <= H)


# ============================ PART B ============================

def part_b1_accounting_schema():
    """B1: real-format unresolved entries read correctly; no KeyError."""
    tmp = fresh_tmp("pb3_acct")
    p = tmp + "/ledger.jsonl"
    # Real worker.unresolved() format: key is "reservation", not "retained".
    lines = [
        {"kind": "settle", "invocation_id": "pb3-d-00", "actual": 0.20,
         "reservation_id": "rsv_a", "reservation": 0.11,
         "usage": {"input_tokens": 10, "output_tokens": 5}, "status": "ok"},
        {"kind": "unresolved", "invocation_id": "pb3-d-01",
         "reservation_id": "rsv_b", "reservation": 0.11,
         "reason": "transport_no_usage: Remote end closed connection without response"},
        {"kind": "unresolved", "invocation_id": "pb3-d-02",
         "reservation_id": "rsv_c", "reservation": 0.11,
         "reason": "timeout_no_usage: scripted"},
    ]
    open(p, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
    try:
        r = payback_acct.compute(p)
        no_keyerror = True
    except KeyError as e:
        no_keyerror = False
        r = {}
    check("real-format unresolved entry: no KeyError", no_keyerror)
    check("settled total correct",
          abs(r.get("D_settled", -1) - 0.20) < 1e-9, r.get("D_settled"))
    check("retained total correct (2 x 0.11)",
          abs(r.get("D_retained", -1) - 0.22) < 1e-9, r.get("D_retained"))
    check("D = settled + retained",
          abs(r.get("D", -1) - 0.42) < 1e-9, r.get("D"))
    # Legacy "retained" key still accepted (defensive).
    lines.append({"kind": "unresolved", "invocation_id": "pb3-p",
                  "reservation_id": "rsv_d", "retained": 0.11,
                  "reason": "legacy"})
    open(p, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
    r = payback_acct.compute(p)
    check("legacy 'retained' key still accepted",
          abs(r.get("D_retained", -1) - 0.33) < 1e-9, r.get("D_retained"))
    # Exact replay: compute twice -> identical.
    r2 = payback_acct.compute(p)
    check("compute() deterministic (exact replay)",
          json.dumps(r, sort_keys=True) == json.dumps(r2, sort_keys=True))


def part_b2_breaker():
    """B2: transport circuit breaker trips deterministically."""
    # 3 consecutive transport failures -> tripped.
    inner = ScriptedTransportProvider(
        [("raise", socket.timeout("t1")),
         ("raise", socket.timeout("t2")),
         ("raise", ConnectionRefusedError(111, "refused")),
         ("ok", 200, OK_PAYLOAD)])
    br = payback_run.TransportBreaker(inner, F.INFRA_BREAKER_N)
    for _ in range(3):
        try:
            br.post({}, {}, 1.0)
        except OSError:
            pass
    check("breaker trips after 3 consecutive transport failures",
          br.tripped and br.streak == 3, (br.tripped, br.streak))
    check("trip is one-way (success does not un-trip)",
          br.post({}, {}, 1.0) == (200, OK_PAYLOAD) and br.tripped)
    check("streak resets on success", br.streak == 0, br.streak)

    # 2 failures then a success -> not tripped.
    inner = ScriptedTransportProvider(
        [("raise", socket.timeout("t1")),
         ("raise", socket.timeout("t2")),
         ("ok", 200, OK_PAYLOAD)])
    br = payback_run.TransportBreaker(inner, 3)
    for _ in range(2):
        try:
            br.post({}, {}, 1.0)
        except OSError:
            pass
    br.post({}, {}, 1.0)
    check("2 failures then success: not tripped",
          not br.tripped and br.streak == 0)

    # http.client.HTTPException subclasses count (remote-closed class).
    inner = ScriptedTransportProvider(
        [("raise", http.client.RemoteDisconnected("closed"))] * 3)
    br = payback_run.TransportBreaker(inner, 3)
    for _ in range(3):
        try:
            br.post({}, {}, 1.0)
        except http.client.HTTPException:
            pass
    check("RemoteDisconnected counts as transport failure", br.tripped)

    # HTTP error statuses do NOT count (provider responded).
    inner = ScriptedTransportProvider([("ok", 500, {"error": "x"})] * 5)
    br = payback_run.TransportBreaker(inner, 3)
    for _ in range(5):
        br.post({}, {}, 1.0)
    check("HTTP 500 does not count toward breaker",
          not br.tripped and br.streak == 0)

    # Credential failures propagate untouched and do not count.
    inner = ScriptedTransportProvider(
        [("raise", worker.CredentialServiceError("authd down"))])
    br = payback_run.TransportBreaker(inner, 3)
    try:
        br.post({}, {}, 1.0)
        cred_pass = False
    except worker.CredentialServiceError:
        cred_pass = True
    check("credential failure propagates untouched", cred_pass)
    check("credential failure not counted",
          not br.tripped and br.streak == 0, (br.tripped, br.streak))

    # Integration: _attempt raises InfraCircuitBreaker once tripped.
    tmp = fresh_tmp("pb3_breaker_int")
    inner = ScriptedTransportProvider(
        [("raise", socket.timeout("t"))] * 10)
    br = payback_run.TransportBreaker(inner, 3)
    cx = make_cx(tmp, br)
    cx["breaker"] = br
    # Drive three transport failures through worker.invoke via _attempt-like
    # path: use worker.invoke directly (attempt() needs a real task).
    for i in range(3):
        res = worker.invoke(instructions="x", input_text="x",
                            envelope=cx["envs"]["preflight"], ledger=cx["ledger"],
                            provider=br, invocation_id=f"pb3-t-{i}",
                            stop_file=cx["stop"], raw_dir=cx["raw"])
        assert res.status == "unresolved", res.status
    check("three transport failures recorded unresolved",
          br.tripped and br.streak == 3)
    # Unresolved reservations preserved (retained exposure, not zero-cost).
    kinds = [json.loads(line)["kind"] for line in open(tmp + "/ledger.jsonl")]
    check("failed calls retained as unresolved",
          kinds.count("unresolved") == 3, kinds)
    try:
        payback_run._attempt(None, "m", "pb3-t-99", cx)
        raised = False
    except payback_run.InfraCircuitBreaker as e:
        raised = "infrastructure-INCOMPLETE" in str(e)
    except Exception:
        raised = False
    check("_attempt raises InfraCircuitBreaker when tripped", raised)

    # Halt path: a breaker-halted RUN_STATUS reads INCOMPLETE in accounting.
    rd = fresh_tmp("pb3_halt") + "/run"
    os.makedirs(rd, exist_ok=True)
    lp = rd + "/ledger.jsonl"
    open(lp, "w").write(json.dumps(
        {"kind": "settle", "invocation_id": "pb3-d-00", "actual": 0.2,
         "reservation_id": "r0", "reservation": 0.11,
         "usage": {}, "status": "ok"}) + "\n")
    json.dump({"status": "halted",
               "reason": "transport circuit breaker tripped: 3 consecutive "
                         "transport failures; halting as infrastructure-INCOMPLETE",
               "phase": "operating"},
              open(rd + "/RUN_STATUS.json", "w"))
    r = payback_acct.compute(lp, None, rd)
    check("breaker-halted run -> INCOMPLETE (never rescued)",
          r["verdict"] == "INCOMPLETE" and r["halted"], r["verdict"])


def _child_py(code: str) -> list:
    return [sys.executable, "-c", code]


def part_b3_supervisor():
    """B3/B4/B5: supervision, capture, infra terminal record."""
    # --- runner death: nonzero exit, no RUN_STATUS.json ---
    rd = fresh_tmp("pb3_sup_death") + "/run"
    rec = supervise.supervise(
        rd,
        _child_py("import sys; print('out-line'); "
                  "print('err-line', file=sys.stderr); sys.exit(3)"),
        "payback003", heartbeat_s=1)
    check("death: termination classified unexpected",
          rec["classification"]["termination"] == "unexpected",
          rec["classification"])
    check("death: exit code persisted",
          rec.get("exit_code") == 3 and rec.get("signal") is None,
          (rec.get("exit_code"), rec.get("signal")))
    check("death: runner PID persisted",
          isinstance(rec.get("runner_pid"), int) and rec["runner_pid"] > 0)
    out = open(rd + "/console.out").read()
    err = open(rd + "/console.err").read()
    check("death: stdout durably captured", "out-line" in out, out[:80])
    check("death: stderr durably captured", "err-line" in err, err[:80])
    itp = rd + "/INFRA_TERMINAL.json"
    check("death: infra terminal record written", os.path.isfile(itp))
    infra = json.load(open(itp))
    check("infra record schema",
          infra.get("record") == "infrastructure_terminal"
          and infra["classification"]["termination"] == "unexpected"
          and infra.get("study_id") == "payback003", infra)
    check("infra record invents no scientific observation",
          set(infra.keys()) <= {"record", "study_id", "classification",
                                "exit", "runner_pid", "started_at",
                                "ended_at", "note"})
    check("supervisor did not fabricate RUN_STATUS.json",
          not os.path.isfile(rd + "/RUN_STATUS.json"))
    hb = json.load(open(rd + "/HEARTBEAT.json"))
    check("heartbeat durable", "child_alive" in hb and "t" in hb, hb)

    # --- missing terminal output on exit 0 ---
    rd = fresh_tmp("pb3_sup_missing") + "/run"
    rec = supervise.supervise(rd, _child_py("pass"), "payback003",
                              heartbeat_s=1)
    check("exit-0 without RUN_STATUS.json -> unexpected",
          rec["classification"]["termination"] == "unexpected",
          rec["classification"])
    check("missing-output infra record written",
          os.path.isfile(rd + "/INFRA_TERMINAL.json"))

    # --- clean completion: exit 0 WITH RUN_STATUS.json ---
    rd = fresh_tmp("pb3_sup_clean") + "/run"
    code = ("import json; json.dump({'status':'completed'}, "
            "open('RUN_STATUS.json','w'))")
    # run with cwd=rd so the child writes RUN_STATUS.json into the run dir
    proc_cwd = os.getcwd()
    os.makedirs(rd, exist_ok=True)
    os.chdir(rd)
    try:
        rec = supervise.supervise(rd, _child_py(code), "payback003",
                                  heartbeat_s=1)
    finally:
        os.chdir(proc_cwd)
    check("clean completion classified expected",
          rec["classification"]["termination"] == "expected",
          rec["classification"])
    check("clean completion: no infra record",
          not os.path.isfile(rd + "/INFRA_TERMINAL.json"))

    # --- signal death ---
    rd = fresh_tmp("pb3_sup_sig") + "/run"
    rec = supervise.supervise(
        rd,
        _child_py("import os, signal, time; "
                  "os.kill(os.getpid(), signal.SIGKILL); time.sleep(30)"),
        "payback003", heartbeat_s=1)
    check("SIGKILL: signal persisted",
          rec.get("signal") == 9 and rec.get("exit_code") is None,
          (rec.get("signal"), rec.get("exit_code")))
    check("SIGKILL -> unexpected",
          rec["classification"]["termination"] == "unexpected")

    # --- idempotent finalize ---
    rd = fresh_tmp("pb3_sup_idem") + "/run"
    os.makedirs(rd, exist_ok=True)
    record = {"study_id": "payback003", "runner_pid": 1234,
              "started_at": 1.0, "ended_at": 2.0,
              "exit_code": 3, "signal": None,
              "classification": {"termination": "unexpected",
                                 "detail": "t"}}
    a = supervise.finalize(rd, dict(record))
    sup_bytes_1 = open(rd + "/SUPERVISION.json", "rb").read()
    infra_bytes_1 = open(rd + "/INFRA_TERMINAL.json", "rb").read()
    b = supervise.finalize(rd, dict(record))
    check("finalize returns existing record on replay", a == b)
    check("second finalize leaves SUPERVISION.json byte-identical",
          open(rd + "/SUPERVISION.json", "rb").read() == sup_bytes_1)
    check("second finalize leaves INFRA_TERMINAL.json byte-identical",
          open(rd + "/INFRA_TERMINAL.json", "rb").read() == infra_bytes_1)


def main():
    print("=== PART A: frozen contract ===")
    part_a()
    print("=== PART B1: accounting schema repair ===")
    part_b1_accounting_schema()
    print("=== PART B2: transport circuit breaker ===")
    part_b2_breaker()
    print("=== PART B3/B4/B5: supervisor ===")
    part_b3_supervisor()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:", FAILURES)
        raise SystemExit(1)
    print("ALL OFFLINE TESTS PASSED (A + B)")


if __name__ == "__main__":
    main()
