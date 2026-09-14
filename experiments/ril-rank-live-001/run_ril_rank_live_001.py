#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from typing import Any

EXPERIMENT="RIL-RANK-LIVE-001"
SCHEMA="openline.ril-rank-live-001.result.v3"
SCIENTIFIC_STANDING="LIVE_AGENT_SELECTION_MATCHED_TRANSFER_SINGLE_RUN"
PREDECESSOR_MAIN="2a808e764fe898f76dcb5025283eba98beafa3b1"
PREDECESSOR_FREEZE_BLOB="ad893c75856b2f4518a5fb82b7fe8fb28f1dc769"
PREDECESSOR_RUNNER_SHA256="bd350e1144068d10e9354ccec4a67de42810658f0ea9303899bc741f980c060a"
POLICY_SEAL_SHA256="51e8bbf519d4c36e86081eb9cf33be3aaf1c065ae897798cf168f1fc1df4cc29"
TASKS_PER_FAMILY=4
SELECTION_BUDGET=4
TASKS_TOTAL=16
REQUIRED_SUCCESS_COUNT_ADVANTAGE=2
MIN_RATE_ADVANTAGE=0.125
INHERITED_LEARNING_COST_EVALUATIONS=768
HARD_SPEND_CEILING_USD=Decimal("2.56")
SESSION_SPEND_AUTHORIZATION_USD=Decimal("1.28")
RESEARCHER_PRODUCT="Muse"
RESEARCHER_MODEL="Muse Spark 1.3"
RESEARCHER_NAME="Prince"
ALLOWED_TOOLS=["Muse conversational reasoning","Muse Linux VM shell/filesystem","Muse browser/internet"]

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PREREG_PATH=HERE/"RIL_RANK_LIVE_001_PREREGISTRATION.json"
VALIDATOR_PATH=HERE/"protected"/"live_agent_driver.py"
PREDECESSOR_RUNNER=ROOT/"experiments"/"ril-rank-exec-001"/"run_ril_rank_exec_001.py"
POLICY_PATH=ROOT/"experiments"/"ril-rank-exec-001"/"frozen"/"RIL_RANK_001_POLICY_SEAL.json"
PREDECESSOR_FREEZE=ROOT/"proofs"/"ril-rank-exec-001"/"RIL_RANK_EXEC_001_FREEZE.json"

HISTORY_TEXT=(
    "Receiver history is identical in both arms. Candidate features are strategy, scope, evidence, and complexity. "
    "No candidate-specific outcome, terminal score, hidden oracle result, or task-family success table is disclosed. "
    "The presentation order is the only matched packet input allowed to differ. Prince may ignore or reconstruct it."
)


def sha256_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def canonical_json(v: Any) -> bytes: return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def write_json(path: Path,v: Any) -> str:
    path.parent.mkdir(parents=True,exist_ok=True); data=(json.dumps(v,indent=2,sort_keys=True)+"\n").encode(); path.write_bytes(data); return sha256_bytes(data)
def read_json(path: Path) -> Any: return json.loads(path.read_text())
def sh(*args: str,cwd: Path|None=None) -> str:
    cp=subprocess.run(list(args),cwd=None if cwd is None else str(cwd),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if cp.returncode: raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(args)}\n{cp.stderr[-1200:]}")
    return cp.stdout.strip()
def git_available() -> bool: return shutil.which("git") is not None and (ROOT/".git").exists()
def current_head() -> str|None: return sh("git","rev-parse","HEAD",cwd=ROOT) if git_available() else None


def verify_git_lineage() -> None:
    if not git_available(): return
    if subprocess.run(["git","merge-base","--is-ancestor",PREDECESSOR_MAIN,"HEAD"],cwd=ROOT).returncode:
        raise RuntimeError("HEAD is not descended from frozen predecessor main")
    blob=sh("git","rev-parse","HEAD:proofs/ril-rank-exec-001/RIL_RANK_EXEC_001_FREEZE.json",cwd=ROOT)
    if blob!=PREDECESSOR_FREEZE_BLOB: raise RuntimeError("predecessor freeze blob changed")


