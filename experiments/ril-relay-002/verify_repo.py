#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
freeze=ROOT/'proofs/ril-relay-001/RIL_RELAY_001_FREEZE.json'
assert freeze.is_file(), 'RELAY-001 freeze missing'
assert sha(freeze)=='d2bc80967450e12da848577b5eb4e1fce1085bd7b8673aaf7d7f847331bfd0de', 'RELAY-001 freeze hash mismatch'
f=json.loads(freeze.read_text())
assert f['formal_verdict']=='INCONCLUSIVE_RIL_RELAY_001_TERMINAL_FAILURE'
assert f['terminal_failure']=='GEMINI_EGRESS_ERR_EMPTY_RESPONSE_BEFORE_TRIAL_1'
print(json.dumps({"verified":True,"relay_001_freeze_sha256":sha(freeze)},indent=2))
