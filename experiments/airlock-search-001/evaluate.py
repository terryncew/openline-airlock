#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,importlib.util,json,shutil,subprocess,tempfile
from pathlib import Path
SUBSTRATE="91861c77e4b03ace60df147b0accf94f4351de18"; BASE="baseline_freeform"; MOD={"triage_rank","hypotheses_first","planner_select"}
HASHES={'.airlock/self-001/scope_registry.json': 'f7dce99f85299814cfb2f3c052faf0072075fadf3d1fe40f7660c1e2a483badb', '.airlock/self-001/evaluator.py': '6cb5ea1fc5bf8ffe08ff08add5f9d5f3739cd14227923228482d6604db9179bb', '.airlock/self-001/protected_checks.py': 'b328cd7de7569bb3803690eabc2c9ddbc2d94aae9fae07c4c94776879642698'}
def h(b): return hashlib.sha256(b).hexdigest()
def frozen(repo):
 if subprocess.check_output(['git','rev-parse',SUBSTRATE],cwd=repo,text=True).strip()!=SUBSTRATE: raise RuntimeError('substrate unavailable')
 for rel,exp in HASHES.items():
  if h((repo/rel).read_bytes())!=exp: raise RuntimeError('current frozen selector mismatch '+rel)
  if h(subprocess.check_output(['git','show',f'{SUBSTRATE}:{rel}'],cwd=repo))!=exp: raise RuntimeError('substrate selector mismatch '+rel)
def load(repo):
 p=repo/'.airlock/self-001/evaluator.py'; s=importlib.util.spec_from_file_location('self001eval',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def candidate(repo,patch,cid):
 wt=Path(tempfile.mkdtemp(prefix='search001-eval-')); wt.rmdir(); cp=subprocess.run(['git','worktree','add','--detach',str(wt),SUBSTRATE],cwd=repo,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if cp.returncode: raise RuntimeError(cp.stderr)
 try:
  subprocess.run(['git','config','user.name','SEARCH-001 Evaluator'],cwd=wt,check=True); subprocess.run(['git','config','user.email','eval@invalid.local'],cwd=wt,check=True)
  ap=subprocess.run(['git','apply','--index','--binary','-'],cwd=wt,input=patch,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if ap.returncode: raise ValueError('PATCH_APPLY_FAILED')
  cp=subprocess.run(['git','commit','-m',f'SEARCH-001 candidate {cid}'],cwd=wt,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if cp.returncode: raise ValueError('PATCH_COMMIT_FAILED')
  return wt,subprocess.check_output(['git','rev-parse','HEAD'],cwd=wt,text=True).strip()
 except Exception:
  subprocess.run(['git','worktree','remove','--force',str(wt)],cwd=repo,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); shutil.rmtree(wt,ignore_errors=True); raise
def rm(repo,wt): subprocess.run(['git','worktree','remove','--force',str(wt)],cwd=repo,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); shutil.rmtree(wt,ignore_errors=True)
def bundle(repo,b,e):
 sid=b.get('strategy');
 if sid not in {BASE,*MOD}: raise RuntimeError('unknown strategy')
 if b.get('substrate_commit')!=SUBSTRATE or b.get('model')!='gpt-5.6-sol' or b.get('requested_candidates')!=4: raise RuntimeError('resource/substrate mismatch '+str(sid))
 rows=[]
 for c in b.get('candidates',[]):
  cid=str(c.get('candidate_id') or 'unknown'); patch=c.get('patch') or ''
  if h(patch.encode())!=c.get('patch_sha256'): raise RuntimeError('patch hash mismatch')
  if c.get('disposition')!='SURVIVED' or not patch: rows.append({'candidate_id':cid,'disposition':'INELIGIBLE','reason':c.get('reason') or 'NO_STRUCTURAL_SURVIVOR'}); continue
  wt=None
  try:
   wt,commit=candidate(repo,patch,cid); r=e.evaluate(repo=wt,baseline=SUBSTRATE,candidate=commit); r['candidate_id']=cid; r['patch_sha256']=c.get('patch_sha256'); rows.append(r)
  except ValueError as ex: rows.append({'candidate_id':cid,'disposition':'INELIGIBLE','reason':str(ex)})
  finally:
   if wt is not None: rm(repo,wt)
 return {'strategy':sid,'candidates':rows,'selection':e.select_unique(rows),'tournament':b.get('tournament')}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--repo',default='.'); ap.add_argument('--artifacts'); ap.add_argument('--out'); ap.add_argument('--self-check',action='store_true'); a=ap.parse_args(); repo=Path(a.repo).resolve(); frozen(repo); e=load(repo)
 if a.self_check:
  r=e.selftest();
  if not r.get('pass'): raise RuntimeError('evaluator selftest failed')
  print(json.dumps({'frozen_selector':'PASS','substrate':SUBSTRATE})); return
 files=sorted(Path(a.artifacts).resolve().rglob('bundle.json'))
 if len(files)!=4: raise RuntimeError(f'expected 4 bundles, got {len(files)}')
 seen=set(); results=[]
 for p in files:
  b=json.loads(p.read_text()); sid=b.get('strategy');
  if sid in seen: raise RuntimeError('duplicate strategy '+str(sid))
  seen.add(sid); results.append(bundle(repo,b,e))
 if seen!={BASE,*MOD}: raise RuntimeError('strategy set mismatch')
 by={r['strategy']:r for r in results}; bw=by[BASE]['selection'].get('status')=='UNIQUE_WINNER'; mw=sorted(s for s in MOD if by[s]['selection'].get('status')=='UNIQUE_WINNER')
 if bw: outcome='BASELINE_RECOVERED'; earned=False
 elif mw: outcome='SEARCH_STRATEGY_GAIN'; earned=True
 else: outcome='SEARCH_GAP_PERSISTS'; earned=False
 out={'schema':'airlock.search-001.result.v1','experiment':'AIRLOCK-SEARCH-001','substrate_commit':SUBSTRATE,'outcome':outcome,'earned_label':'SEARCH_STRATEGY_GAIN' if earned else None,'baseline_unique_winner':bw,'modified_unique_winners':mw,'strategy_results':sorted(results,key=lambda x:x['strategy']),'frozen_selector_sha256':HASHES,'claim':'Under the frozen SELF-001 gate and equal resource budget, a preregistered modified autonomous search strategy produced at least one independently admissible improvement that baseline Hermes failed to discover.' if earned else None,'claim_boundary':'Proposal/search strategy varies; the hidden SELF-001 selector was absent from generation jobs and unchanged in evaluation. Fresh-target replication is required before SELF-002 compounding.','next_if_earned':'AIRLOCK-SEARCH-002 fresh-target replication'}
 q=Path(a.out).resolve(); q.parent.mkdir(parents=True,exist_ok=True); q.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps({'outcome':outcome,'modified_unique_winners':mw}))
if __name__=='__main__': main()