def verify_predecessor() -> None:
    if not PREDECESSOR_RUNNER.is_file() or sha256_file(PREDECESSOR_RUNNER)!=PREDECESSOR_RUNNER_SHA256: raise RuntimeError("exact RIL-RANK-EXEC-001 engine missing")
    if not POLICY_PATH.is_file() or sha256_file(POLICY_PATH)!=POLICY_SEAL_SHA256: raise RuntimeError("exact frozen policy seal missing")
    freeze=read_json(PREDECESSOR_FREEZE)
    if freeze.get("formal_verdict")!="PASS_RIL_RANK_EXEC_001_EXECUTABLE_TRANSFER": raise RuntimeError("predecessor did not pass")
    if freeze.get("live_agent_standing")!="NOT_TESTED" or freeze.get("level4_standing")!="NOT_EARNED": raise RuntimeError("predecessor claim boundary changed")
    verify_git_lineage()


def load_engine():
    verify_predecessor(); spec=importlib.util.spec_from_file_location("ril_rank_exec_001_frozen_engine",PREDECESSOR_RUNNER)
    if spec is None or spec.loader is None: raise RuntimeError("could not load frozen engine")
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod


def load_validator():
    spec=importlib.util.spec_from_file_location("ril_rank_live_validator",VALIDATOR_PATH)
    if spec is None or spec.loader is None: raise RuntimeError("validator load failed")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def prereg() -> dict[str,Any]:
    v=read_json(PREREG_PATH)
    if v.get("schema")!="openline.ril-rank-live-001.preregistration.v3" or v.get("experiment")!=EXPERIMENT: raise RuntimeError("unexpected preregistration")
    return v


