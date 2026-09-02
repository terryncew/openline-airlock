#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, tempfile
from pathlib import Path

def load(repo: Path, module: str):
    path = repo/"maintbox"/f"{module}.py"
    spec = importlib.util.spec_from_file_location(f"search002_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def assess(repo: Path) -> dict[str,bool]:
    objectives=load(repo,"objectives"); queue=load(repo,"queue"); inbox=load(repo,"inbox")
    gitview=load(repo,"gitview"); names=load(repo,"names"); retry=load(repo,"retry")
    paths=load(repo,"paths"); chunks_mod=load(repo,"chunks")
    out={}
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        missing=td/"missing.json"; missing.write_text(json.dumps({"meta":1}))
        blank=td/"blank.json"; blank.write_text(json.dumps({"goal":""}))
        valid=td/"valid.json"; valid.write_text(json.dumps({"goal":"ship","meta":1}))
        a=b=False
        try: objectives.load_objective(missing)
        except ValueError: a=True
        try: objectives.load_objective(blank)
        except ValueError: b=True
        try: c=objectives.load_objective(valid)["goal"]=="ship"
        except Exception: c=False
        out["objective_required_goal"]=a and b and c

        ib=td/"inbox.jsonl"; ib.write_text('{"id":1}\nBROKEN\n{"id":2}\n')
        try: out["inbox_malformed_line"]=[r.get("id") for r in inbox.read_inbox(ib)]==[1,2]
        except Exception: out["inbox_malformed_line"]=False

    class Counting:
        def __init__(self):
            self.count=0
            self.rows=[{"id":1,"ready":False},{"id":2,"ready":False},{"id":3,"ready":True},{"id":4,"ready":True}]
        def __iter__(self):
            for row in self.rows:
                self.count+=1
                yield row
    items=Counting()
    try:
        found=queue.first_ready(items)
        out["queue_short_circuit"]=found=={"id":3,"ready":True} and items.count==3
    except Exception: out["queue_short_circuit"]=False

    state={"calls":0}
    def provider():
        state["calls"]+=1
        return {"branch":"main","dirty":True}
    try:
        snap=gitview.git_snapshot(provider)
        out["git_snapshot_single_query"]=snap=={"branch":"main","dirty":True} and state["calls"]==1
    except Exception: out["git_snapshot_single_query"]=False

    try: out["slug_empty_fallback"]=names.slugify("!!!")=="item" and names.slugify("Hello World")=="hello-world"
    except Exception: out["slug_empty_fallback"]=False
    try: out["retry_zero_attempts"]=retry.retry_delays(0)==[] and retry.retry_delays(2)==[0.5,1.0]
    except Exception: out["retry_zero_attempts"]=False
    try: out["dedupe_first_seen_order"]=paths.dedupe_paths(["b","a","b","c","a"])==["b","a","c"]
    except Exception: out["dedupe_first_seen_order"]=False
    try:
        out["chunks_keep_partial"]=chunks_mod.chunks([1,2,3,4,5],2)==[[1,2],[3,4],[5]] and chunks_mod.chunks([],2)==[]
    except Exception: out["chunks_keep_partial"]=False
    return out

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo",required=True); args=ap.parse_args()
    result=assess(Path(args.repo).resolve())
    print(json.dumps({"schema":"airlock.search002.oracle.v1","dimensions":result,"passed_count":sum(result.values())},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
