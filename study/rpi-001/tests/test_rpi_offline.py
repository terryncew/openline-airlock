"""RPI-001 offline qualification: every frozen-fixture code path exercised
against the exact frozen corpus representation, zero provider contact.

Covers: corpus integrity + disjointness, allocation, schedule, call
inventory/budget, envelope gating, ledger accounting, receiver gate,
delta machinery, proposal extraction, interruption rules, stop-file,
and a full simulated study run (scripted provider) through acquire ->
promote -> operate -> accounting split -> terminal decision.
"""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(STUDY), "econ-001", "src"))
sys.path.insert(0, os.path.join(STUDY, "scripts"))

from econ import corpus as corpus_mod  # noqa: E402
from econ import evaluate, extract, ledger as ledger_mod  # noqa: E402
from econ import prompts, worker  # noqa: E402
from econ.corpus import TARGET_FILENAME  # noqa: E402
import rpi_run as R  # noqa: E402


@pytest.fixture(scope="module")
def frozen():
    return R.load_frozen()


@pytest.fixture(scope="module")
def corpus_tasks(frozen):
    return frozen[0]


# ---------- corpus gates ----------

def test_corpus_integrity_all_tasks(corpus_tasks):
    # every frozen task: reference PASSES, buggy target FAILS (local exec)
    bad = []
    for tid, t in sorted(corpus_tasks.items()):
        v_ref, _ = evaluate.evaluate(TARGET_FILENAME, t.reference_code,
                                     t.support_files, t.hidden_tests)
        v_bug, _ = evaluate.evaluate(TARGET_FILENAME, t.target_code,
                                     t.support_files, t.hidden_tests)
        if not (v_ref == 1 and v_bug == 0):
            bad.append(tid)
    assert not bad, f"integrity failures: {bad}"
    assert len(corpus_tasks) == 100


def test_corpus_disjoint_from_prior(corpus_tasks):
    prior = set()
    for rel in ["study/econ-001/corpus/corpus.json",
                "study/econ-001/corpus/corpus_r2.json",
                "study/econ-001/corpus/corpus_r3.json",
                "study/econ-002/corpus/corpus.json"]:
        p = os.path.join(os.path.dirname(STUDY), "..", "..", rel)
        # resolve via git toplevel instead of relative guessing
        import subprocess
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True,
                              cwd=HERE).stdout.strip()
        data = json.load(open(os.path.join(root, rel)))
        for pool, tasks in data.items():
            if isinstance(tasks, list):
                for t in tasks:
                    if t.get("target_code"):
                        prior.add(t["target_code"])
    overlap = [tid for tid, t in corpus_tasks.items()
               if t.target_code in prior]
    assert not overlap, f"prior-corpus duplicates: {overlap}"


def test_corpus_ids_deterministic(corpus_tasks):
    assert sorted(corpus_tasks) == [f"rpi-eva-{i:04d}" for i in range(100)]


# ---------- allocation + schedule ----------

def test_allocation_disjoint(frozen):
    _, alloc, _ = frozen
    groups = [alloc["phase1"]["round1"]["discovery"],
              alloc["phase1"]["round1"]["promotion"],
              alloc["phase1"]["round2"]["discovery"],
              alloc["phase1"]["round2"]["promotion"],
              alloc["phase2"]["round1"]["discovery"],
              alloc["phase2"]["round1"]["promotion"],
              alloc["operating"]]
    flat = [t for g in groups for t in g]
    assert len(flat) == len(set(flat)) == 81
    assert len(alloc["spares"]) == 19
    assert not (set(flat) & set(alloc["spares"]))


def test_schedule_permutations(frozen):
    _, alloc, sched = frozen
    assert set(sched) == set(alloc["operating"])
    for tid, order in sched.items():
        assert sorted(order) == ["A", "B", "C"], tid


def test_call_inventory_and_budget():
    n, worst = R.call_inventory_check()
    assert n == 192
    assert worst == pytest.approx(9.60)
    assert worst <= R.BUDGET_SCI