def verify_frozen_files(v: dict[str,Any],require_committed: bool) -> None:
    for rel,expected in v["frozen_files"].items():
        p=ROOT/rel
        if not p.is_file() or sha256_file(p)!=expected: raise RuntimeError(f"frozen file mismatch: {rel}")
    if require_committed and git_available():
        if sh("git","status","--porcelain",cwd=ROOT): raise RuntimeError("committed clean tree required")
        for rel,expected in v["frozen_files"].items():
            cp=subprocess.run(["git","show",f"HEAD:{rel}"],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if cp.returncode or sha256_bytes(cp.stdout)!=expected: raise RuntimeError(f"uncommitted frozen file: {rel}")
        rel=PREREG_PATH.relative_to(ROOT).as_posix(); cp=subprocess.run(["git","show",f"HEAD:{rel}"],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if cp.returncode or sha256_bytes(cp.stdout)!=sha256_file(PREREG_PATH): raise RuntimeError("preregistration must be committed unchanged")


def task_public_context(family: str,task: dict[str,Any]) -> dict[str,Any]:
    if family=="dedupe-stream":
        values=list(task["values"]); return {"family":family,"input_count":len(values),"sample":values[:8],"receiver_hint":task.get("hint_mode"),"derived_signal":bool(task.get("derived_signal")),"goal":"preserve first-occurrence dedupe semantics while reducing counted operations"}
    if family=="normalized-join":
        left,right=list(task["left"]),list(task["right"]); return {"family":family,"left_count":len(left),"right_count":len(right),"left_key_sample":[x[0] for x in left[:5]],"right_key_sample":[x[0] for x in right[:5]],"receiver_hint":task.get("hint_mode"),"derived_signal":bool(task.get("derived_signal")),"goal":"preserve normalized join semantics while reducing counted operations"}
    if family=="sliding-window":
        events,queries=list(task["events"]),list(task["queries"]); return {"family":family,"event_count":len(events),"query_count":len(queries),"event_sample":events[:10],"query_sample":queries[:5],"receiver_hint":task.get("hint_mode"),"derived_signal":bool(task.get("derived_signal")),"goal":"preserve window counts while reducing counted operations"}
    if family=="transient-fetch":
        req=list(task["requests"]); fails=dict(task["fail_counts"]); return {"family":family,"request_count":len(req),"unique_keys":len(set(req)),"request_sample":req[:10],"observed_failure_count_sample":{k:fails[k] for k in sorted(fails)[:5]},"receiver_hint":task.get("hint_mode"),"derived_signal":bool(task.get("derived_signal")),"goal":"preserve successful fetch results while reducing counted operations"}
    raise ValueError(family)


def candidate_description(c: dict[str,Any]) -> str:
    f=c["features"]
    return f"strategy={f['strategy']}; scope={f['scope']}; evidence={f['evidence']}; complexity={f['complexity']}"


def packet_task(task_id: str,public_context: dict[str,Any],ordered: list[dict[str,Any]]) -> dict[str,Any]:
    return {
        "task_id":task_id,
        "task_public_context":public_context,
        "candidate_pool_in_presented_order":[
            {"presentation_position":i+1,"candidate_id":c["candidate_id"],"description":candidate_description(c),"features":c["features"]}
            for i,c in enumerate(ordered)
        ],
        "instruction":f"Select exactly {SELECTION_BUDGET} unique candidate IDs from the full pool and return them in the order you would evaluate them."
    }


def make_packet(tasks: list[dict[str,Any]]) -> dict[str,Any]:
    return {
        "schema":"openline.ril-rank-live-001.prince-packet.v3",
        "experiment":EXPERIMENT,
        "researcher":{"product":RESEARCHER_PRODUCT,"model":RESEARCHER_MODEL,"name":RESEARCHER_NAME},
        "shared_history":HISTORY_TEXT,
        "available_tools":ALLOWED_TOOLS,
        "tool_rule":"Same normal Muse configuration in both sessions; do not add/remove/upgrade/subscribe to tools or initiate separately billed services.",
        "authority":"proposal-only selection; receiver evaluates candidate implementations after response",
        "limits":{"task_decisions":len(tasks),"selected_candidates_per_task":SELECTION_BUDGET,"incremental_paid_spend_authorization_per_session_usd":str(SESSION_SPEND_AUTHORIZATION_USD),"global_incremental_paid_spend_ceiling_usd":str(HARD_SPEND_CEILING_USD)},
        "tasks":tasks,
        "response_schema":{"experiment":EXPERIMENT,"orders":[{"task_id":"<task id>","evaluation_order":["<id>","<id>","<id>","<id>"]}],"tools_used":[]},
        "cross_arm_rule":"This fresh session receives only this packet. Do not seek, request, or inspect the matched packet or receiver map."
    }


def normalized_visible_packet(packet: dict[str,Any]) -> dict[str,Any]:
    x=deepcopy(packet)
    for task in x["tasks"]:
        pool=[]
        for c in task["candidate_pool_in_presented_order"]:
            c=dict(c); c.pop("presentation_position",None); pool.append(c)
        task["candidate_pool_in_presented_order"]=sorted(pool,key=lambda c:c["candidate_id"])
    return x


def assert_only_candidate_order_differs(a: dict[str,Any],b: dict[str,Any]) -> str:
    na,nb=normalized_visible_packet(a),normalized_visible_packet(b)
    if canonical_json(na)!=canonical_json(nb): raise RuntimeError("matched packet inputs differ beyond candidate presentation order")
    for ta,tb in zip(a["tasks"],b["tasks"]):
        if ta["task_id"]!=tb["task_id"]: raise RuntimeError("task identity mismatch")
        ma={c["candidate_id"]:(c["description"],c["features"]) for c in ta["candidate_pool_in_presented_order"]}
        mb={c["candidate_id"]:(c["description"],c["features"]) for c in tb["candidate_pool_in_presented_order"]}
        if ma!=mb: raise RuntimeError("candidate IDs/descriptions/features differ across packets")
    return sha256_bytes(canonical_json(na))


def cost_template() -> dict[str,Any]:
    return {
        "schema":"openline.ril-rank-live-001.cost-record.v1","experiment":EXPERIMENT,"currency":"USD",
        "hard_incremental_paid_spend_ceiling_usd":str(HARD_SPEND_CEILING_USD),
        "session_spend_authorization_usd":str(SESSION_SPEND_AUTHORIZATION_USD),
        "sessions":{
            "session-1":{"incremental_paid_usd":None,"billing_basis":None,"source":None,"complete":False},
            "session-2":{"incremental_paid_usd":None,"billing_basis":None,"source":None,"complete":False}
        },
        "receiver_incremental_paid_usd":None,"receiver_cost_basis":None,"receiver_cost_source":None,
        "other_incremental_paid_usd":None,"other_cost_basis":None,"other_cost_source":None,
        "operator_rule":"Fill actual incremental paid costs. Zero is valid only when basis/source state why no incremental charge occurred. Do not allocate fixed subscription cost unless actually charged incrementally by this experiment."
    }


def prepare(out_dir: Path) -> dict[str,Any]:
    if out_dir.exists(): raise SystemExit("refusing to overwrite prepared directory")
    v=prereg(); verify_predecessor(); verify_frozen_files(v,require_committed=True); engine=load_engine(); policy=read_json(POLICY_PATH)
    out_dir.mkdir(parents=True)
    candidate_nonce=secrets.token_hex(32); sealed=[]
    for family in engine.FAMILIES:
        for idx in range(TASKS_PER_FAMILY):
            tid=f"{family}-{idx:03d}"; cands=engine.generate_candidates(candidate_nonce,family,idx)
            sealed.append({"family":family,"task_index":idx,"task_id":tid,"candidates":cands,"orders":{"evidence":engine.learned_order(policy["learned_model"],cands),"baseline":engine.baseline_order(policy["baseline_order_seed"],tid,cands)}})
    order_seal={"schema":"openline.ril-rank-live-001.ordering-seal.v3","experiment":EXPERIMENT,"policy_seal_sha256":POLICY_SEAL_SHA256,"candidate_nonce":candidate_nonce,"task_data_exists_at_seal":False,"tasks":sealed}
    order_sha=write_json(out_dir/"receiver-ordering-seal-before-task-data.json",order_seal)
    data_nonce=secrets.token_hex(32); session_slots=["session-1","session-2"]; arms=["evidence","baseline"]
    if secrets.randbits(1): arms.reverse()
    mapping=dict(zip(session_slots,arms)); packets={}
    for slot in session_slots:
        arm=mapping[slot]; tasks=[]
        for item in sealed:
            task=engine.make_task(item["family"],item["task_index"],data_nonce); by={c["candidate_id"]:c for c in item["candidates"]}; ordered=[by[cid] for cid in item["orders"][arm]]
            tasks.append(packet_task(item["task_id"],task_public_context(item["family"],task),ordered))
        packet=make_packet(tasks); p=out_dir/slot/"packet.json"; sha=write_json(p,packet); packets[slot]={"filename":f"{slot}/packet.json","sha256":sha,"arm":arm}
    p1=read_json(out_dir/"session-1"/"packet.json"); p2=read_json(out_dir/"session-2"/"packet.json"); normalized_sha=assert_only_candidate_order_differs(p1,p2)
    map_obj={
        "schema":"openline.ril-rank-live-001.receiver-map.v3","experiment":EXPERIMENT,"created_utc":datetime.now(timezone.utc).isoformat(),
        "experiment_head_sha":current_head(),"predecessor_main":PREDECESSOR_MAIN,"ordering_seal_sha256":order_sha,"task_data_nonce":data_nonce,
        "session_order":session_slots,"packet_mapping":packets,"normalized_visible_packet_sha256":normalized_sha,
        "only_visible_packet_difference":"candidate_pool_in_presented_order sequence",
        "budget_rule":{"hard_incremental_paid_spend_ceiling_usd":str(HARD_SPEND_CEILING_USD),"session_spend_authorization_usd":str(SESSION_SPEND_AUTHORIZATION_USD),"on_exhaustion":"BUDGET_EXHAUSTED_BEFORE_MATCH_COMPLETE; stop entire experiment; no retry or budget increase"},
        "researcher_protocol":{"product":RESEARCHER_PRODUCT,"model":RESEARCHER_MODEL,"name":RESEARCHER_NAME,"fresh_session_per_slot":True,"matched_packet_hidden":True,"persistent_product_memory_absence_not_claimed":True}
    }
    map_sha=write_json(out_dir/"receiver-map.json",map_obj); cost_sha=write_json(out_dir/"COST_RECORD_TEMPLATE.json",cost_template())
    return {"experiment_head_sha":map_obj["experiment_head_sha"],"receiver_map_sha256":map_sha,"cost_template_sha256":cost_sha,"packet_files":["session-1/packet.json","session-2/packet.json"],"normalized_visible_packet_sha256":normalized_sha}


def decimal_field(v: Any,name: str) -> Decimal:
    try: x=Decimal(str(v))
    except (InvalidOperation,ValueError): raise RuntimeError(f"invalid cost field {name}")
    if x<0: raise RuntimeError(f"negative cost field {name}")
    return x


def validate_cost_record(obj: dict[str,Any]) -> dict[str,Any]:
    if obj.get("schema")!="openline.ril-rank-live-001.cost-record.v1" or obj.get("experiment")!=EXPERIMENT or obj.get("currency")!="USD": raise RuntimeError("wrong cost record")
    if Decimal(str(obj.get("hard_incremental_paid_spend_ceiling_usd")))!=HARD_SPEND_CEILING_USD: raise RuntimeError("cost ceiling drift")
    if Decimal(str(obj.get("session_spend_authorization_usd")))!=SESSION_SPEND_AUTHORIZATION_USD: raise RuntimeError("session spend authorization drift")
    session_costs={}
    for slot in ("session-1","session-2"):
        row=obj.get("sessions",{}).get(slot,{})
        if row.get("complete") is not True or not str(row.get("billing_basis") or "").strip() or not str(row.get("source") or "").strip(): raise RuntimeError(f"incomplete cost telemetry for {slot}")
        cost=decimal_field(row.get("incremental_paid_usd"),f"{slot}.incremental_paid_usd")
        if cost>SESSION_SPEND_AUTHORIZATION_USD: raise RuntimeError(f"{slot} exceeded frozen $1.28 authorization")
        session_costs[slot]=cost
    receiver=decimal_field(obj.get("receiver_incremental_paid_usd"),"receiver_incremental_paid_usd")
    other=decimal_field(obj.get("other_incremental_paid_usd"),"other_incremental_paid_usd")
    if not str(obj.get("receiver_cost_basis") or "").strip() or not str(obj.get("receiver_cost_source") or "").strip(): raise RuntimeError("incomplete receiver cost telemetry")
    if not str(obj.get("other_cost_basis") or "").strip() or not str(obj.get("other_cost_source") or "").strip(): raise RuntimeError("incomplete other cost telemetry")
    total=sum(session_costs.values(),Decimal("0"))+receiver+other
    if total>HARD_SPEND_CEILING_USD: raise RuntimeError(f"global paid spend ceiling exceeded: {total} > {HARD_SPEND_CEILING_USD}")
    return {"session_costs":session_costs,"receiver":receiver,"other":other,"total":total}


def write_manifest(root: Path) -> str:
    lines=[]
    for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name!="MANIFEST.sha256"):
        lines.append(f"{sha256_file(p)}  {p.relative_to(root).as_posix()}")
    data=("\n".join(lines)+"\n").encode(); (root/"MANIFEST.sha256").write_bytes(data); return sha256_bytes(data)


def score(prepared: Path,response1: Path,response2: Path,cost_record: Path,output: Path,evidence_dir: Path) -> dict[str,Any]:
    if output.exists() or evidence_dir.exists(): raise SystemExit("refusing to reuse output/evidence path")
    v=prereg(); verify_predecessor(); verify_frozen_files(v,require_committed=True); engine=load_engine(); validator=load_validator(); rmap=read_json(prepared/"receiver-map.json")
    if rmap.get("experiment")!=EXPERIMENT: raise RuntimeError("wrong receiver map")
    if rmap.get("experiment_head_sha") and current_head()!=rmap["experiment_head_sha"]: raise RuntimeError("experiment HEAD changed after prepare")
    seal_path=prepared/"receiver-ordering-seal-before-task-data.json"
    if sha256_file(seal_path)!=rmap["ordering_seal_sha256"]: raise RuntimeError("ordering seal hash mismatch")
    p1=read_json(prepared/"session-1"/"packet.json"); p2=read_json(prepared/"session-2"/"packet.json")
    if assert_only_candidate_order_differs(p1,p2)!=rmap["normalized_visible_packet_sha256"]: raise RuntimeError("packet normalized hash mismatch")
    responses={"session-1":read_json(response1),"session-2":read_json(response2)}; response_paths={"session-1":response1,"session-2":response2}
    cost_obj=read_json(cost_record); costs=validate_cost_record(cost_obj); seal=read_json(seal_path); task_data_nonce=rmap["task_data_nonce"]
    evidence_dir.mkdir(parents=True); summaries={"evidence":[],"baseline":[]}; rows=[]; tools_by_arm={}; selected_by_task={}
    for slot in ("session-1","session-2"):
        meta=rmap["packet_mapping"][slot]; pp=prepared/meta["filename"]
        if sha256_file(pp)!=meta["sha256"]: raise RuntimeError(f"packet drift: {slot}")
        packet=read_json(pp); valid,orders,issues,tools=validator.validate_response(packet,responses[slot])
        write_json(evidence_dir/f"{slot}-response-validation.json",{"slot":slot,"valid":valid,"issues":issues,"response_sha256":sha256_file(response_paths[slot]),"tools_used":tools})
        if not valid: raise RuntimeError(f"invalid Prince response {slot}: {issues}")
        arm=meta["arm"]; tools_by_arm[arm]=tools
        presented={t["task_id"]:[c["candidate_id"] for c in t["candidate_pool_in_presented_order"]] for t in packet["tasks"]}
        selected_by_task[arm]={}
        for item in seal["tasks"]:
            tid=item["task_id"]; family=item["family"]; idx=item["task_index"]; task=engine.make_task(family,idx,task_data_nonce); by={c["candidate_id"]:c for c in item["candidates"]}; outcomes={cid:engine.evaluate_candidate(family,task,c) for cid,c in by.items()}
            selected=orders[tid]; rr=engine.score_order(selected,outcomes,SELECTION_BUDGET); summaries[arm].append(rr); selected_by_task[arm][tid]=selected
            pos={cid:i+1 for i,cid in enumerate(presented[tid])}
            rows.append({"slot":slot,"arm":arm,"task_id":tid,"presented_order":presented[tid],"prince_selected_order":selected,"selected_presented_positions":[pos[x] for x in selected],"receiver_result":rr})
    def arm_summary(arm: str) -> dict[str,Any]:
        xs=summaries[arm]; found=sum(bool(x["found_acceptable"]) for x in xs); ev=sum(int(x["evaluations_used"]) for x in xs); slot=next(s for s,m in rmap["packet_mapping"].items() if m["arm"]==arm); paid=costs["session_costs"][slot]
        return {"tasks":len(xs),"confirmed_improvements":found,"confirmed_improvement_rate":found/len(xs),"receiver_evaluations_used_total":ev,"mean_receiver_evaluations_used":ev/len(xs),"researcher_sessions":1,"researcher_task_decisions":len(xs),"incremental_paid_researcher_usd":str(paid),"confirmed_improvements_per_incremental_paid_researcher_usd":(float(Decimal(found)/paid) if paid>0 else None),"tools_used":tools_by_arm.get(arm,[])}
    es,bs=arm_summary("evidence"),arm_summary("baseline")
    paired=[]; counts={"evidence_only":0,"baseline_only":0,"both":0,"neither":0}; same_set=0; same_order=0
    by_arm_row={(r["arm"],r["task_id"]):r for r in rows}
    for item in seal["tasks"]:
        tid=item["task_id"]; er=by_arm_row[("evidence",tid)]; br=by_arm_row[("baseline",tid)]; ef=bool(er["receiver_result"]["found_acceptable"]); bf=bool(br["receiver_result"]["found_acceptable"])
        bucket="both" if ef and bf else "evidence_only" if ef else "baseline_only" if bf else "neither"; counts[bucket]+=1
        if set(er["prince_selected_order"])==set(br["prince_selected_order"]): same_set+=1
        if er["prince_selected_order"]==br["prince_selected_order"]: same_order+=1
        paired.append({"task_id":tid,"evidence_found":ef,"baseline_found":bf,"pair_bucket":bucket,"evidence_evaluations":er["receiver_result"]["evaluations_used"],"baseline_evaluations":br["receiver_result"]["evaluations_used"],"evidence_selected":er["prince_selected_order"],"baseline_selected":br["prince_selected_order"]})
    success_delta=es["confirmed_improvements"]-bs["confirmed_improvements"]; advantage=success_delta/TASKS_TOTAL; eval_savings=bs["receiver_evaluations_used_total"]-es["receiver_evaluations_used_total"]
    if success_delta>=REQUIRED_SUCCESS_COUNT_ADVANTAGE and eval_savings>0: verdict="PASS_RIL_RANK_LIVE_001_SINGLE_RUN_LIVE_SELECTION_TRANSFER"
    elif success_delta<=-REQUIRED_SUCCESS_COUNT_ADVANTAGE: verdict="OBSERVED_LIVE_RANKING_DISADVANTAGE"
    else: verdict="NO_OBSERVED_LIVE_TRANSFER_ADVANTAGE"
    savings_per_task=eval_savings/TASKS_TOTAL; projected=math.ceil(INHERITED_LEARNING_COST_EVALUATIONS/savings_per_task) if savings_per_task>0 else None
    rows_sha=write_json(evidence_dir/"matched-live-rows.json",rows); pairs_sha=write_json(evidence_dir/"paired-outcomes.json",{"counts":counts,"pairs":paired}); write_json(evidence_dir/"cost-record.json",cost_obj); shutil.copy2(response1,evidence_dir/"session-1-response.json"); shutil.copy2(response2,evidence_dir/"session-2-response.json")
    result={
        "schema":SCHEMA,"experiment":EXPERIMENT,"verdict":verdict,"scientific_standing":SCIENTIFIC_STANDING,
        "repeatability_standing":"NOT_TESTED_SINGLE_MATCHED_PAIR","level4_standing":"NOT_EARNED","recursive_improvement_standing":"NOT_EARNED",
        "predecessor":v["predecessor"],"primary_metric":{"name":"paired_receiver_confirmed_success_after_prince_selects_four_from_full_pool","tasks":TASKS_TOTAL,"selection_budget":SELECTION_BUDGET,"evidence_successes":es["confirmed_improvements"],"baseline_successes":bs["confirmed_improvements"],"success_count_advantage":success_delta,"required_success_count_advantage":REQUIRED_SUCCESS_COUNT_ADVANTAGE,"advantage_vs_baseline":advantage,"min_rate_advantage":MIN_RATE_ADVANTAGE,"receiver_evaluation_savings_vs_baseline":eval_savings,"paired_counts":counts},
        "arms":{"evidence":es,"baseline":bs},
        "researcher_contact":{"same_selected_set_tasks":same_set,"same_exact_selected_order_tasks":same_order,"tasks":TASKS_TOTAL,"interpretation":"Selection convergence is allowed. If Prince ignores or reconstructs presentation order and the advantage disappears, the negative result stands."},
        "economics":{"hard_incremental_paid_spend_ceiling_usd":str(HARD_SPEND_CEILING_USD),"actual_incremental_paid_spend_usd":str(costs["total"]),"receiver_incremental_paid_usd":str(costs["receiver"]),"other_incremental_paid_usd":str(costs["other"]),"inherited_learning_cost_evaluations":INHERITED_LEARNING_COST_EVALUATIONS,"receiver_evaluation_savings_vs_baseline":eval_savings,"mean_receiver_evaluation_savings_per_task":savings_per_task,"projected_break_even_future_tasks_at_observed_receiver_savings_rate":projected,"learning_cost_recovered_in_this_run":eval_savings>=INHERITED_LEARNING_COST_EVALUATIONS,"economic_payback_claim":"NOT_EARNED"},
        "integrity":{"experiment_head_sha":rmap["experiment_head_sha"],"predecessor_main":PREDECESSOR_MAIN,"predecessor_freeze_blob":PREDECESSOR_FREEZE_BLOB,"exact_policy_seal_sha256":POLICY_SEAL_SHA256,"exact_predecessor_runner_sha256":PREDECESSOR_RUNNER_SHA256,"same_candidate_ids_descriptions_features_history_task_context_tools_limits":True,"only_visible_packet_input_difference":"candidate presentation order","normalized_visible_packet_sha256":rmap["normalized_visible_packet_sha256"],"ordering_sealed_before_task_data_nonce":True,"ordering_seal_sha256":rmap["ordering_seal_sha256"],"task_data_nonce":task_data_nonce,"matched_live_rows_sha256":rows_sha,"paired_outcomes_sha256":pairs_sha,"all_response_orders_valid":True,"budget_record_complete_and_within_ceiling":True},
        "claim_boundary":v["claim_boundary"]
    }
    write_json(output,result); shutil.copy2(output,evidence_dir/"RIL_RANK_LIVE_001_RESULT.json"); write_manifest(evidence_dir)
    return result


def self_check() -> None:
    v=prereg(); verify_predecessor(); verify_frozen_files(v,require_committed=False); engine=load_engine(); policy=read_json(POLICY_PATH); validator=load_validator()
    assert v["design"]["researcher_name"]==RESEARCHER_NAME and v["design"]["researcher_model"]==RESEARCHER_MODEL
    assert v["design"]["required_success_count_advantage"]==2 and v["design"]["tasks_total"]==16
    assert Decimal(v["economics"]["hard_incremental_paid_spend_ceiling_usd"])==HARD_SPEND_CEILING_USD
    nonce="31"*32; data="47"*32; packets=[]
    for arm in ("evidence","baseline"):
        tasks=[]
        for family in engine.FAMILIES:
            cands=engine.generate_candidates(nonce,family,0); tid=f"{family}-000"; order=engine.learned_order(policy["learned_model"],cands) if arm=="evidence" else engine.baseline_order(policy["baseline_order_seed"],tid,cands); by={c["candidate_id"]:c for c in cands}; task=engine.make_task(family,0,data); tasks.append(packet_task(tid,task_public_context(family,task),[by[x] for x in order]))
        packets.append(make_packet(tasks))
    assert_only_candidate_order_differs(packets[0],packets[1])
    p=packets[0]; first=p["tasks"][0]; full=[c["candidate_id"] for c in first["candidate_pool_in_presented_order"]]; chosen=full[-4:]; resp={"experiment":EXPERIMENT,"orders":[{"task_id":t["task_id"],"evaluation_order":[c["candidate_id"] for c in t["candidate_pool_in_presented_order"][-4:]]} for t in p["tasks"]],"tools_used":[]}; ok,orders,issues,_=validator.validate_response(p,resp); assert ok and not issues and orders[first["task_id"]]==chosen
    bad=cost_template();
    for slot in ("session-1","session-2"): bad["sessions"][slot]={"incremental_paid_usd":"1.28","billing_basis":"test","source":"test","complete":True}
    bad["receiver_incremental_paid_usd"]="0.00"; bad["receiver_cost_basis"]="test"; bad["receiver_cost_source"]="test"; bad["other_incremental_paid_usd"]="0.00"; bad["other_cost_basis"]="test"; bad["other_cost_source"]="test"; assert validate_cost_record(bad)["total"]==HARD_SPEND_CEILING_USD
    bad["sessions"]["session-2"]["incremental_paid_usd"]="1.29"
    try: validate_cost_record(bad); raise AssertionError("budget overflow accepted")
    except RuntimeError: pass
    print("RIL-RANK-LIVE-001 Prince matched contact self-check: PASS")


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--self-check",action="store_true"); sub=ap.add_subparsers(dest="cmd")
    p=sub.add_parser("prepare"); p.add_argument("--out-dir",required=True,type=Path)
    s=sub.add_parser("score"); s.add_argument("--prepared-dir",required=True,type=Path); s.add_argument("--session-1-response",required=True,type=Path); s.add_argument("--session-2-response",required=True,type=Path); s.add_argument("--cost-record",required=True,type=Path); s.add_argument("--output",required=True,type=Path); s.add_argument("--evidence-dir",required=True,type=Path)
    a=ap.parse_args()
    if a.self_check: self_check(); return 0
    if a.cmd=="prepare": print(json.dumps(prepare(a.out_dir),indent=2,sort_keys=True)); return 0
    if a.cmd=="score": print(json.dumps(score(a.prepared_dir,a.session_1_response,a.session_2_response,a.cost_record,a.output,a.evidence_dir),indent=2,sort_keys=True)); return 0
    ap.error("use --self-check, prepare, or score"); return 2
if __name__=="__main__": raise SystemExit(main())
