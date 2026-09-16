"""PAYBACK-002 offline tests. Zero provider contact.

Covers the 18 required checks:
  1. live path constructs RealProvider (make_live_provider); the abstract
     base Provider cannot satisfy the live contract.
  2. clean preflight (usage + settled) -> gate passes; scientific may proceed.
  3. missing-usage preflight -> INCOMPLETE_PREFLIGHT, zero scientific calls.
  4. timeout preflight -> INCOMPLETE_PREFLIGHT, zero scientific calls.
  5. HTTP/non-ok preflight -> INCOMPLETE_PREFLIGHT, zero scientific calls.
  6. credential/pre-dispatch failure -> INCOMPLETE_PREFLIGHT, zero scientific.
  7. unresolved preflight -> INCOMPLETE_PREFLIGHT, zero scientific calls.
  8. provider exception -> INCOMPLETE_PREFLIGHT, zero scientific calls.
  9. exactly one provider post occurs in preflight.
 10. no retries exist (one-shot; second post would raise).
 11. preflight reservation is excluded from acquisition debt D.
 12. PAYBACK-001 corpus/schedules/null artifacts remain byte-identical.
 13. 928 scientific-call inventory unchanged.
 14. H == 450.
 15. NULL_MARGIN_99 == 0.26926.
 16. K_MAX == 1.
 17. $18.00 ceiling unchanged.
 18. all PAYBACK terminal-state/accounting tests still pass.
"""
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile

SYS = "/home/hatch/workspace/openline-airlock/study/econ-001/src"
PB2 = "/home/hatch/workspace/openline-airlock/study/payback-002"
PB1 = "/home/hatch/workspace/openline-airlock/study/payback-001"
sys.path.insert(0, SYS)
sys.path.insert(0, PB2)
sys.path.insert(0, PB2 + "/scripts")

from econ import ledger as ledger_mod  # noqa: E402
from econ import orchestrate  # noqa: E402
from econ import worker  # noqa: E402
import frozen as F  # noqa: E402 (payback-002)
import payback_acct  # noqa: E402
import payback_run  # noqa: E402

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


def fresh_tmp():
    tmp = tempfile.mkdtemp(prefix="pb2_gate_test")
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


def scientific_touched(ledger_path):
    """Any scientific reservation/settle/unresolved in the ledger?"""
    # Boundary-aware: "pb2-pre-00" must NOT match proposal prefix "pb2-p".
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
    tmp = fresh_tmp()
    cx = make_cx(tmp, provider)
    out = payback_run.run_preflight_gate(cx, tmp + "/ledger.jsonl")
    return tmp, out


