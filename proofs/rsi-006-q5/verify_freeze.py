#!/usr/bin/env python3
"""Proof-integrity self-check for proofs/rsi-006-q5.

Verifies, without touching the runtime durable root:
  1. every file listed in INTEGRITY_MANIFEST.md hashes to its recorded SHA-256;
  2. the copied journal hash chain is continuous (GENESIS -> 196 entries, 0 breaks);
  3. journal event counts match freeze-record.json (1 tx_begin, 1 contact,
     192 observation, 1 restart, 1 observation_adopted);
  4. negative proofs hold: no second tx_begin, no discovery seals, no
     confirmation nonce, no verdict/report entries in the copied journal;
  5. contact marker binds the recorded mutant/ts/receipt;
  6. the two invocation command files are byte-identical;
  7. the frozen spec file still hashes to the value bound in freeze-record.json.

Usage: python3 proofs/rsi-006-q5/verify_freeze.py   (run from repo root)
Exit 0 on full pass, 1 with details on any failure.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root
FREEZE = ROOT / "proofs" / "rsi-006-q5"
failures: list[str] = []


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


# 1. manifest hashes
manifest = (FREEZE / "INTEGRITY_MANIFEST.md").read_text().splitlines()
rows = [l for l in manifest if l.startswith("| proofs/")]
check(len(rows) > 0, "manifest contains no file rows")
for row in rows:
    cols = [c.strip() for c in row.strip().strip("|").split("|")]
    rel, want = cols[0], cols[1]
    p = ROOT / rel
    check(p.is_file(), f"missing file: {rel}")
    if p.is_file():
        check(sha256_file(p) == want, f"hash mismatch: {rel}")

record = json.loads((FREEZE / "freeze-record.json").read_text())

# 2. journal hash chain
jdir = FREEZE / "evidence" / "journal"
jfiles = sorted(jdir.glob("*.json"))
check(len(jfiles) == 196, f"expected 196 journal copies, found {len(jfiles)}")
prev = "GENESIS"
types: dict[str, int] = {}
for f in jfiles:
    d = json.loads(f.read_text())
    check(d.get("prev") == prev, f"chain break at {f.name}")
    prev = d["digest"]
    types[d.get("type")] = types.get(d.get("type"), 0) + 1

# 3. event counts
want_counts = {"tx_begin": 1, "contact": 1, "observation": 192,
               "restart": 1, "observation_adopted": 1}
check(types == want_counts, f"event counts differ: {types} vs {want_counts}")

# 4. negative proofs
check(types.get("seal", 0) == 0, "unexpected discovery seal entries")
check(types.get("confirmation", 0) == 0, "unexpected confirmation entries")
check(types.get("verdict", 0) == 0, "unexpected verdict entries")
check(types.get("report", 0) == 0, "unexpected report entries")
nonces = [f for f in jfiles if "nonce" in json.loads(f.read_text()).get("type", "")]
check(len(nonces) == 0, f"unexpected nonce-bearing entries: {nonces[:3]}")

# 5. contact marker binding
cm = json.loads((FREEZE / "evidence" / "contact-marker.json").read_text())
check(cm["mutant_id"] == record["contact"]["mutant_id"], "contact mutant mismatch")
check(abs(cm["ts"] - record["contact"]["ts"]) < 1e-6, "contact ts mismatch")
check(cm["receipt_sha256"] == record["stage1_receipt_sha256"], "contact receipt mismatch")

# 6. byte-identical invocations
c1 = (FREEZE / "evidence" / "stage2-command.txt").read_bytes()
c2 = (FREEZE / "evidence" / "stage2-resume-command.txt").read_bytes()
check(c1 == c2, "resume command is not byte-identical to original command")

# 7. frozen spec still hashes to the bound value
spec = ROOT / "experiments" / "rsi-006-q5-durable-substrate-qualification" / "RSI_006_Q5_SPEC.md"
check(sha256_file(spec) == record["bound_code"]["q5_spec_sha256"],
      "RSI_006_Q5_SPEC.md no longer hashes to the bound value")

# ledger negative evidence: 0049 has prepared+started, no complete/outcome
ldir = FREEZE / "evidence" / "ledger"
have_0049 = {p.name for p in ldir.glob("cachetools-A-0049.*")}
check(have_0049 == {"cachetools-A-0049.prepared.json", "cachetools-A-0049.started.json"},
      f"0049 ledger copies wrong: {sorted(have_0049)}")
have_0048 = {p.name for p in ldir.glob("cachetools-A-0048.*")}
check(have_0048 == {"cachetools-A-0048.prepared.json", "cachetools-A-0048.started.json",
                    "cachetools-A-0048.complete.json", "cachetools-A-0048.outcome.json"},
      f"0048 ledger copies wrong: {sorted(have_0048)}")

if failures:
    print("FREEZE VERIFICATION FAILED:")
    for f_ in failures:
        print(" -", f_)
    sys.exit(1)
print(f"FREEZE VERIFIED: {len(rows)} files hashed, journal chain intact "
      f"({len(jfiles)} entries), counts {types}")