def test_no_paid_contact_by_default():
    R.offline_validate()
    assert "dynamic_credentials" not in sys.modules


# ---------- ledger + accounting ----------

def test_ledger_reserve_settle_unresolved(tmp_path):
    led = ledger_mod.Ledger(10.00, str(tmp_path / "l.jsonl"))
    r = led.reserve(0.05, "inv1", "solving")
    assert led.encumbered == pytest.approx(0.05)
    led.settle(r["reservation_id"], "inv1", 0.05, 0.0123, usage={"a": 1}, status="ok")
    assert led.settled_total == pytest.approx(0.0123)
    assert led.encumbered == pytest.approx(0.0123)
    r2 = led.reserve(0.05, "inv2", "solving")
    led.unresolved(r2["reservation_id"], "inv2", 0.05, reason="x")
    assert led.unresolved_total == pytest.approx(0.05)
    assert led.encumbered == pytest.approx(0.0623)


def test_phase_spend_split(tmp_path):
    led = ledger_mod.Ledger(10.00, str(tmp_path / "l.jsonl"))
    # D1: one settled, one unresolved
    r = led.reserve(0.05, "rpi001_616e139a_P1r1d0", "solving")
    led.settle(r["reservation_id"], "rpi001_616e139a_P1r1d0", 0.05, 0.01,
               usage={"a": 1}, status="ok")
    r = led.reserve(0.05, "rpi001_616e139a_P1r1d1", "solving")
    led.unresolved(r["reservation_id"], "rpi001_616e139a_P1r1d1", 0.05,
                   reason="t")
    r = led.reserve(0.05, "rpi001_616e139a_P2r1d0", "solving")
    led.settle(r["reservation_id"], "rpi001_616e139a_P2r1d0", 0.05, 0.02,
               usage={"a": 1}, status="ok")

    class CX:
        ledger = led
    d1, iids1 = R.phase_spend(CX(), ["rpi001_616e139a_P1r1",
                                     "rpi001_616e139a_P1r2"])
    d2, iids2 = R.phase_spend(CX(), ["rpi001_616e139a_P2r1"])
    assert d1 == pytest.approx(0.06)   # 0.01 settled + 0.05 retained
    assert d2 == pytest.approx(0.02)
    assert len(iids1) == 2 and len(iids2) == 1


def test_retire_open_reserves_never_resent(tmp_path):
    led = ledger_mod.Ledger(10.00, str(tmp_path / "l.jsonl"))
    led.reserve(0.05, "inv_ambiguous", "solving")

    class CX:
        ledger = led
    n = R.retire_open_reserves(CX())
    assert n == 1
    assert led.unresolved_total == pytest.approx(0.05)
    assert led.open_reserves() == []
    # second call finds nothing: no resend, no double-count
    assert R.retire_open_reserves(CX()) == 0
    assert led.unresolved_total == pytest.approx(0.05)


# ---------- receiver gate ----------

def _att(verdict, cost, status="ok", iid="x"):
    return {"invocation_id": iid, "status": status, "verdict": verdict,
            "actual_usd": cost, "reservation_usd": 0.05}


def test_receiver_gate_accept():
    p = [_att(1, 0.010, iid=f"p{i}") for i in range(12)]
    c = [_att(1, 0.009, iid=f"c{i}") for i in range(12)]
    ok, rec = R.receiver_gate(p, c)
    assert ok and rec["ratio"] == pytest.approx(0.9)


def test_receiver_gate_reject_regression():
    p = [_att(1, 0.010, iid=f"p{i}") for i in range(12)]
    c = [_att(1, 0.009, iid=f"c{i}") for i in range(12)]
    c[3] = _att(0, 0.009, iid="c3")
    ok, rec = R.receiver_gate(p, c)
    assert not ok and rec["regressions"] == 1


def test_receiver_gate_reject_cost():
    p = [_att(1, 0.010, iid=f"p{i}") for i in range(12)]
    c = [_att(1, 0.011, iid=f"c{i}") for i in range(12)]
    ok, rec = R.receiver_gate(p, c)
    assert not ok and rec["ratio"] > 1.0


