"""RPI-001: fresh recursive-productivity A/B/C experiment.

Question: do successive inherited method improvements produce more
independently verified useful work per dollar?

Arms: A = baseline method M0 (unchanged). B = M0 + one accepted
improvement M1 (frozen). C = the identical frozen M1 + further
improvement search (M2 if phase-2 accepts, else M1).

Default mode is OFFLINE validation of the frozen apparatus (zero
provider contact). --preflight runs exactly one non-scientific paid
call (apparatus accounting). --authorize-paid-contact executes the
frozen scientific plan once. Nothing billable runs without a flag.

Frozen parameters:
  run id ............ rpi001_616e139a
  corpus ............ 100 tasks, eval_sha256 933cfadd...17bc06a3
  schedule .......... f1780b14...67c391bd (36 operating tasks)
  K1=2 (phase-1 proposal rounds), K2=1 (phase-2 rounds), H=36
  envelopes ......... solving/proposal/preflight $0.05 reservation
  budgets ........... $10.00 scientific, $10.00 apparatus (separate ledgers)

Accounting split (frozen, owner revision 2026-09-21):
  D1 = all phase-1 scientific costs (settled + retained unresolved),
       acquired once, split equally: B bears D1/2, C bears D1/2.
  D2 = all phase-2 scientific costs (settled + retained unresolved),
       borne by C alone.
  Arm A: operating spend only. Arm B: D1/2 + operating. Arm C: D1/2 + D2 + operating.
  Apparatus spend (preflight, qualification) is reported separately and
  never charged as arm performance.

Interruption (frozen): open ledger reserves on startup are retired as
unresolved exposure and NEVER resent. Interruption during a promotion
round voids that round (charged rejection). Interruption during phase-2
voids phase 2 (C inherits M1). An operating task with an unresolved arm
attempt is dropped from the paired comparison (all arms); if fewer than
30 paired tasks remain, the operating comparison is INCONCLUSIVE.
"""
import sys, os, json, hashlib, random

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(STUDY), "econ-001", "src"))
from econ import acquire, attempt as attempt_mod  # noqa: E402
from econ import corpus as corpus_mod, extract  # noqa: E402
from econ import ledger as ledger_mod, prompts, tokens, worker  # noqa: E402

SID = "rpi001_616e139a"
BUDGET_SCI, BUDGET_APP = 10.00, 10.00
K1, K2, H = 2, 1, 36
MIN_PAIRED = 30
ENVS = {
    "solving": {"name": "solving", "max_input_tokens": 4096,
                 "max_output_tokens": 4096, "reservation_usd": 0.05},
    "proposal": {"name": "proposal", "max_input_tokens": 8192,
                 "max_output_tokens": 1024, "reservation_usd": 0.05},
}
PRE_ENV = {"name": "preflight", "max_input_tokens": 512,
           "max_output_tokens": 16, "reservation_usd": 0.05}
CORPUS_SHA = "933cfadd086e1a561daee659f9460d647f42f700002b5b8d0c55dd0417bc06a3"
SCHED_SHA = "f1780b140a4ceb439afeeade64e376f2ca51d0964f295f0902e78fb367c391bd"

# --- Frozen proposal prompt: the proposer explicitly receives the economic
# --- objective; receiver acceptance rules and held-out tests are outside
# --- its control (it sees the rule, never the promotion tasks).
ECON_OBJECTIVE = (
    "ECONOMIC OBJECTIVE: Produce a method change whose goal is more "
    "independently verified useful work per dollar: equal-or-better verified "
    "success at lower measured execution cost. You may delete, merge, "
    "shorten, simplify, or remove method steps. Added procedure is a "
    "regression unless it improves verified output enough to justify its "
    "cost. Do not attempt to game the acceptance rule: the promotion tasks "
    "are held out and unseen, the tests are fixed, and only the receiver's "
    "frozen rule decides acceptance.")
ACCEPT_CRIT = (
    "FROZEN RECEIVER ACCEPTANCE (outside your control): on 12 fresh paired "
    "tasks the candidate must pass 12/12, the parent must pass 12/12, no "
    "task the parent passes may be failed by the candidate, and the "
    "candidate's total settled promotion cost must be at most 100% of the "
    "parent's (ratio <= 1.0). Any deviation -> rejection.")
