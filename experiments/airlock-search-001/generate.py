#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess,tarfile,tempfile,io
from pathlib import Path
from airlock.runner import run_tournament
SUBSTRATE="91861c77e4b03ace60df147b0accf94f4351de18"; MODEL="gpt-5.6-sol"; CANDIDATES=4
STRATEGIES={'baseline_freeform': 'Improve this repository. Find the highest-value small, reversible change you can justify. You choose the problem and the implementation. The independent selector—not you—decides whether anything earns admission.', 'triage_rank': 'Improve this repository. Before editing, inspect the repository broadly and identify several plausible small, reversible improvements. Rank them using only evidence available in the repository: expected user or engineering value, confidence, reversibility, implementation size, and regression risk. Choose the highest-return candidate, then implement it. You choose the problem and implementation. The independent selector—not you—decides whether anything earns admission.', 'hypotheses_first': 'Improve this repository. Before editing, generate at least six concrete improvement hypotheses from the code, public checks, documentation, and repository structure. Falsify weak hypotheses cheaply, compare the survivors, and implement one small, reversible change with the strongest evidence of useful gain. You choose the problem and implementation. The independent selector—not you—decides whether anything earns admission.', 'planner_select': 'Improve this repository. First perform a read-only survey of the codebase and public checks. Form at least three candidate interventions, compare their likely value, evidence, size, reversibility, and regression risk, then implement the smallest intervention with the strongest expected return. You choose the problem and implementation. The independent selector—not you—decides whether anything earns admission.'}
HIDDEN=[".airlock/self-001/evaluator.py",".airlock/self-001/scope_registry.json",".airlock/self-001/preregistration.json",".airlock/self-001/fixtures","experiments/airlock-self-001"]
PUBLIC={"schema":"airlock.config.v1","parallelism":4,"providers":{"hermes":{"command":["python",".airlock/checks/hermes_live_001_worker.py","{prompt}"],"pass_env":["HERMES_HOME"],"timeout_seconds":2700}},"protected_paths":[".github/workflows/**",".airlock/**","tests/**","scripts/verify_*","pyproject.toml","CHANGELOG.md"],"baseline":{"check_commands":[["python",".airlock/self-001/protected_checks.py"]],"timeout_seconds":1200},"verification":{"target_commands":[],"static_commands":[],"test_commands":[["python",".airlock/self-001/protected_checks.py"]],"timeout_seconds":1200}}
def sh(cmd,cwd,text=True):
 return subprocess.run(cmd,cwd=cwd,text=text,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--source-repo',default='.'); ap.add_argument('--strategy',required=True,choices=sorted(STRATEGIES)); ap.add_argument('--out',required=True); a=ap.parse_args(); src=Path(a.source_repo).resolve(); out=Path(a.out).resolve(); out.parent.mkdir(parents=True,exist_ok=True)
 if subprocess.check_output(['git','rev-parse',SUBSTRATE],cwd=src,text=True).strip()!=SUBSTRATE: raise RuntimeError('pinned substrate unavailable')
 tmp=Path(tempfile.mkdtemp(prefix='search001-')); repo=tmp/'repo'; repo.mkdir()
 try:
  arc=subprocess.check_output(['git','archive','--format=tar',SUBSTRATE],cwd=src)
  with tarfile.open(fileobj=io.BytesIO(arc),mode='r:') as tf: tf.extractall(repo)
  for rel in HIDDEN:
   p=repo/rel
   if p.is_dir(): shutil.rmtree(p)
   elif p.exists(): p.unlink()
  if any((repo/r).exists() for r in HIDDEN): raise RuntimeError('hidden evaluator leaked into worker repo')
  cfg=repo/'.airlock/search-public-config.json'; cfg.parent.mkdir(parents=True,exist_ok=True); cfg.write_text(json.dumps(PUBLIC,indent=2)+'\n')
  sh(['git','init'],repo); sh(['git','config','user.name','SEARCH-001'],repo); sh(['git','config','user.email','search001@invalid.local'],repo); sh(['git','add','-A'],repo); cp=sh(['git','commit','-m','SEARCH-001 sanitized substrate'],repo)
  if cp.returncode: raise RuntimeError(cp.stderr)
  base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
  rep=run_tournament(repo,STRATEGIES[a.strategy],agents=CANDIDATES,models=[MODEL]*CANDIDATES,budget=None,open_pr=False,config_path=cfg)
  rows=[]
  for r in rep.get('candidates',[]):
   c=r.get('commit'); patch=''
   if isinstance(c,str) and c and c!=base:
    d=sh(['git','diff','--binary','--full-index',f'{base}..{c}','--','.'],repo); patch=d.stdout if d.returncode==0 else ''
   rows.append({'candidate_id':r.get('candidate_id'),'model':r.get('model'),'disposition':r.get('disposition'),'reason':r.get('reason'),'changed_paths':r.get('changed_paths',[]),'patch':patch,'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'agent_execution':r.get('agent_execution'),'agent_report':r.get('agent_report',{}),'checks':r.get('checks',[])})
  payload={'schema':'airlock.search-001.candidate-bundle.v1','strategy':a.strategy,'substrate_commit':SUBSTRATE,'model':MODEL,'requested_candidates':CANDIDATES,'prompt_sha256':hashlib.sha256(STRATEGIES[a.strategy].encode()).hexdigest(),'hidden_paths_absent':HIDDEN,'tournament':{'run_id':rep.get('run_id'),'status':rep.get('status'),'survivor_count':rep.get('survivor_count'),'reported_cost':rep.get('cost'),'elapsed_seconds':rep.get('elapsed_seconds')},'candidates':rows}
  out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n'); print(json.dumps({'strategy':a.strategy,'candidates':len(rows),'survivors':sum(x.get('disposition')=='SURVIVED' for x in rows)}))
 finally: shutil.rmtree(tmp,ignore_errors=True)
if __name__=='__main__': main()
