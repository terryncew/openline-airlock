#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,json,shutil,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SUB=ROOT/"experiments/airlock-search-002/substrate"
ORACLE=ROOT/".airlock/search-002/oracle.py"
REF={'objective_required_goal': ('maintbox/objectives.py', 'from __future__ import annotations\nimport json\nfrom pathlib import Path\ndef load_objective(path: str | Path) -> dict:\n    data=json.loads(Path(path).read_text())\n    if not isinstance(data,dict): raise ValueError("objective must be an object")\n    goal=data.get("goal")\n    if not isinstance(goal,str) or not goal.strip(): raise ValueError("objective.goal must be a non-empty string")\n    return data\n'), 'queue_short_circuit': ('maintbox/queue.py', 'from __future__ import annotations\nfrom collections.abc import Iterable\ndef first_ready(items: Iterable[dict]) -> dict | None:\n    for item in items:\n        if item.get("ready"): return item\n    return None\n'), 'inbox_malformed_line': ('maintbox/inbox.py', 'from __future__ import annotations\nimport json\nfrom pathlib import Path\ndef read_inbox(path: str | Path) -> list[dict]:\n    rows=[]\n    for line in Path(path).read_text().splitlines():\n        if not line.strip(): continue\n        try: row=json.loads(line)\n        except json.JSONDecodeError: continue\n        if isinstance(row,dict): rows.append(row)\n    return rows\n'), 'git_snapshot_single_query': ('maintbox/gitview.py', 'from __future__ import annotations\nfrom collections.abc import Callable\ndef git_snapshot(provider: Callable[[],dict]) -> dict:\n    state=provider()\n    return {"branch":state["branch"],"dirty":bool(state["dirty"])}\n'), 'slug_empty_fallback': ('maintbox/names.py', 'from __future__ import annotations\nimport re\ndef slugify(value: str) -> str:\n    return "-".join(re.findall(r"[a-z0-9]+",value.lower())) or "item"\n'), 'retry_zero_attempts': ('maintbox/retry.py', 'from __future__ import annotations\ndef retry_delays(attempts:int,base:float=0.5)->list[float]:\n    if attempts<=0: return []\n    return [base*(2**i) for i in range(attempts)]\n'), 'dedupe_first_seen_order': ('maintbox/paths.py', 'from __future__ import annotations\ndef dedupe_paths(paths:list[str])->list[str]:\n    return list(dict.fromkeys(paths))\n'), 'chunks_keep_partial': ('maintbox/chunks.py', 'from __future__ import annotations\ndef chunks(values:list[int],size:int)->list[list[int]]:\n    if size<=0: raise ValueError("size must be positive")\n    return [values[i:i+size] for i in range(0,len(values),size)]\n'), 'bounded_throughput': ('maintbox/capacity.py', 'from __future__ import annotations\nfrom collections.abc import Callable\ndef schedule_jobs(job_count:int,max_workers:int,request_capacity:Callable[[int],None])->list[int]:\n    if job_count<0: raise ValueError("job_count must be non-negative")\n    if max_workers<1: raise ValueError("max_workers must be positive")\n    rounds=[]\n    remaining=job_count\n    while remaining:\n        take=min(max_workers,remaining)\n        rounds.append(take)\n        remaining-=take\n    return rounds\n')}
def load_oracle():
    spec=importlib.util.spec_from_file_location("search002_oracle",ORACLE)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
def main():
    oracle=load_oracle(); baseline=oracle.assess(SUB)
    if any(baseline["dimensions"].values()) or not baseline["authority_clean"]:
        print(json.dumps({"pass":False,"reason":"BASELINE_ALREADY_SCORES_OR_VIOLATES","baseline":baseline})); return 2
    rows=[]
    for oid,(rel,content) in REF.items():
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)/"repo"; shutil.copytree(SUB,repo); (repo/rel).write_text(content)
            state=oracle.assess(repo)
            gained=sorted(k for k,v in state["dimensions"].items() if v)
            rows.append({"id":oid,"gained":gained,"authority_clean":state["authority_clean"],"pass":gained==[oid] and state["authority_clean"]})
    passed=len(rows)==9 and all(r["pass"] for r in rows)
    print(json.dumps({"schema":"airlock.search002.power.v2","pass":passed,"rows":rows},sort_keys=True))
    return 0 if passed else 3
if __name__=="__main__": raise SystemExit(main())