NUM_GUIDE = (
    "Directive numbering: the CURRENT METHOD is shown with [k] block "
    "labels. Block [1] is the preamble; each numbered step after it is the "
    "next block in order. Use the [k] number in REPLACE_STEP/REMOVE_STEP. "
    "Example: to replace the CHECK step shown as [6], write "
    "REPLACE_STEP 6: <new step text>. The [k] labels are addressing aids "
    "only; never copy them into new step text.")
DELTA_FMT = (
    "Delta format inside one ```delta fenced block, one directive per line:\n"
    "  REPLACE_STEP <n>: <new step text>\n  ADD_STEP: <new step text>\n"
    "  REMOVE_STEP <n>\nEmit ONLY the fenced block. No commentary.")
PROPOSAL_INSTRUCTIONS = "\n\n".join(
    [ECON_OBJECTIVE, ACCEPT_CRIT, NUM_GUIDE, DELTA_FMT])
PRE_INSTRUCTIONS = "Reply with exactly this word and nothing else: ok"
PRE_INPUT = "ping"
PRE_TIMEOUT_S = 60.0


def _split_blocks(method_text: str) -> list[list[str]]:
    """Mirror of apply_delta's step-splitting loop (frozen econ/prompts.py).
    Block 1 is the preamble; each '<n>.'-led step is the next block."""
    lines = [l for l in method_text.splitlines()]
    steps: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s and s[0].isdigit() and len(s) > 1 and s[1] == "." and (
                len(s) == 2 or s[2] == " "):
            if cur:
                steps.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        steps.append(cur)
    return steps


def _block_listed_method(method_text: str) -> str:
    parts = []
    for i, b in enumerate(_split_blocks(method_text), 1):
        parts.append(f"[{i}]\n" + "\n".join(b))
    return "\n\n".join(parts)


def load_frozen():
    with open(os.path.join(STUDY, "corpus", "corpus.json")) as f:
        data = json.load(f)["eval"]
    h = hashlib.sha256()
    for t in data:
        h.update(json.dumps(t, sort_keys=True).encode())
    assert h.hexdigest() == CORPUS_SHA, "corpus hash mismatch"
    tasks = {t["task_id"]: corpus_mod.Task(**t) for t in data}
    with open(os.path.join(STUDY, "TASK_ALLOCATION.json")) as f:
        alloc = json.load(f)
    with open(os.path.join(STUDY, "SCHEDULE.json")) as f:
        sched_doc = json.load(f)
    assert sched_doc["schedule_sha256"] == SCHED_SHA, "schedule hash mismatch"
    sched_json = json.dumps(sched_doc["schedule"], indent=1, sort_keys=True)
    assert hashlib.sha256(sched_json.encode()).hexdigest() == SCHED_SHA
    return tasks, alloc, sched_doc["schedule"]


def spend_of(a):
    return float(a.get("actual_usd") if a.get("actual_usd") is not None
                 else a.get("reservation_usd", 0.0))


class Ctx:
    def __init__(self, run_dir, provider, sci_ledger):
        self.run_dir = run_dir
        self.raw = os.path.join(run_dir, "raw")
        os.makedirs(self.raw, exist_ok=True)
        self.stop = os.path.join(run_dir, "STOP")
        self.provider = provider
        self.ledger = sci_ledger
        self.tasks, self.alloc, self.sched = load_frozen()


def run_solving(cx, task_id, method_text, invocation_id):
    a = attempt_mod.attempt(cx.tasks[task_id], method_text, ledger=cx.ledger,
                            provider=cx.provider, envelopes=ENVS,
                            invocation_id=invocation_id, stop_file=cx.stop,
                            raw_dir=cx.raw)
    a.pop("code", None)
    return a


