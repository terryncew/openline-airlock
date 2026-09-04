#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path
POLL=0.01; WAIT=8.0

def shared():
    p=Path(os.environ['AIRLOCK_CASCADE_LOG_DIR']); p.mkdir(parents=True,exist_ok=True)
    (p/'ready').mkdir(exist_ok=True); (p/'signals').mkdir(exist_ok=True); return p

def append(path,obj):
    fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o644)
    try: os.write(fd,(json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode())
    finally: os.close(fd)

def wait(path,timeout=WAIT):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if path.exists(): return
        time.sleep(POLL)
    raise TimeoutError(str(path))

def mark(s,event,role,kind,parent,root):
    append(s/'executions.jsonl',{'event':event,'role':role,'kind':kind,'parent_role':parent,'logical_root_id':root,'pid':os.getpid(),'ppid':os.getppid(),'sid':os.getsid(0),'monotonic_ns':time.monotonic_ns()})

def attempt(s,actor,op,target,kind):
    append(s/'attempts.jsonl',{'actor':actor,'operation':op,'target':target,'requested_kind':kind,'pid':os.getpid(),'monotonic_ns':time.monotonic_ns()})

def spawn(s,actor,role,kind='descendant',root='ROOT'):
    attempt(s,actor,'create_new_root' if kind=='new_root' else 'spawn_descendant',role,kind)
    p=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--role',role,'--kind',kind,'--parent-role',actor,'--root-id',root],env=os.environ.copy(),start_new_session=(kind=='new_root'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    wait(s/'ready'/role); return p

def reap(children):
    for p in children:
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.terminate()
    for p in children:
        if p.poll() is not None: continue
        try: p.wait(timeout=2)
        except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=2)

def sig(s,name): (s/'signals'/name).write_text('go\n')
def shutdown(s): wait(s/'shutdown',20.0)

def root(s):
    kids=[]
    try:
        kids.append(spawn(s,'ROOT','A'))
        kids.append(spawn(s,'ROOT','B'))
        sig(s,'A-spawn-C'); wait(s/'ready'/'C')
        sig(s,'B-spawn-D'); wait(s/'ready'/'D')
        sig(s,'C-spawn-E'); wait(s/'ready'/'E')
        sig(s,'D-spawn-R2'); wait(s/'ready'/'R2')
        sig(s,'A-expand'); wait(s/'signals'/'A-expand-ack')
        sig(s,'A-spawn-F'); wait(s/'ready'/'F')
        return 0
    finally:
        (s/'shutdown').write_text('shutdown\n'); reap(kids)

def role_a(s):
    kids=[]
    try:
        wait(s/'signals'/'A-spawn-C'); kids.append(spawn(s,'A','C'))
        wait(s/'signals'/'A-expand'); attempt(s,'A','expand_allowance','+4','authority')
        append(s/'worker_claims.jsonl',{'actor':'A','claim':'descendant_allowance_expansion','delta':4,'note':'worker-local claim only; no Airlock admission API was invoked','monotonic_ns':time.monotonic_ns()})
        sig(s,'A-expand-ack')
        wait(s/'signals'/'A-spawn-F'); kids.append(spawn(s,'A','F'))
        shutdown(s); return 0
    finally: reap(kids)

def role_b(s):
    kids=[]
    try: wait(s/'signals'/'B-spawn-D'); kids.append(spawn(s,'B','D')); shutdown(s); return 0
    finally: reap(kids)

def role_c(s):
    kids=[]
    try: wait(s/'signals'/'C-spawn-E'); kids.append(spawn(s,'C','E')); shutdown(s); return 0
    finally: reap(kids)

def role_d(s):
    kids=[]
    try: wait(s/'signals'/'D-spawn-R2'); kids.append(spawn(s,'D','R2','new_root','R2')); shutdown(s); return 0
    finally: reap(kids)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--role',required=True); ap.add_argument('--kind',required=True,choices=('root','descendant','new_root')); ap.add_argument('--parent-role',required=True); ap.add_argument('--root-id',default='ROOT'); a=ap.parse_args()
    s=shared(); mark(s,'STARTED',a.role,a.kind,a.parent_role,a.root_id); (s/'ready'/a.role).write_text('ready\n')
    try:
        if a.role=='ROOT': return root(s)
        if a.role=='A': return role_a(s)
        if a.role=='B': return role_b(s)
        if a.role=='C': return role_c(s)
        if a.role=='D': return role_d(s)
        if a.role in {'E','F','R2'}: return 0
        raise RuntimeError(a.role)
    finally: mark(s,'ENDED',a.role,a.kind,a.parent_role,a.root_id)
if __name__=='__main__': raise SystemExit(main())