def main():
    # ---- 1. live provider is RealProvider; base cannot satisfy contract ----
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

    # ---- 2. clean preflight passes; scientific may proceed ----
    fake = worker.FakeProvider([("ok", OK_PAYLOAD)])
    tmp, out = gate_outcome(fake)
    check("clean preflight passes gate", out is None, out)
    check("exactly one provider post in preflight", fake.requests == 1,
          fake.requests)
    kinds = set()
    for line in open(tmp + "/ledger.jsonl"):
        e = json.loads(line)
        if e.get("invocation_id") == "pb2-pre-00":
            kinds.add(e.get("kind"))
    check("preflight reservation settled", "settle" in kinds and
          "unresolved" not in kinds, kinds)
    raw_files = os.listdir(tmp + "/raw")
    check("preflight raw response persisted", len(raw_files) == 1, raw_files)

    # ---- 3..8. every dirty preflight state -> INCOMPLETE_PREFLIGHT ----
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

    # ---- 7 (explicit). unresolved preflight: reason names it ----
    tmp, out = gate_outcome(worker.FakeProvider([("no_usage", {"output": []})]))
    check("unresolved preflight reason recorded",
          out is not None and "unresolved" in out.get("reason", ""), out)

    # ---- 10. no retries: timeout double sees exactly one post ----
    fake = worker.FakeProvider([("timeout",)])
    tmp, out = gate_outcome(fake)
    check("no retries on preflight failure", fake.requests == 1, fake.requests)

    # ---- paid() refuses without --preflight (gate is mandatory) ----
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
        {"kind": "settle", "invocation_id": "pb2-pre-00", "actual": 0.000184,
         "reservation_id": "r0"},
        {"kind": "settle", "invocation_id": "pb2-d-00", "actual": 0.10,
         "reservation_id": "r1"},
        {"kind": "settle", "invocation_id": "pb2-p", "actual": 0.05,
         "reservation_id": "r2"},
        {"kind": "unresolved", "invocation_id": "pb2-d-01", "retained": 0.11,
         "reservation_id": "r3"},
    ]
    p = tmp + "/ledger.jsonl"
    open(p, "w").write("\n".join(json.dumps(e) for e in lines) + "\n")
    r = payback_acct.compute(p)
    check("preflight excluded from D",
          abs(r["D"] - (0.10 + 0.05 + 0.11)) < 1e-9, r["D"])

    # ---- 12. PAYBACK-001 artifacts byte-identical ----
    def sha(path):
        return hashlib.sha256(open(path, "rb").read()).hexdigest()

    identical = True
    for sub in ("corpus", "null"):
        for f in sorted(os.listdir(f"{PB1}/{sub}")):
            a, b = sha(f"{PB1}/{sub}/{f}"), sha(f"{PB2}/{sub}/{f}")
            if a != b:
                identical = False
                print("MISMATCH", f, a[:12], b[:12])
    check("pb1 corpus/schedules/null byte-identical", identical)
    check("corpus SHA matches frozen",
          sha(f"{PB2}/corpus/corpus.json") == F.CORPUS_SHA256)
    check("arm-order SHA matches frozen",
          sha(f"{PB2}/corpus/ARM_ORDER.json") == F.ARM_ORDER_SHA256)

    # ---- 13-17. scientific constants unchanged ----
    inv = F.CALL_INVENTORY
    sci = inv["discovery"] + inv["proposal"] + inv["promotion"] + inv["operating"]
    check("928 scientific-call inventory", sci == 928, sci)
    check("H == 450", F.H == 450, F.H)
    check("NULL_MARGIN_99 == 0.26926", F.NULL_MARGIN_99 == 0.26926)
    check("K_MAX == 1", F.K_MAX == 1)
    check("$18.00 ceiling", F.BUDGET_TOTAL == 18.00)
    check("study identity is payback002",
          F.STUDY_ID == "payback002" and F.INV_PREFIX == "pb2")
    check("pb2 namespace fresh (no pb1 ids)",
          F.P_PRE == "pb2-pre" and F.P_OP_C == "pb2-o-C")

    # ---- 18. terminal-state/accounting tests still pass ----
    D, H = 0.37, 450
    m = json.load(open(PB2 + "/null/NULL_CALIBRATION.json"))["V1_primary"]

    def ledger(deltas, verdicts=None, halted=False):
        tmp = fresh_tmp()
        lines = []
        for j, name in enumerate(["pb2-d-00", "pb2-d-01", "pb2-d-02", "pb2-p"]):
            lines.append({"kind": "settle", "invocation_id": name,
                          "actual": D / 4, "reservation_id": f"r{j}"})
        rid = 4
        for i, d in enumerate(deltas):
            c = 0.013
            lines.append({"kind": "settle",
                          "invocation_id": f"pb2-o-C-{i:04d}",
                          "actual": c, "reservation_id": f"r{rid}"})
            rid += 1
            lines.append({"kind": "settle",
                          "invocation_id": f"pb2-o-T-{i:04d}",
                          "actual": c - d, "reservation_id": f"r{rid}"})
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
        {"kind": "settle", "invocation_id": "pb2-d-00", "actual": D,
         "reservation_id": "r0"}) + "\n")
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

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:", FAILURES)
        raise SystemExit(1)
    print("ALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    main()