def receiver_gate(paired_parent, paired_cand):
    """Frozen receiver rule. Any non-ok attempt voids the round."""
    n = len(paired_parent)
    assert n == len(paired_cand) and n == 12
    for a in paired_parent + paired_cand:
        if a.get("status") != "ok":
            return False, {"void": True,
                           "reason": f"non-ok attempt {a.get('invocation_id')}"}
    vp = sum(a.get("verdict", 0) for a in paired_parent)
    vc = sum(a.get("verdict", 0) for a in paired_cand)
    cp = sum(spend_of(a) for a in paired_parent)
    cc = sum(spend_of(a) for a in paired_cand)
    regr = sum(1 for a, b in zip(paired_parent, paired_cand)
               if a.get("verdict") == 1 and b.get("verdict") != 1)
    ok = vp == 12 and vc == 12 and regr == 0 and cc <= cp
    return ok, dict(vp=vp, vc=vc, cp=round(cp, 6), cc=round(cc, 6),
                    regressions=regr, ratio=round(cc / cp, 4) if cp else None)


def acquire_once(cx, name, parent_method, disc_ids, promo_ids, tag):
    """One acquisition round: 3 discovery + 1 proposal + 12 paired promotion.
    Returns (accepted: bool, method_text, round_record)."""
    rec = {"name": name, "parent": ("M0" if parent_method == prompts.BASE_METHOD
                                   else "M1")}
    disc = [run_solving(cx, tid, parent_method, f"{SID}_{tag}d{i}")
            for i, tid in enumerate(disc_ids)]
    rec["discovery"] = [{"task_id": t, "verdict": a.get("verdict"),
                         "status": a.get("status")} for t, a in
                        zip(disc_ids, disc)]
    fb = "\n\n".join(
        f"--- DISCOVERY {i+1} ---\n" + acquire._feedback(cx.tasks[t], a)
        for i, (t, a) in enumerate(zip(disc_ids, disc)))
    body = ("CURRENT METHOD (block-numbered; use the [k] labels in your "
            "directives):\n" + _block_listed_method(parent_method)
            + "\n\n" + fb)
    tokens.enforce_cap(body, 7000, "proposal_input")
    res = worker.invoke(instructions=PROPOSAL_INSTRUCTIONS, input_text=body,
                        envelope=ENVS["proposal"], ledger=cx.ledger,
                        provider=cx.provider,
                        invocation_id=f"{SID}_{tag}p", stop_file=cx.stop,
                        raw_dir=cx.raw)
    if res.status != "ok" or not res.text:
        rec.update(accepted=False, reason=f"proposal_{res.status}")
        return False, parent_method, rec
    delta = extract.extract_delta(res.text)
    if delta is None:
        rec.update(accepted=False, reason="delta_extraction_failed")
        return False, parent_method, rec
    try:
        cand = prompts.apply_delta(parent_method, delta)
    except Exception as e:
        rec.update(accepted=False, reason=f"delta_rejected: {e}")
        return False, parent_method, rec
    rec["delta_sha256"] = hashlib.sha256(delta.encode()).hexdigest()
    rec["rendered_sha256"] = hashlib.sha256(cand.encode()).hexdigest()
    pp = [run_solving(cx, tid, parent_method, f"{SID}_{tag}P{i:02d}")
          for i, tid in enumerate(promo_ids)]
    pc = [run_solving(cx, tid, cand, f"{SID}_{tag}C{i:02d}")
          for i, tid in enumerate(promo_ids)]
    ok, gate = receiver_gate(pp, pc)
    rec["gate"] = gate
    rec.update(accepted=ok, reason="accepted" if ok else "receiver_rejected")
    return ok, (cand if ok else parent_method), rec


def operating(cx, methods):
    """36 frozen tasks; per-task arm order from the frozen schedule."""
    recs = []
    dropped = []
    for tid in cx.alloc["operating"]:
        arms = {}
        ok_all = True
        for arm in cx.sched[tid]:
            a = run_solving(cx, tid, methods[arm], f"{SID}_op_{tid}_{arm}")
            arms[arm] = a
            if a.get("status") != "ok":
                ok_all = False
        if not ok_all:
            dropped.append(tid)
            continue
        recs.append({"task_id": tid, "arms": arms})
    return recs, dropped


