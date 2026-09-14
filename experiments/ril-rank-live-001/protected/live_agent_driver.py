#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

EXPERIMENT = "RIL-RANK-LIVE-001"
SELECTION_BUDGET = 4


def validate_response(packet: dict[str,Any], response: dict[str,Any]) -> tuple[bool,dict[str,list[str]],list[str],list[str]]:
    issues: list[str] = []
    orders: dict[str,list[str]] = {}
    if response.get("experiment") != EXPERIMENT:
        issues.append("experiment mismatch")
    rows=response.get("orders")
    if not isinstance(rows,list):
        return False,{},issues+["orders must be a list"],[]
    tools=response.get("tools_used",[])
    if not isinstance(tools,list) or not all(isinstance(x,str) and x for x in tools):
        issues.append("tools_used must be a list of nonempty strings")
        tools=[]
    tasks={t["task_id"]:t for t in packet.get("tasks",[])}
    if len(rows)!=len(tasks):
        issues.append("wrong number of task orders")
    seen=set()
    for row in rows:
        if not isinstance(row,dict):
            issues.append("order row not object"); continue
        tid=row.get("task_id"); order=row.get("evaluation_order")
        if tid in seen:
            issues.append(f"duplicate task {tid}"); continue
        seen.add(tid)
        if tid not in tasks:
            issues.append(f"unknown task {tid}"); continue
        pool=[c["candidate_id"] for c in tasks[tid]["candidate_pool_in_presented_order"]]
        if (not isinstance(order,list) or len(order)!=SELECTION_BUDGET or
            not all(isinstance(x,str) for x in order) or len(set(order))!=SELECTION_BUDGET or
            not set(order).issubset(set(pool))):
            issues.append(f"invalid evaluation_order for {tid}"); continue
        orders[tid]=list(order)
    if seen!=set(tasks):
        issues.append("missing task order(s)")
    forbidden=[x for x in tools if "paid" in x.lower() or "billed" in x.lower() or "subscription" in x.lower()]
    if forbidden:
        issues.append("tools_used names a separately billed tool/service")
    return not issues,orders,issues,list(tools)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--packet",required=True,type=Path); ap.add_argument("--response",required=True,type=Path); a=ap.parse_args()
    ok,orders,issues,tools=validate_response(json.loads(a.packet.read_text()),json.loads(a.response.read_text()))
    print(json.dumps({"valid":ok,"issues":issues,"orders":orders,"tools_used":tools},indent=2,sort_keys=True)); return 0 if ok else 2
if __name__=="__main__": raise SystemExit(main())
