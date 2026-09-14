#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EXPERIMENT = "RIL-RANK-LIVE-002"
SELECTION_BUDGET = 4
ALLOWED_TOOLS = {"Muse conversational reasoning","Muse Linux VM shell/filesystem","Muse browser/internet","RunPod GPU"}


def _dec(v: Any) -> Decimal | None:
    try: return Decimal(str(v))
    except (InvalidOperation,ValueError,TypeError): return None


def validate_response(packet: dict[str,Any], response: dict[str,Any]) -> tuple[bool,dict[str,list[str]],list[str],list[str],dict[str,Any]]:
    issues: list[str] = []
    orders: dict[str,list[str]] = {}
    if response.get("experiment") != EXPERIMENT:
        issues.append("experiment mismatch")
    rows=response.get("orders")
    if not isinstance(rows,list):
        return False,{},issues+["orders must be a list"],[],{}
    tools=response.get("tools_used",[])
    if not isinstance(tools,list) or not all(isinstance(x,str) and x for x in tools):
        issues.append("tools_used must be a list of nonempty strings"); tools=[]
    else:
        unknown=[x for x in tools if x not in ALLOWED_TOOLS]
        if unknown: issues.append(f"unapproved tool(s): {unknown}")
    tasks={t["task_id"]:t for t in packet.get("tasks",[])}
    if len(rows)!=len(tasks): issues.append("wrong number of task orders")
    seen=set()
    for row in rows:
        if not isinstance(row,dict): issues.append("order row not object"); continue
        tid=row.get("task_id"); order=row.get("evaluation_order")
        if tid in seen: issues.append(f"duplicate task {tid}"); continue
        seen.add(tid)
        if tid not in tasks: issues.append(f"unknown task {tid}"); continue
        pool=[c["candidate_id"] for c in tasks[tid]["candidate_pool_in_presented_order"]]
        if (not isinstance(order,list) or len(order)!=SELECTION_BUDGET or
            not all(isinstance(x,str) for x in order) or len(set(order))!=SELECTION_BUDGET or
            not set(order).issubset(set(pool))):
            issues.append(f"invalid evaluation_order for {tid}"); continue
        orders[tid]=list(order)
    if seen!=set(tasks): issues.append("missing task order(s)")

    gpu=response.get("gpu_usage")
    if not isinstance(gpu,dict):
        issues.append("gpu_usage must be an object"); gpu={}
    contract=packet.get("gpu_contract",{})
    used=gpu.get("used")
    if not isinstance(used,bool): issues.append("gpu_usage.used must be boolean")
    if gpu.get("provider")!="RunPod": issues.append("gpu provider mismatch")
    if gpu.get("gpu_sku")!=contract.get("gpu_sku"): issues.append("gpu sku mismatch")
    rate=_dec(gpu.get("quoted_hourly_rate_usd")); contract_rate=_dec(contract.get("quoted_hourly_rate_usd"))
    if rate is None or contract_rate is None or rate!=contract_rate: issues.append("gpu hourly rate mismatch")
    runtime=gpu.get("runtime_seconds"); wall=gpu.get("session_wall_seconds")
    if not isinstance(runtime,int) or runtime<0: issues.append("runtime_seconds must be nonnegative integer")
    if not isinstance(wall,int) or wall<0: issues.append("session_wall_seconds must be nonnegative integer")
    if isinstance(runtime,int) and isinstance(wall,int) and wall<runtime: issues.append("session wall time shorter than GPU runtime")
    max_runtime=contract.get("max_gpu_runtime_seconds_per_session")
    if isinstance(runtime,int) and isinstance(max_runtime,int) and runtime>max_runtime: issues.append("gpu runtime exceeded frozen stopping limit")
    if used is True:
        if "RunPod GPU" not in tools: issues.append("gpu marked used but RunPod GPU missing from tools_used")
        for k in ("pod_id","start_utc","stop_utc"):
            if not str(gpu.get(k) or "").strip(): issues.append(f"gpu usage missing {k}")
        if runtime == 0: issues.append("gpu marked used with zero runtime")
    if used is False:
        if runtime not in (0,None): issues.append("gpu marked unused with nonzero runtime")
        if "RunPod GPU" in tools: issues.append("RunPod GPU named in tools_used while gpu_usage.used=false")
    prs=gpu.get("provider_reported_spend_usd")
    if prs is not None:
        d=_dec(prs)
        if d is None or d<0: issues.append("invalid provider_reported_spend_usd")
    return not issues,orders,issues,list(tools),dict(gpu)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--packet",required=True,type=Path); ap.add_argument("--response",required=True,type=Path); a=ap.parse_args()
    ok,orders,issues,tools,gpu=validate_response(json.loads(a.packet.read_text()),json.loads(a.response.read_text()))
    print(json.dumps({"valid":ok,"issues":issues,"orders":orders,"tools_used":tools,"gpu_usage":gpu},indent=2,sort_keys=True)); return 0 if ok else 2
if __name__=="__main__": raise SystemExit(main())