def arm_economics(recs):
    out = {}
    for arm in ("A", "B", "C"):
        w = sum(r["arms"][arm].get("verdict", 0) for r in recs)
        c = sum(spend_of(r["arms"][arm]) for r in recs)
        out[arm] = {"tasks": len(recs), "work": w, "spend_usd": round(c, 6),
                    "work_per_dollar": round(w / c, 4) if c else None}
    return out


def paired_ratio_ci(recs, x, y):
    """Paired per-task cost ratio work/$ comparison with 95% CI (normal)."""
    import math
    ds = []
    for r in recs:
        a, b = r["arms"][x], r["arms"][y]
        ca, cb = spend_of(a), spend_of(b)
        if ca > 0 and cb > 0:
            ds.append(math.log(ca / cb))
    n = len(ds)
    if n < 2:
        return {"n": n, "note": "insufficient"}
    m = sum(ds) / n
    sd = math.sqrt(sum((d - m) ** 2 for d in ds) / (n - 1))
    se = sd / math.sqrt(n)
    lo, hi = m - 1.96 * se, m + 1.96 * se
    return {"n": n, "log_ratio_mean": round(m, 4),
            "ratio_geomean": round(math.exp(m), 4),
            "ci95": [round(math.exp(lo), 4), round(math.exp(hi), 4)]}


def phase_spend(cx, invocation_prefixes):
    """Sum settled + retained-unresolved for invocations with given prefixes."""
    total = 0.0
    matched = set()
    for e in cx.ledger.entries:
        iid = e.get("invocation_id", "")
        if any(iid.startswith(p) for p in invocation_prefixes):
            matched.add(iid)
    # settle/unresolved entries carry the final amounts; reserves net to zero
    by_iid = {}
    for e in cx.ledger.entries:
        iid = e.get("invocation_id", "")
        if iid in matched:
            by_iid.setdefault(iid, []).append(e)
    for iid, es in by_iid.items():
        kinds = {e["kind"] for e in es}
        if "settle" in kinds:
            total += sum(e["actual"] for e in es if e["kind"] == "settle")
        elif "unresolved" in kinds:
            total += sum(e["reservation"] for e in es
                         if e["kind"] == "unresolved")
        else:
            total += sum(e["amount"] for e in es if e["kind"] == "reserve")
    return round(total, 6), sorted(matched)


def retire_open_reserves(cx):
    """Frozen interruption rule: open reserves become unresolved exposure,
    NEVER resent. Returns count retired."""
    n = 0
    for r in cx.ledger.open_reserves():
        cx.ledger._append({"kind": "unresolved",
                           "reservation_id": r["reservation_id"],
                           "invocation_id": r["invocation_id"],
                           "reservation": r["amount"],
                           "reason": "interrupted_resume_retired_no_resend"})
        n += 1
    return n


