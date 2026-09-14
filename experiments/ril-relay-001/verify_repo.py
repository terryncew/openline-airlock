#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
freeze=ROOT/'proofs/ril-anomaly-002/RIL_ANOMALY_002_FREEZE.json'
iso=ROOT/'proofs/ril-isolation-002/RIL_ISOLATION_002_FREEZE.json'
assert freeze.is_file(), 'ANOMALY-002 freeze missing'
assert sha(freeze)=='3e19d031ee2a98cf55ed31f862b9ad45826588c57642a2edf7750aabb2987ad3', 'ANOMALY-002 freeze hash mismatch'
f=json.loads(freeze.read_text()); assert f['formal_verdict']=='INCONCLUSIVE_RIL_ANOMALY_002_TERMINAL_FAILURE'
assert iso.is_file(), 'ISOLATION-002 freeze missing'
assert sha(iso)=='ce98f84046481f84f6e26a453fbc6f806e690e68f3d5c9bb6c13ae291f0d6285', 'ISOLATION-002 freeze hash mismatch'
print(json.dumps({'verified':True,'anomaly_002_freeze_sha256':sha(freeze),'isolation_002_freeze_sha256':sha(iso)},indent=2))
