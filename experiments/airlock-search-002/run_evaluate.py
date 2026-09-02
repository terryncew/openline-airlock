#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, shutil, subprocess, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SUB=ROOT/"experiments/airlock-search-002/substrate"
ORACLE=ROOT/".airlock/search-002/oracle.py"

def sh(cmd,cwd,input_text=None):
    return subprocess.run(cmd,cwd=cwd,text=True,input=input_text,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)

def load_oracle():
    spec=importlib.util.spec_from_file_location("search002_oracle_eval",ORACLE)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def materialize(patch:str):
    td=Path(tempfile.mkdtemp(prefix="search002-eval-")); repo=td/"repo"; shutil.copytree(SUB,repo)
    sh(["git","init"],repo); sh(["git","config","user.name","SEARCH-002 Evaluator"],repo); sh(["git","config","user.email","eval@invalid.local"],repo)
    sh(["git","add","-A"],repo); sh(["git","commit","-m","baseline"],repo)
    cp=sh(["git","apply","--index","--binary","-"],repo,input_text=patch)
    if cp.returncode:
        shutil.rmtree(td,ignore_errors=True); raise ValueError("PATCH_APPLY_FAILED")
    return repo

def eval_arm(bundle,baseline_state,oracle):
    discovered=set(); rows=[]
    for row in bundle.get("rows",[]):
        cid=row.get("candidate_id")
        if row.get("prefilter")!="PASS":
            rows.append({"candidate_id":cid,"status":"REJECT","reason":row.get("prefilter"),"gains":[]}); continue
        patch=row.get("patch") or ""
        if not patch:
            rows.append({"candidate_id":cid,"status":"REJECT","reason":"NO_PATCH","gains":[]}); continue
        repo=None
        try:
            repo=materialize(patch)
            if sh(["python","public_checks.py"],repo).returncode!=0:
                rows.append({"candidate_id":cid,"status":"REJECT","reason":"PUBLIC_CHECK_REGRESSION","gains":[]}); continue
            state=oracle.assess(repo)
            gains=sorted(k for k,v in state.items() if v and not baseline_state.get(k,False))
            discovered.update(gains)
            rows.append({"candidate_id":cid,"status":"ACCEPTED_VALUE" if gains else "NO_SCORE_GAIN","reason":None if gains else "NO_SCORE_GAIN","gains":gains,"diff":row.get("diff"),"plan":row.get("plan")})
        except ValueError as exc:
            rows.append({"candidate_id":cid,"status":"REJECT","reason":str(exc),"gains":[]})
        finally:
            if repo is not None: shutil.rmtree(repo.parent,ignore_errors=True)
    return {"strategy":bundle["strategy"],"unique_dimensions":sorted(discovered),"unique_count":len(discovered),"candidate_rows":rows}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--baseline-bundle",required=True); ap.add_argument("--outcome-bundle",required=True); ap.add_argument("--out",required=True); args=ap.parse_args()
    b=json.loads(Path(args.baseline_bundle).read_text()); o=json.loads(Path(args.outcome_bundle).read_text())
    for bundle,strategy in ((b,"baseline"),(o,"outcome_trace")):
        if bundle.get("schema")!="airlock.search-002.bundle.v1" or bundle.get("strategy")!=strategy or bundle.get("model")!="gpt-5.6-sol" or bundle.get("candidates")!=4 or bundle.get("max_turns_per_candidate")!=90:
            raise RuntimeError(f"bundle boundary mismatch: {strategy}")
    oracle=load_oracle(); baseline_state=oracle.assess(SUB)
    if any(baseline_state.values()): raise RuntimeError("starting substrate already scores")
    baseline=eval_arm(b,baseline_state,oracle); outcome=eval_arm(o,baseline_state,oracle); margin=outcome["unique_count"]-baseline["unique_count"]
    if outcome["unique_count"]>=2 and margin>=2: verdict="SEARCH_STRATEGY_GAIN"; earned=True
    elif baseline["unique_count"]==0 and outcome["unique_count"]==0: verdict="DISCOVERY_SEARCH_DEFICIT"; earned=False
    elif outcome["unique_count"]<=baseline["unique_count"]: verdict="OUTCOME_TRACE_NO_GAIN"; earned=False
    else: verdict="INSUFFICIENT_SEARCH_GAIN"; earned=False
    result={
      "schema":"airlock.search-002.result.v1","experiment":"AIRLOCK-SEARCH-002","verdict":verdict,"earned":earned,
      "primary_endpoint":{"baseline_unique_score_dimensions":baseline["unique_count"],"outcome_trace_unique_score_dimensions":outcome["unique_count"],"margin":margin,"required_outcome_trace_minimum":2,"required_margin":2},
      "baseline":baseline,"outcome_trace":outcome,
      "claim":"Outcome Trace improved more independently scored public outcomes than baseline under the preregistered equal budget." if earned else None,
      "claim_boundary":"The scorecard was visible to both arms and protected from modification. The external evaluator independently executed the public scorecard consequences. Searchers could optimize against the scoreboard but could not rewrite it.",
      "next_if_earned":"Fresh-substrate replication before self-compounding."
    }
    out=Path(args.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\\n")
    print(json.dumps({"verdict":verdict,"baseline":baseline["unique_count"],"outcome_trace":outcome["unique_count"],"margin":margin}))
    return 0
if __name__=="__main__": raise SystemExit(main())