def run_study(cx):
    retired = retire_open_reserves(cx)
    log = {"run_id": SID, "retired_open_reserves": retired,
           "phase1_rounds": [], "phase2": None}
    # ---- Phase 1: acquire the first accepted improvement (up to K1 rounds)
    m1, m1_from = prompts.BASE_METHOD, None
    for r in range(1, K1 + 1):
        alloc_r = cx.alloc["phase1"][f"round{r}"]
        try:
            ok, m1, rec = acquire_once(
                cx, f"phase1_round{r}", prompts.BASE_METHOD,
                alloc_r["discovery"], alloc_r["promotion"], f"P1r{r}")
        except worker.OperatorStop:
            rec = {"name": f"phase1_round{r}", "accepted": False,
                   "reason": "operator_stop_round_void"}
            ok = False
        log["phase1_rounds"].append(rec)
        if ok:
            m1_from = f"phase1_round{r}"
            break
    log["m1_accepted"] = m1_from is not None
    # ---- Phase 2: C's further search from M1 (or M0 if phase-1 failed)
    parent2 = m1 if m1_from else prompts.BASE_METHOD
    alloc2 = cx.alloc["phase2"]["round1"]
    try:
        ok2, m2, rec2 = acquire_once(
            cx, "phase2_round1", parent2,
            alloc2["discovery"], alloc2["promotion"], "P2r1")
    except worker.OperatorStop:
        rec2 = {"name": "phase2_round1", "accepted": False,
                "reason": "operator_stop_phase_void"}
        ok2, m2 = False, parent2
    log["phase2"] = rec2
    log["m2_accepted"] = ok2
    methods = {"A": prompts.BASE_METHOD,
               "B": m1,
               "C": m2 if ok2 else m1}
    log["methods"] = {k: hashlib.sha256(v.encode()).hexdigest()
                      for k, v in methods.items()}
    # ---- Operating: frozen 36 tasks, scheduled arm order
    recs, dropped = operating(cx, methods)
    log["operating_dropped_tasks"] = dropped
    log["operating_paired_n"] = len(recs)
    log["arm_economics"] = arm_economics(recs)
    log["paired_B_vs_A"] = paired_ratio_ci(recs, "A", "B")
    log["paired_C_vs_B"] = paired_ratio_ci(recs, "B", "C")
    # ---- Frozen accounting split
    d1, d1_iids = phase_spend(cx, [f"{SID}_P1r1", f"{SID}_P1r2"])
    d2, d2_iids = phase_spend(cx, [f"{SID}_P2r1"])
    op = log["arm_economics"]
    allin = {
        "A": round(op["A"]["spend_usd"], 6),
        "B": round(d1 / 2 + op["B"]["spend_usd"], 6),
        "C": round(d1 / 2 + d2 + op["C"]["spend_usd"], 6),
    }
    log["accounting_split"] = {
        "D1_phase1_scientific_usd": d1,
        "D2_phase2_scientific_usd": d2,
        "D1_invocations": len(d1_iids), "D2_invocations": len(d2_iids),
        "arm_B_bears_D1_over_2": round(d1 / 2, 6),
        "arm_C_bears_D1_over_2": round(d1 / 2, 6),
        "arm_C_bears_D2": d2,
        "allin_spend_usd": allin,
        "allin_work_per_dollar": {
            k: round(op[k]["work"] / allin[k], 4) if allin[k] else None
            for k in ("A", "B", "C")},
    }
    log["ledger"] = {"settled_usd": round(cx.ledger.settled_total, 6),
                     "unresolved_usd": round(cx.ledger.unresolved_total, 6),
                     "encumbered_usd": round(cx.ledger.encumbered, 6),
                     "budget_usd": cx.ledger.budget}
    # ---- Frozen decision rules
    concl = len(recs) >= MIN_PAIRED
    regB = any(r["arms"]["A"].get("verdict") == 1 and
               r["arms"]["B"].get("verdict") != 1 for r in recs)
    regC = any(r["arms"]["B"].get("verdict") == 1 and
               r["arms"]["C"].get("verdict") != 1 for r in recs)
    w = log["accounting_split"]["allin_work_per_dollar"]
    moreB = concl and not regB and w["A"] and w["B"] and w["B"] / w["A"] >= 1.05
    moreC = concl and not regC and w["B"] and w["C"] and w["C"] / w["B"] >= 1.05
    log["terminal"] = {
        "operating_conclusive": concl,
        "regressions_B_vs_A": regB, "regressions_C_vs_B": regC,
        "B_produced_more_allin": bool(moreB),
        "C_produced_more_allin": bool(moreC),
    }
    return log


def call_inventory_check():
    # worst case: K1 rounds x (3 disc + 1 prop + 24 promo) + K2 x 28 + H x 3
    n = (K1 * 28) + (K2 * 28) + (H * 3)
    worst_res = n * ENVS["solving"]["reservation_usd"]
    return n, worst_res


