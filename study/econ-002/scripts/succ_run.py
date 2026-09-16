"""ECON-002 minimal successor falsifier. Reuses frozen econ-001 primitives
(attempt, ledger, worker, apply_delta, corpus, envelopes). Paired-12 /
20%-margin receiver gate; deterministic Stage 1, corrected-objective Stage 2.

Default: offline validation only (frozen artifacts, candidates, call
inventory, budget bound). ZERO provider contact. --authorize-paid-contact
executes the frozen paid plan; nothing billable runs without that flag.
"""
import sys, os, json, hashlib
HERE = os.path.dirname(os.path.abspath(__file__))
STUDY2 = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(STUDY2), "econ-001", "src"))
from econ import acquire, attempt as attempt_mod  # noqa: E402
from econ import corpus as corpus_mod, extract  # noqa: E402
from econ import ledger as ledger_mod, orchestrate, prompts, worker  # noqa: E402

SID, BUDGET, N, MARGIN = "econ002_c72e6357", 20.00, 12, 0.20
ORDER, NSTAGE2 = ["D1", "D2", "D3", "D4"], 2
OBJ = ("Produce one method change whose goal is lower measured execution cost "
    "while preserving equal-or-better verified success. You may delete, merge, "
    "shorten, simplify, or remove method steps. Added procedure is a regression "
    "unless it improves verified output enough to justify its cost.")
CRIT = ("Frozen receiver acceptance: on 12 fresh tasks attempted with both "
    "methods, the candidate must pass 12/12, the parent must pass 12/12, no "
    "task the parent passes may be failed by the candidate, and the candidate's "
    "total settled cost must be at most 80% of the parent's.")
NUM = ("Directive numbering (verified against apply_delta): block 1 is the "
    "preamble line; visible numbered step k is block k+1. Example: to delete "
    "the visible CHECK step, write REMOVE_STEP 6.")
FMT = ("Delta format inside one ```delta fenced block, one directive per line:\n"
    "  REPLACE_STEP <n>: <new step text>\n  ADD_STEP: <new step text>\n"
    "  REMOVE_STEP <n>\nEmit ONLY the fenced block. No commentary.")
PROMPT = "\n\n".join([OBJ, CRIT, NUM, FMT])
FIELDS = ("task_id", "family", "template", "statement", "target_code",
          "reference_code", "hidden_tests", "support_files")

def frozen():
    c = lambda p: json.load(open(STUDY2 + p))
    tasks = {t["task_id"]: corpus_mod.Task(**{k: t[k] for k in FIELDS})
             for t in c("/corpus/corpus.json")["eval"]}
    return tasks, c("/CANDIDATES.json"), c("/TASK_ALLOCATION.json")

def gate(p, q):  # paired-12 / 20% receiver rule
    assert len(p) == len(q) == N
    s = lambda a: float(a["actual_usd"] if a.get("actual_usd") is not None
                        else a.get("reservation_usd", 0.0))
    vp, vc = sum(a.get("verdict", 0) for a in p), sum(a.get("verdict", 0) for a in q)
    cp, cc = sum(s(a) for a in p), sum(s(a) for a in q)
    regr = sum(1 for a, b in zip(p, q) if a.get("verdict") == 1 and b.get("verdict") != 1)
    ok = vp == N and vc == N and regr == 0 and cc <= (1 - MARGIN) * cp
    return ok, dict(vp=vp, vc=vc, cp=cp, cc=cc, regressions=regr,
                    ratio=cc / cp if cp else None)

def runall(method, tids, tag, cx):  # one parent/candidate attempt per task
    out = []
    for i, tid in enumerate(tids):
        a = attempt_mod.attempt(cx["tasks"][tid], method, ledger=cx["ledger"],
            provider=cx["provider"], envelopes=cx["envs"],
            invocation_id=f"{SID}_{tag}_{i:02d}", stop_file=cx["stop"],
            raw_dir=cx["raw"])
        a.pop("code", None); out.append(a)
        if a.get("status") == "stopped":
            raise worker.OperatorStop("stop during " + tag)
    return out

def judge(name, cm, tids, cx):  # same 12 task IDs, parent and candidate
    ok, rec = gate(runall(prompts.BASE_METHOD, tids, name + "_P", cx),
                   runall(cm, tids, name + "_C", cx))
    rec.update(name=name, decision="accept" if ok else "reject")
    return rec