def test_receiver_gate_void_on_nonok():
    p = [_att(1, 0.010, iid=f"p{i}") for i in range(12)]
    c = [_att(1, 0.009, iid=f"c{i}") for i in range(12)]
    c[5] = _att(0, 0.05, status="unresolved", iid="c5")
    ok, rec = R.receiver_gate(p, c)
    assert not ok and rec.get("void") is True


# ---------- delta machinery ----------

def test_delta_numbering_visible_step():
    # block 6 = CHECK step (block 1 = preamble)
    d = "REPLACE_STEP 6: CHECK. Rewritten check step."
    out = prompts.apply_delta(prompts.BASE_METHOD, d)
    assert "CHECK. Rewritten check step." in out
    assert "Walk the visible tests" not in out
    # block listing mirrors apply_delta's split, including on rendered M1
    listed = R._block_listed_method(prompts.BASE_METHOD)
    assert listed.split("[6]\n")[1].startswith("5. CHECK")
    listed2 = R._block_listed_method(out)
    assert listed2.split("[6]\n")[1].startswith("6. CHECK. Rewritten")


def test_delta_cap_rejects_not_crashes():
    big = "ADD_STEP: " + "x " * 2000
    with pytest.raises(Exception):
        prompts.apply_delta(prompts.BASE_METHOD, big)


def test_extract_delta_contract():
    good = "```delta\nREPLACE_STEP 7: CHECK. New.\n```"
    assert extract.extract_delta(good) == "REPLACE_STEP 7: CHECK. New."
    assert extract.extract_delta("no fence here") is None
    assert extract.extract_delta("```delta\na\n```\n```delta\nb\n```") is None


# ---------- scripted provider ----------

class ScriptedProvider(worker.Provider):
    def __init__(self, handler):
        self.handler = handler
        self.posts = 0

    def post(self, body, headers, timeout):
        self.posts += 1
        return self.handler(body, headers)


def _resp(text, itok=800, otok=200):
    return (200, {"id": "resp_test", "object": "response",
                  "output": [{"type": "message", "content":
                              [{"type": "output_text", "text": text}]}],
                  "usage": {"input_tokens": itok, "output_tokens": otok}})


def _solving_handler(tasks, proposal_texts=None):
    # proposal_texts: one delta per proposal call, in order
    queue = list(proposal_texts or [])

    def h(body, headers):
        if "ECONOMIC OBJECTIVE" in body.get("instructions", ""):
            assert queue, "unexpected extra proposal call"
            return _resp(queue.pop(0), itok=2000, otok=100)
        m = re.search(r"TASK (rpi-eva-\d+)", body.get("input", ""))
        assert m, "solving call without task id"
        t = tasks[m.group(1)]
        return _resp(f"```python\n{t.reference_code}\n```")
    return h


def _make_cx(tmp_path, tasks, handler):
    run_dir = str(tmp_path / "run")
    os.makedirs(os.path.join(run_dir, "raw"), exist_ok=True)
    cx = R.Ctx.__new__(R.Ctx)
    cx.run_dir = run_dir
    cx.raw = os.path.join(run_dir, "raw")
    cx.stop = os.path.join(run_dir, "STOP")
    cx.provider = ScriptedProvider(handler)
    cx.ledger = ledger_mod.Ledger(R.BUDGET_SCI,
                                  os.path.join(run_dir, "ledger.jsonl"))
    cx.tasks, cx.alloc, cx.sched = tasks, json.load(
        open(os.path.join(STUDY, "TASK_ALLOCATION.json"))), json.load(
        open(os.path.join(STUDY, "SCHEDULE.json")))["schedule"]
    return cx


DELTA = "REPLACE_STEP 6: CHECK. Walk the visible tests against your fixed " \
        "file by hand, then re-read the changed lines once for syntax."