def offline_validate():
    tasks, alloc, sched = load_frozen()
    n, worst = call_inventory_check()
    checks = {
        "corpus_hash": True, "schedule_hash": True,
        "allocation_covers": (
            len(alloc["phase1"]["round1"]["discovery"]) == 3 and
            len(alloc["phase1"]["round1"]["promotion"]) == 12 and
            len(alloc["phase2"]["round1"]["promotion"]) == 12 and
            len(alloc["operating"]) == H and len(alloc["spares"]) == 19),
        "no_task_reuse": len({t for ph in
            [alloc["phase1"]["round1"]["discovery"],
             alloc["phase1"]["round1"]["promotion"],
             alloc["phase1"]["round2"]["discovery"],
             alloc["phase1"]["round2"]["promotion"],
             alloc["phase2"]["round1"]["discovery"],
             alloc["phase2"]["round1"]["promotion"]] + [alloc["operating"]]
            for t in ph}) == 3 + 12 + 3 + 12 + 3 + 12 + H,
        "max_calls": n, "worst_case_reservation_usd": round(worst, 2),
        "budget_fits": worst <= BUDGET_SCI,
        "envelope_gate": all(v["reservation_usd"] <= 0.05
                             for v in ENVS.values()),
        "method_cap": len(prompts.BASE_METHOD.split()) < 1500,
    }
    # fixture conformance: every frozen fixture path exercised
    sample = tasks[alloc["operating"][0]]
    pkt = sample.packet()
    assert isinstance(pkt, str) and len(pkt) > 0
    v, _ = __import__("econ.evaluate", fromlist=["evaluate"]).evaluate(
        corpus_mod.TARGET_FILENAME, sample.reference_code,
        sample.support_files, sample.hidden_tests)
    assert v == 1, "reference must pass on frozen fixture"
    v2, _ = __import__("econ.evaluate", fromlist=["evaluate"]).evaluate(
        corpus_mod.TARGET_FILENAME, sample.target_code,
        sample.support_files, sample.hidden_tests)
    assert v2 == 0, "buggy target must fail on frozen fixture"
    checks["fixture_conformance"] = True
    # delta machinery on frozen method text (block 6 = CHECK step)
    d = ("REPLACE_STEP 6: CHECK. Walk the visible tests against your fixed "
         "file by hand, then re-read the changed lines once for syntax.")
    rendered = prompts.apply_delta(prompts.BASE_METHOD, d)
    assert "re-read the changed lines once for syntax" in rendered
    assert "Cover the edge case from step 2 explicitly" not in rendered
    checks["delta_roundtrip"] = True
    # block listing mirrors apply_delta's split (also on rendered methods)
    listed = _block_listed_method(prompts.BASE_METHOD)
    assert listed.split("[6]\n")[1].startswith("5. CHECK")
    listed2 = _block_listed_method(rendered)
    assert listed2.split("[6]\n")[1].startswith(
        "6. CHECK. Walk the visible tests")
    checks["block_listing_mirrors_split"] = True
    return checks


def run_preflight(run_dir, provider):
    led = ledger_mod.Ledger(BUDGET_APP,
                            os.path.join(run_dir, "apparatus_ledger.jsonl"))
    rec = {"invocation_id": f"{SID}_preflight", "scientific": False}
    posts = [0]

    class Counting(provider.__class__):
        def post(self, body, headers, timeout):
            posts[0] += 1
            return super().post(body, headers, timeout)

    prov = Counting()
    try:
        res = worker.invoke(instructions=PRE_INSTRUCTIONS, input_text=PRE_INPUT,
                            envelope=PRE_ENV, ledger=led, provider=prov,
                            invocation_id=rec["invocation_id"],
                            timeout_s=PRE_TIMEOUT_S,
                            raw_dir=os.path.join(run_dir, "raw"))
    except (worker.OperatorStop, worker.InfrastructureHalt) as e:
        rec.update(ok=False, provider_posts=posts[0],
                   failure_class="pre_dispatch_or_operator_stop",
                   reason=f"{type(e).__name__}: {str(e)[:200]}")
        return rec
    priced = None
    if res.status == "ok" and res.usage:
        try:
            priced = worker.settle_cost(res.usage)
        except Exception:
            priced = None
    ok = (res.status == "ok" and posts[0] == 1 and priced is not None
          and priced <= PRE_ENV["reservation_usd"])
    rec.update(ok=ok, provider_posts=posts[0], status=res.status,
               usage=res.usage, settled_usd=priced,
               nonempty_output=bool(res.text and res.text.strip()),
               reason=None if ok else (res.error or "preflight_checks_failed"))
    return rec