def propose(tids, cx):  # Stage-2 proposal; malformed -> charged rejection
    disc = runall(prompts.BASE_METHOD, tids, "S2d", cx)
    fb = "\n\n".join(f"--- DISCOVERY {i+1} ---\n" + acquire._feedback(
        cx["tasks"][t], a) for i, (t, a) in enumerate(zip(tids, disc)))
    res = worker.invoke(instructions=PROMPT,
        input_text="CURRENT METHOD:\n" + prompts.BASE_METHOD + "\n\n" + fb,
        envelope=cx["envs"]["proposal"], ledger=cx["ledger"],
        provider=cx["provider"], invocation_id=f"{SID}_S2p",
        stop_file=cx["stop"], raw_dir=cx["raw"])
    if res.status != "ok" or not res.text:
        return None, f"proposal_{res.status}"
    delta = extract.extract_delta(res.text)
    if delta is None:
        return None, "delta_extraction_failed"
    try:
        return prompts.apply_delta(prompts.BASE_METHOD, delta), None
    except Exception as e:
        return None, f"delta_rejected: {e}"

def offline():  # everything freezable, verified with zero provider contact
    tasks, cands, alloc = frozen()
    assert hashlib.sha256(open(STUDY2 + "/corpus/corpus.json", "rb").read()
        ).hexdigest() == alloc["corpus_sha256"] and len(tasks) == 78
    for n in ORDER:  # deterministic candidates immutable since freeze
        r = prompts.apply_delta(prompts.BASE_METHOD, cands["candidates"][n]["delta_text"])
        assert hashlib.sha256(r.encode()).hexdigest() == cands["candidates"][n]["rendered_sha256"], n
    used = [t for d in alloc["stage1"].values() for t in d["promotion_tasks"]]
    used += [t for d in alloc["stage2"].values() for t in d["discovery_tasks"] + d["promotion_tasks"]]
    assert len(used) == len(set(used)) == 78 and set(used) <= set(tasks)
    cfg = json.load(open(os.path.dirname(STUDY2) + "/econ-001/CONFIG.json"))
    rmax = max(cfg["envelopes"]["solving"]["reservation_usd"],
               cfg["envelopes"]["proposal"]["reservation_usd"])
    calls = 4 * 2 * N + NSTAGE2 * (3 + 1 + 2 * N)
    assert (worst := calls * rmax) <= BUDGET, "budget bound exceeded"
    print(f"offline OK: 78 tasks, 4 candidates bound, {calls} max calls, "
          f"worst-case reservation ${worst:.2f} <= ${BUDGET:.2f}. No provider contact.")

def paid():
    tasks, cands, alloc = frozen()
    rd = STUDY2 + f"/runs/{SID}"
    os.makedirs(rd + "/raw", exist_ok=True)
    cx = dict(tasks=tasks, provider=worker.RealProvider(), envs=
        orchestrate.load_envelopes(os.path.dirname(STUDY2) + "/econ-001/CONFIG.json"),
        ledger=ledger_mod.Ledger(BUDGET, rd + "/ledger.jsonl"),
        stop=rd + "/STOP", raw=rd + "/raw")
    results, accepted = [], None
    try:
        for name in ORDER:  # frozen order; never reordered on results
            cm = cands["candidates"][name]["rendered_method"]
            assert hashlib.sha256(cm.encode()).hexdigest() == cands["candidates"][name]["rendered_sha256"]
            rec = judge(name, cm, alloc["stage1"][name]["promotion_tasks"], cx)
            results.append(rec)
            if rec["decision"] == "accept":
                accepted = ["deterministic", name]; break
        if accepted is None:  # Stage 2 earned only if Stage 1 yields nothing
            for i in range(NSTAGE2):
                key = f"S{i+1}"
                cm, err = propose(alloc["stage2"][key]["discovery_tasks"], cx)
                if cm is None:
                    results.append(dict(name=key, decision="reject", reason=err)); continue
                rec = judge(key, cm, alloc["stage2"][key]["promotion_tasks"], cx)
                results.append(rec)
                if rec["decision"] == "accept":
                    accepted = ["model-proposed", key]; break
    except (worker.OperatorStop, worker.InfrastructureHalt) as e:
        results.append(dict(terminal=type(e).__name__, detail=str(e)[:200]))
    json.dump(dict(study_id=SID, results=results, accepted=accepted,
                   ledger=cx["ledger"].summary()), open(rd + "/study.json", "w"), indent=1)
    print(json.dumps(dict(accepted=accepted, results=results), indent=1))

if __name__ == "__main__":
    (paid if "--authorize-paid-contact" in sys.argv else offline)()
