#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import random
import secrets
import statistics
import string
import time
from pathlib import Path
from typing import Any

EXPERIMENT = "RIL-RANK-EXEC-001"
SCHEMA = "openline.ril-rank-exec-001.result.v1"
FEATURE_SPACE = {
    "strategy": ("guard", "normalize", "reorder", "cache", "retry", "vectorize"),
    "scope": ("narrow", "medium", "broad"),
    "evidence": ("direct", "derived", "speculative"),
    "complexity": ("low", "medium", "high"),
}
FAMILIES = ("dedupe-stream", "normalized-join", "sliding-window", "transient-fetch")
TASKS_PER_FAMILY = 20
CANDIDATES_PER_TASK = 12
EVALUATION_BUDGET = 4
MIN_PRIMARY_ADVANTAGE = 0.08
ACCEPT_RATIO = 0.80
INHERITED_LEARNING_COST_EVALUATIONS = 768
BASE_MAIN = "8bfc2298067c654dc25bfd911b87a209c29d60ad"
POLICY_SEAL_SHA256 = "51e8bbf519d4c36e86081eb9cf33be3aaf1c065ae897798cf168f1fc1df4cc29"
FREEZE_SHA256 = "081646d8f97a7a1730c0b2cb559fd6ea789b173d523691ba3f5aa4567657c7ab"

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PREREG_PATH = HERE / "RIL_RANK_EXEC_001_PREREGISTRATION.json"
POLICY_PATH = HERE / "frozen" / "RIL_RANK_001_POLICY_SEAL.json"
FREEZE_PATH = REPO_ROOT / "proofs" / "ril-rank-001" / "RIL_RANK_001_FREEZE.json"


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fsync_json(path: Path, obj: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    with path.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    return sha256_bytes(payload.encode())


def _digest(key_hex: str, *parts: Any) -> bytes:
    key = bytes.fromhex(key_hex)
    msg = "\x1f".join(str(p) for p in parts).encode()
    return hmac.new(key, msg, hashlib.sha256).digest()


def uniform01(key_hex: str, *parts: Any) -> float:
    d = _digest(key_hex, *parts)
    return (int.from_bytes(d[:8], "big") + 0.5) / 2**64


def rng_for(key_hex: str, *parts: Any) -> random.Random:
    return random.Random(int.from_bytes(_digest(key_hex, *parts)[:8], "big"))


def candidate_id(features: dict[str, str]) -> str:
    return sha256_bytes(canonical_bytes(features))[:16]


def generate_candidates(candidate_nonce: str, family: str, task_index: int) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    draw = 0
    while len(candidates) < CANDIDATES_PER_TASK:
        features: dict[str, str] = {}
        for feature, values in FEATURE_SPACE.items():
            d = _digest(candidate_nonce, family, task_index, draw, feature)
            features[feature] = values[int.from_bytes(d[:4], "big") % len(values)]
        cid = candidate_id(features)
        candidates.setdefault(cid, {"candidate_id": cid, "features": features})
        draw += 1
        if draw > 10000:
            raise RuntimeError("unable to generate unique candidates")
    return sorted(candidates.values(), key=lambda c: c["candidate_id"])


def rank_score(model: dict[str, Any], candidate: dict[str, Any]) -> float:
    return sum(model["atoms"][f"{k}={v}"]["log_odds"] for k, v in candidate["features"].items())


def learned_order(model: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    return [c["candidate_id"] for c in sorted(candidates, key=lambda c: (-rank_score(model, c), c["candidate_id"]))]


def baseline_order(seed: str, task_id: str, candidates: list[dict[str, Any]]) -> list[str]:
    def key(c: dict[str, Any]) -> tuple[str, str]:
        return hashlib.sha256(f"{seed}|{task_id}|{c['candidate_id']}".encode()).hexdigest(), c["candidate_id"]
    return [c["candidate_id"] for c in sorted(candidates, key=key)]


def key_mode(features: dict[str, str], task: dict[str, Any]) -> str:
    evidence = features["evidence"]
    complexity = features["complexity"]
    if evidence == "direct":
        mode = task.get("hint_mode", "identity")
    elif evidence == "derived":
        mode = "normalize" if task.get("derived_signal", False) else "identity"
    else:
        mode = "identity"
    if complexity == "low" and mode == "normalize":
        return "strip"
    if complexity == "high" and mode == "normalize":
        return "aggressive"
    return mode


def norm_text(s: str, mode: str) -> str:
    if mode == "identity":
        return s
    if mode == "strip":
        return s.strip()
    if mode == "normalize":
        return s.strip().casefold()
    if mode == "aggressive":
        return "".join(ch for ch in s.strip().casefold() if ch not in string.punctuation)
    raise ValueError(mode)


def make_task(family: str, index: int, data_nonce: str) -> dict[str, Any]:
    r = rng_for(data_nonce, family, index)
    if family == "dedupe-stream":
        base = [f"item-{i}" for i in range(r.randint(8, 18))]
        values: list[str] = []
        for _ in range(r.randint(70, 130)):
            x = r.choice(base)
            if r.random() < 0.55:
                x = x.upper()
            if r.random() < 0.55:
                x = (" " * r.randint(0, 2)) + x + (" " * r.randint(0, 2))
            if r.random() < 0.04:
                x = " " * r.randint(0, 2)
            values.append(x)
        return {"values": values, "hint_mode": "normalize", "derived_signal": True}
    if family == "normalized-join":
        keys = [f"k-{i}" for i in range(r.randint(18, 35))]
        left, right = [], []
        for i in range(r.randint(50, 90)):
            k = r.choice(keys)
            shown = k.upper() if r.random() < 0.5 else k
            if r.random() < 0.5:
                shown = f" {shown} "
            left.append((shown, i))
        for i, k in enumerate(keys):
            shown = k.upper() if r.random() < 0.5 else k
            if r.random() < 0.5:
                shown = f" {shown} "
            right.append((shown, i * 7 + 3))
        r.shuffle(right)
        return {"left": left, "right": right, "hint_mode": "normalize", "derived_signal": True}
    if family == "sliding-window":
        n = r.randint(90, 160)
        t = 0
        events = []
        for _ in range(n):
            t += r.randint(0, 4)
            events.append(t)
        if r.random() < 0.45:
            r.shuffle(events)
            sorted_hint = False
        else:
            sorted_hint = True
        queries = [(r.randint(0, max(events)), r.randint(5, 25)) for _ in range(r.randint(25, 45))]
        return {"events": events, "queries": queries, "hint_mode": "sorted" if sorted_hint else "unsorted", "derived_signal": sorted_hint}
    if family == "transient-fetch":
        keys = [f"key-{i}" for i in range(r.randint(10, 22))]
        requests = [r.choice(keys) for _ in range(r.randint(55, 100))]
        fail_counts = {k: r.choice([0, 0, 1, 1, 2]) for k in keys}
        values = {k: sha256_bytes(k.encode())[:8] for k in keys}
        return {"requests": requests, "fail_counts": fail_counts, "values": values, "hint_mode": "retry3", "derived_signal": any(v > 0 for v in fail_counts.values())}
    raise ValueError(family)


def dedupe_oracle(values: list[str]) -> list[str]:
    out, seen = [], set()
    for raw in values:
        k = raw.strip().casefold()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def eval_dedupe(task: dict[str, Any], f: dict[str, str]) -> tuple[bool, int, int]:
    values = task["values"]
    oracle = dedupe_oracle(values)
    baseline_ops = 0
    baseline_seen: list[str] = []
    for raw in values:
        k = raw.strip().casefold(); baseline_ops += 1
        if not k: continue
        found = False
        for old in baseline_seen:
            baseline_ops += 1
            if old == k: found = True; break
        if not found: baseline_seen.append(k)
    mode = key_mode(f, task)
    scope = f["scope"]
    strategy = f["strategy"]
    limit = len(values) if scope != "narrow" else max(1, len(values)//2)
    seq = values[:limit]
    ops = 0
    out: list[str] = []
    if strategy in {"cache", "vectorize"}:
        seen = set()
        for raw in seq:
            k = norm_text(raw, mode); ops += 1
            if scope == "broad" and not k: continue
            ops += 1
            if k in seen: continue
            seen.add(k); out.append(k)
    elif strategy == "reorder":
        ks = [norm_text(x, mode) for x in seq]; ops += len(seq)
        out = sorted({k for k in ks if k}); ops += len(seq)
    else:
        for raw in seq:
            k = norm_text(raw, mode); ops += 1
            if strategy == "guard" and not k: continue
            if scope == "broad" and not k: continue
            found = False
            for old in out:
                ops += 1
                if old == k: found = True; break
            if not found: out.append(k)
        if strategy == "retry": ops *= 2
    return out == oracle, ops, baseline_ops


def join_oracle(left: list[tuple[str,int]], right: list[tuple[str,int]]) -> list[tuple[int,int]]:
    rm = {k.strip().casefold(): v for k, v in right}
    return [(lv, rm[k.strip().casefold()]) for k, lv in left if k.strip().casefold() in rm]


def eval_join(task: dict[str, Any], f: dict[str, str]) -> tuple[bool,int,int]:
    left, right = task["left"], task["right"]
    oracle = join_oracle(left, right)
    baseline_ops = 0
    for lk, _ in left:
        nk = lk.strip().casefold(); baseline_ops += 1
        for rk, _ in right:
            baseline_ops += 1
            if nk == rk.strip().casefold(): break
    mode = key_mode(f, task); strategy=f["strategy"]; scope=f["scope"]
    lmode = mode if scope != "narrow" else "identity"
    rmode = mode
    ops=0; out=[]
    if strategy in {"cache","vectorize"}:
        rm={}
        for k,v in right:
            rm[norm_text(k,rmode)] = v; ops += 2
        for k,lv in left:
            nk=norm_text(k,lmode); ops += 2
            if nk in rm: out.append((lv,rm[nk]))
    elif strategy == "reorder":
        L=sorted((norm_text(k,lmode),v) for k,v in left); R=sorted((norm_text(k,rmode),v) for k,v in right); ops += len(L)+len(R)
        rm=dict(R); out=[(lv,rm[k]) for k,lv in L if k in rm]; ops += len(L)
        # restore left value order to compare semantic output
        out=sorted(out,key=lambda x:x[0])
        oracle=sorted(oracle,key=lambda x:x[0])
    else:
        for lk,lv in left:
            nk=norm_text(lk,lmode); ops+=1
            for rk,rv in right:
                ops+=1
                if nk == norm_text(rk,rmode): out.append((lv,rv)); break
        if strategy == "retry": ops *= 2
    return out == oracle, ops, baseline_ops


def window_oracle(events:list[int], queries:list[tuple[int,int]]) -> list[int]:
    return [sum(1 for e in events if t-w <= e <= t) for t,w in queries]


def eval_window(task:dict[str,Any], f:dict[str,str]) -> tuple[bool,int,int]:
    events, queries = task["events"], task["queries"]
    oracle=window_oracle(events,queries)
    baseline_ops=len(events)*len(queries)
    strategy=f["strategy"]; scope=f["scope"]; complexity=f["complexity"]; evidence=f["evidence"]
    qs=queries if scope != "narrow" else queries[:max(1,len(queries)//2)]
    assume_sorted = (task["hint_mode"]=="sorted") if evidence=="direct" else (all(events[i] <= events[i+1] for i in range(len(events)-1)) if evidence=="derived" else True)
    ev=list(events); ops=0
    if strategy in {"reorder","cache","vectorize"}:
        if not assume_sorted or strategy=="reorder": ev.sort(); ops += len(ev)*max(1,int(math.log2(max(2,len(ev)))))
        elif not all(ev[i] <= ev[i+1] for i in range(len(ev)-1)):
            # trusted a false assumption; optimized search will be wrong
            pass
        import bisect
        out=[]
        for t,w in qs:
            lo=t-w + (1 if complexity=="low" else 0)
            out.append(bisect.bisect_right(ev,t)-bisect.bisect_left(ev,lo)); ops += int(math.log2(max(2,len(ev))))*2
    else:
        out=[]
        for t,w in qs:
            c=0
            for e in ev:
                ops+=1
                if t-w <= e <= t: c+=1
            out.append(c)
        if strategy=="retry": ops*=2
    return out==oracle, ops, baseline_ops


def fetch_oracle(task:dict[str,Any]) -> list[str]:
    return [task["values"][k] for k in task["requests"]]


def eval_fetch(task:dict[str,Any], f:dict[str,str]) -> tuple[bool,int,int]:
    requests=task["requests"]; fails=task["fail_counts"]; vals=task["values"]; oracle=fetch_oracle(task)
    baseline_ops=sum((fails[k]+1) for k in requests)
    strategy=f["strategy"]; scope=f["scope"]; complexity=f["complexity"]; evidence=f["evidence"]
    if evidence=="direct": retries=3
    elif evidence=="derived": retries=3 if task["derived_signal"] else 1
    else: retries=1
    if complexity=="low": retries=min(retries,2)
    elif complexity=="high": retries=4
    out=[]; ops=0; cache={}
    for idx,k in enumerate(requests):
        use_cache = strategy in {"cache","vectorize"} and (scope!="narrow" or idx < len(requests)//2)
        if use_cache and k in cache:
            ops+=1; out.append(cache[k]); continue
        allowed = retries if strategy in {"retry","cache","vectorize","reorder"} else 1
        success=False
        for attempt in range(allowed):
            ops+=1
            if attempt >= fails[k]:
                out.append(vals[k]); cache[k]=vals[k]; success=True; break
        if not success: out.append("<FAIL>")
        if complexity=="high": ops += max(0, allowed-1)
    return out==oracle, ops, baseline_ops


def evaluate_candidate(family:str, task:dict[str,Any], candidate:dict[str,Any]) -> dict[str,Any]:
    f=candidate["features"]
    if family=="dedupe-stream": correct,ops,base=eval_dedupe(task,f)
    elif family=="normalized-join": correct,ops,base=eval_join(task,f)
    elif family=="sliding-window": correct,ops,base=eval_window(task,f)
    elif family=="transient-fetch": correct,ops,base=eval_fetch(task,f)
    else: raise ValueError(family)
    ratio=ops/base if base else math.inf
    accepted=bool(correct and ratio <= ACCEPT_RATIO)
    gain=(1.0-ratio) if correct else -1.0
    return {"candidate_id":candidate["candidate_id"],"features":f,"correct":correct,"operations":ops,"baseline_operations":base,"operation_ratio":ratio,"gain":gain,"accepted":accepted,"reason":"OBJECTIVE_CLEARED" if accepted else ("CORRECT_BUT_TOO_COSTLY" if correct else "INCORRECT")}


def score_order(order:list[str], outcomes:dict[str,dict[str,Any]], budget:int) -> dict[str,Any]:
    first=None; best=-math.inf
    for i,cid in enumerate(order[:budget],1):
        row=outcomes[cid]; best=max(best,float(row["gain"]))
        if first is None and row["accepted"]:
            first=i; break
    return {"found_acceptable":first is not None,"evaluations_to_first_acceptable":first,"evaluations_used":first if first is not None else budget,"censored_evaluations_to_first_acceptable":first if first is not None else budget+1,"best_gain_seen":best}


def summarize(rows:list[dict[str,Any]], method:str) -> dict[str,Any]:
    found=sum(1 for r in rows if r[method]["found_acceptable"])
    by_family={}
    for family in FAMILIES:
        fr=[r for r in rows if r["family"]==family]; ff=sum(1 for r in fr if r[method]["found_acceptable"])
        by_family[family]={"tasks":len(fr),"found_within_budget":ff,"found_within_budget_rate":ff/len(fr),"evaluations_used_total":sum(r[method]["evaluations_used"] for r in fr)}
    wins=[r[method]["evaluations_to_first_acceptable"] for r in rows if r[method]["evaluations_to_first_acceptable"] is not None]
    return {"tasks":len(rows),"found_within_budget":found,"found_within_budget_rate":found/len(rows),"evaluations_used_total":sum(r[method]["evaluations_used"] for r in rows),"mean_evaluations_used":statistics.fmean(r[method]["evaluations_used"] for r in rows),"mean_evaluations_to_first_win_among_wins":statistics.fmean(wins) if wins else None,"by_family":by_family}


def classify(e:float,b:float,s:float, eval_savings:int) -> str:
    eb=e-b >= MIN_PRIMARY_ADVANTAGE
    es=e-s >= MIN_PRIMARY_ADVANTAGE
    if eb and es and eval_savings>0: return "PASS_RIL_RANK_EXEC_001_EXECUTABLE_TRANSFER"
    if eb and not es: return "EXECUTABLE_RANKING_ADVANTAGE_HISTORY_BINDING_NOT_ESTABLISHED"
    if es and not eb: return "EXECUTABLE_HISTORY_SIGNAL_NO_BASELINE_ADVANTAGE"
    return "NO_EXECUTABLE_TRANSFER_ADVANTAGE"


def verify_inputs() -> dict[str,Any]:
    if sha256_file(POLICY_PATH) != POLICY_SEAL_SHA256: raise SystemExit("RIL-RANK-001 policy seal hash mismatch")
    if sha256_file(FREEZE_PATH) != FREEZE_SHA256: raise SystemExit("RIL-RANK-001 freeze hash mismatch")
    freeze=json.loads(FREEZE_PATH.read_text())
    if freeze["formal_verdict"] != "PASS_RIL_RANK_001_HISTORY_RANKING_SIGNAL": raise SystemExit("predecessor verdict mismatch")
    if freeze["level4_standing"] != "NOT_EARNED": raise SystemExit("predecessor claim boundary mismatch")
    policy=json.loads(POLICY_PATH.read_text())
    if policy["experiment"] != "RIL-RANK-001": raise SystemExit("wrong policy source")
    return policy


def self_check() -> None:
    prereg=json.loads(PREREG_PATH.read_text())
    assert prereg["experiment"]==EXPERIMENT
    assert prereg["primary_metric"]["evaluation_budget"]==EVALUATION_BUDGET
    assert prereg["primary_metric"]["min_rate_advantage_vs_each_control"]==MIN_PRIMARY_ADVANTAGE
    assert prereg["predecessor"]["main_sha"]==BASE_MAIN
    policy=verify_inputs()
    assert set(policy["learned_model"]["atoms"]) == set(policy["shuffled_model"]["atoms"])
    # Fixed smoke only: exercise all families and all feature values without revealing primary nonces.
    nonce="11"*32; data="22"*32
    for family in FAMILIES:
        task=make_task(family,0,data)
        cands=generate_candidates(nonce,family,0)
        assert len(cands)==CANDIDATES_PER_TASK
        outcomes=[evaluate_candidate(family,task,c) for c in cands]
        assert all(x["baseline_operations"]>0 for x in outcomes)
    print("RIL-RANK-EXEC-001 self-check: PASS")


def run(output:Path,evidence_dir:Path) -> dict[str,Any]:
    if output.exists() or evidence_dir.exists(): raise SystemExit("refusing to reuse output/evidence path")
    policy=verify_inputs(); prereg=json.loads(PREREG_PATH.read_text())
    evidence_dir.mkdir(parents=True,exist_ok=False)
    started=time.time()
    candidate_nonce=secrets.token_hex(32)
    tasks=[]
    for family in FAMILIES:
        for idx in range(TASKS_PER_FAMILY):
            task_id=f"{family}-{idx:03d}"; cands=generate_candidates(candidate_nonce,family,idx)
            tasks.append({"family":family,"task_index":idx,"task_id":task_id,"candidates":cands,"orders":{"baseline":baseline_order(policy["baseline_order_seed"],task_id,cands),"evidence":learned_order(policy["learned_model"],cands),"history_shuffled":learned_order(policy["shuffled_model"],cands)}})
    seal={"schema":"openline.ril-rank-exec-001.ranking-seal.v1","experiment":EXPERIMENT,"policy_seal_sha256":POLICY_SEAL_SHA256,"candidate_nonce":candidate_nonce,"tasks":tasks,"task_data_exists_at_seal":False}
    seal_sha=fsync_json(evidence_dir/"rankings-sealed-before-task-data.json",seal)
    data_nonce=secrets.token_hex(32)
    measured=[]; scored=[]
    for item in tasks:
        task=make_task(item["family"],item["task_index"],data_nonce)
        outs={}
        for c in item["candidates"]:
            row=evaluate_candidate(item["family"],task,c); outs[c["candidate_id"]]=row
            measured.append({"family":item["family"],"task_id":item["task_id"],**row})
        sr={"family":item["family"],"task_id":item["task_id"]}
        for method,order in item["orders"].items(): sr[method]=score_order(order,outs,EVALUATION_BUDGET)
        scored.append(sr)
    outcomes_sha=fsync_json(evidence_dir/"executable-outcomes.json",measured)
    scored_sha=fsync_json(evidence_dir/"scored-orders.json",scored)
    summaries={m:summarize(scored,m) for m in ("baseline","evidence","history_shuffled")}
    e=summaries["evidence"]["found_within_budget_rate"]; b=summaries["baseline"]["found_within_budget_rate"]; s=summaries["history_shuffled"]["found_within_budget_rate"]
    savings=summaries["baseline"]["evaluations_used_total"]-summaries["evidence"]["evaluations_used_total"]
    savings_per_task=savings/len(scored)
    break_even=math.ceil(INHERITED_LEARNING_COST_EVALUATIONS/savings_per_task) if savings_per_task>0 else None
    verdict=classify(e,b,s,savings)
    result={
      "schema":SCHEMA,"experiment":EXPERIMENT,"verdict":verdict,"scientific_standing":"CONTROLLED_EXECUTABLE_MICROTASK_TRANSFER","level4_standing":"NOT_EARNED","live_agent_standing":"NOT_TESTED",
      "predecessor":prereg["predecessor"],
      "primary_metric":{"name":"acceptable_improvement_found_within_fixed_evaluation_budget","evaluation_budget":EVALUATION_BUDGET,"tasks":len(scored),"evidence_rate":e,"baseline_rate":b,"history_shuffled_rate":s,"advantage_vs_baseline":e-b,"advantage_vs_history_shuffled":e-s,"min_rate_advantage_vs_each_control":MIN_PRIMARY_ADVANTAGE},
      "methods":summaries,
      "economics":{"inherited_learning_cost_evaluations":INHERITED_LEARNING_COST_EVALUATIONS,"downstream_evaluation_savings_vs_baseline":savings,"mean_savings_per_task_vs_baseline":savings_per_task,"projected_break_even_future_tasks_at_observed_savings_rate":break_even,"learning_cost_recovered_in_this_holdout":savings>=INHERITED_LEARNING_COST_EVALUATIONS},
      "integrity":{"exact_predecessor_policy_seal_sha256":POLICY_SEAL_SHA256,"rankings_sealed_before_task_data_nonce":True,"ranking_seal_sha256":seal_sha,"task_data_nonce":data_nonce,"executable_outcomes_sha256":outcomes_sha,"scored_orders_sha256":scored_sha,"same_candidate_pool_all_methods":True,"same_evaluation_budget_all_methods":True,"family_identity_excluded_from_inherited_rank_model":True,"no_new_ranker_training":True},
      "claim_boundary":prereg["claim_boundary"],"started_unix":started,"completed_unix":time.time()
    }
    fsync_json(output,result)
    return result


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--self-check",action="store_true"); ap.add_argument("--output",type=Path); ap.add_argument("--evidence-dir",type=Path); args=ap.parse_args()
    if args.self_check: self_check(); return 0
    if not args.output or not args.evidence_dir: ap.error("--output and --evidence-dir required unless --self-check")
    r=run(args.output,args.evidence_dir)
    print(json.dumps({"verdict":r["verdict"],"primary_metric":r["primary_metric"],"economics":r["economics"]},indent=2,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