def test_simulated_full_run_accept(tmp_path, corpus_tasks):
    delta2 = ("REPLACE_STEP 2: READ. Read the task statement and the target "
                "file once, noting the exact failing behavior. Do not invent "
                "requirements beyond the statement.")
    handler = _solving_handler(corpus_tasks,
                               proposal_texts=[f"```delta\n{DELTA}\n```",
                                               f"```delta\n{delta2}\n```"])
    cx = _make_cx(tmp_path, corpus_tasks, handler)
    log = R.run_study(cx)
    assert log["m1_accepted"] is True
    assert log["m2_accepted"] is True
    assert log["operating_paired_n"] == 36
    assert log["operating_dropped_tasks"] == []
    assert cx.provider.posts == 28 + 28 + 108  # P1(1rd) + P2 + operating
    econ = log["arm_economics"]
    assert all(econ[a]["work"] == 36 for a in "ABC")
    split = log["accounting_split"]
    # D1 == D2: one accepted round each; C bears D2 alone, D1 split equally
    assert split["D1_phase1_scientific_usd"] == pytest.approx(
        split["D2_phase2_scientific_usd"])
    assert split["arm_B_bears_D1_over_2"] == pytest.approx(
        split["D1_phase1_scientific_usd"] / 2)
    assert split["allin_spend_usd"]["B"] == pytest.approx(
        split["D1_phase1_scientific_usd"] / 2 + econ["B"]["spend_usd"])
    assert split["allin_spend_usd"]["C"] == pytest.approx(
        split["D1_phase1_scientific_usd"] / 2
        + split["D2_phase2_scientific_usd"] + econ["C"]["spend_usd"])
    # identical scripted costs -> ratio 1.0 < 1.05 -> did not produce more
    assert log["terminal"]["B_produced_more_allin"] is False
    assert log["terminal"]["C_produced_more_allin"] is False
    assert log["ledger"]["unresolved_usd"] == 0
    assert log["ledger"]["encumbered_usd"] == pytest.approx(
        log["ledger"]["settled_usd"])
    # methods differ across lineages; B frozen == phase-1 rendered
    assert log["methods"]["A"] != log["methods"]["B"]
    assert log["methods"]["B"] != log["methods"]["C"]


def test_simulated_run_malformed_delta_rejected(tmp_path, corpus_tasks):
    handler = _solving_handler(corpus_tasks,
                               proposal_texts=["here is some prose, no fence",
                                               "still no fence"])
    cx = _make_cx(tmp_path, corpus_tasks, handler)
    log = R.run_study(cx)
    # both phase-1 rounds rejected (malformed), phase-2 rejected too
    assert log["m1_accepted"] is False
    assert log["m2_accepted"] is False
    assert all(r["reason"] == "delta_extraction_failed"
               for r in log["phase1_rounds"])
    # B and C fall back to M0; operating still completes
    assert log["methods"]["A"] == log["methods"]["B"] == log["methods"]["C"]
    assert log["operating_paired_n"] == 36
    split = log["accounting_split"]
    assert split["allin_spend_usd"]["B"] == pytest.approx(
        split["D1_phase1_scientific_usd"] / 2
        + log["arm_economics"]["B"]["spend_usd"])


def test_stop_file_halts_before_contact(tmp_path, corpus_tasks):
    handler = _solving_handler(corpus_tasks)
    cx = _make_cx(tmp_path, corpus_tasks, handler)
    open(cx.stop, "w").write("stop")
    with pytest.raises(worker.OperatorStop):
        R.run_solving(cx, "rpi-eva-0045", prompts.BASE_METHOD, "stop_test")
    assert cx.provider.posts == 0
    assert cx.ledger.encumbered == 0


def test_one_call_per_invocation(tmp_path, corpus_tasks):
    handler = _solving_handler(corpus_tasks)
    cx = _make_cx(tmp_path, corpus_tasks, handler)
    a = R.run_solving(cx, "rpi-eva-0045", prompts.BASE_METHOD, "one_call")
    assert a["status"] == "ok" and a["verdict"] == 1
    assert cx.provider.posts == 1