def run_qualify(run_dir, provider):
    """Model-output qualification (apparatus, paid): exact model, reasoning
    effort, completion budget, and parser qualified pre-contact for nonempty
    output. Toy prompts only: never the method, never a corpus task."""
    led = ledger_mod.Ledger(BUDGET_APP,
                            os.path.join(run_dir, "apparatus_ledger.jsonl"))
    cases = [
        ("q_solve1", ENVS["solving"],
         "Emit exactly one ```python fenced block containing a Python "
         "function add(a, b) that returns a+b. No other text.",
         extract.extract_file_block),
        ("q_delta1", ENVS["proposal"],
         "Emit exactly one ```delta fenced block containing exactly this "
         "line: REPLACE_STEP 6: CHECK. Rewritten check. No other text.",
         extract.extract_delta),
        ("q_solve2", ENVS["solving"],
         "Emit exactly one ```python fenced block containing a Python "
         "function mul(a, b) that returns a*b. No other text.",
         extract.extract_file_block),
    ]
    results = []
    for name, env, prompt, parser in cases:
        iid = f"{SID}_qual_{name}"
        try:
            res = worker.invoke(instructions=prompt, input_text="qualify",
                                envelope=env, ledger=led, provider=provider,
                                invocation_id=iid, timeout_s=120.0,
                                raw_dir=os.path.join(run_dir, "raw"))
        except (worker.OperatorStop, worker.InfrastructureHalt) as e:
            rec = {"invocation_id": iid, "scientific": False, "toy": True,
                   "ok": False, "failure_class": "pre_dispatch_or_halt",
                   "reason": f"{type(e).__name__}: {str(e)[:200]}"}
            results.append(rec)
            return results, led
        parsed = parser(res.text or "") if res.status == "ok" else None
        ok = (res.status == "ok" and res.usage is not None
              and parsed is not None and len(parsed.strip()) > 0)
        results.append({"invocation_id": iid, "scientific": False,
                        "toy": True, "ok": ok, "status": res.status,
                        "settled_usd": res.actual_usd,
                        "parsed_chars": len(parsed) if parsed else 0,
                        "nonempty_output": bool(res.text and res.text.strip()),
                        "reason": None if ok else (res.error or "qualify_failed")})
    return results, led


def main():
    args = set(sys.argv[1:])
    run_dir = os.path.join(STUDY, "runs", SID)
    os.makedirs(run_dir, exist_ok=True)
    if "--preflight" in args:
        rec = run_preflight(run_dir, worker.RealProvider())
        print(json.dumps(rec, indent=1))
        if not rec.get("ok"):
            raise SystemExit("PREFLIGHT FAILED: no scientific contact")
        return
    if "--qualify" in args:
        results, led = run_qualify(run_dir, worker.RealProvider())
        print(json.dumps(results, indent=1))
        print("apparatus ledger encumbered: %.6f / %.2f" %
              (led.encumbered, led.budget))
        if not all(r.get("ok") for r in results):
            raise SystemExit("QUALIFICATION FAILED: no scientific contact")
        print("MODEL-OUTPUT QUALIFICATION PASSED")
        return
    if "--authorize-paid-contact" in args:
        cx = Ctx(run_dir, worker.RealProvider(),
                 ledger_mod.Ledger(BUDGET_SCI,
                                   os.path.join(run_dir, "ledger.jsonl")))
        log = run_study(cx)
        with open(os.path.join(run_dir, "result.json"), "w") as f:
            json.dump(log, f, indent=1, sort_keys=True)
        print(json.dumps(log["terminal"], indent=1))
        print("ledger:", json.dumps(log["ledger"], indent=1))
        return
    # default: offline validation
    checks = offline_validate()
    print(json.dumps(checks, indent=1, sort_keys=True))
    assert all(v for k, v in checks.items()
               if k not in ("max_calls", "worst_case_reservation_usd")), checks
    print("OFFLINE VALIDATION PASSED — zero provider contact")


if __name__ == "__main__":
    main()
