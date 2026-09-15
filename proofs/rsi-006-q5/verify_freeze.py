#!/usr/bin/env python3
"""Proof-integrity self-check for proofs/rsi-006-q5.

Verifies, without touching the runtime durable root or executing Q5:

A. EXACT MANIFEST INVENTORY (repair 2)
   - every manifest path is unique; duplicate rows fail
   - every listed path resolves beneath proofs/rsi-006-q5/
   - every listed file exists, is a regular file (no symlinks), hashes match
   - the actual set of regular freeze files equals the manifest set exactly,
     with the single explicit exception INTEGRITY_MANIFEST.md
     (the manifest cannot hash itself)
   - any unlisted extra file, any missing file, any omitted file fails

B. FULL JOURNAL DIGEST VERIFICATION (repair 1)
   For every copied journal entry (196), using the exact frozen Q4
   canonicalization from
   experiments/rsi-006-q4-durable-transaction/stransaction.py:
       canonical_bytes(obj) = json.dumps(obj, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")
       digest = sha256(canonical_bytes({"seq","prev","type","payload","ts"}))
   - require the expected fields (exactly seq/prev/type/payload/ts/digest)
   - require sequential seq from 1
   - require prev == prior recomputed digest (GENESIS for entry 1)
   - recompute each entry's own digest and require equality
   - only then advance the chain
   A mutation self-test (in-memory only) proves payload/timestamp
   tampering is caught by recomputation.

C. ORPHAN / EVIDENCE BINDING VERIFICATION (repair 3)
   For cachetools-A-0048, from copied bytes only:
   - txid / receipt / code-hash bindings against the tx-begin entry
   - observation / phase / schema / attempt bindings on all four records
   - sha256(exact copied outcome bytes) == completion outcome_digest
   - completion outcome_digest == adopted journal payload digest
   - evidence_digest and launch_digest recomputed per the frozen Q4
     adoption contract and required to equal the journal payload values
   For cachetools-A-0049: prepared+started bindings verified; the absence
   of complete/outcome in the runtime directory is NOT independently
   established from the freeze (see claim categories below).

D. CARRIED-OVER BINDINGS
   - contact marker binds mutant/ts/receipt
   - the two invocation command files are byte-identical
   - RSI_006_Q5_SPEC.md still hashes to the bound value

E. CLAIM CATEGORIES (printed on success)
   A. independently verified from frozen bytes
   B. recorded at capture time (operator/protocol observations, not
      independently re-verifiable from the freeze)

Usage: python3 proofs/rsi-006-q5/verify_freeze.py   (run from repo root)
Exit 0 on full pass, 1 with details on any failure.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]  # repo root
FREEZE = ROOT / "proofs" / "rsi-006-q5"
FREEZE_REL = PurePosixPath("proofs/rsi-006-q5")
MANIFEST_NAME = "INTEGRITY_MANIFEST.md"

failures: list[str] = []
notes: list[str] = []  # informational, not failures


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_bytes(obj: dict) -> bytes:
    # Exact frozen Q4 rule (stransaction.canonical_bytes).
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- A. manifest
manifest_text = (FREEZE / MANIFEST_NAME).read_text().splitlines()
rows = [l for l in manifest_text if l.startswith("| proofs/")]
check(len(rows) > 0, "manifest contains no file rows")

seen: dict[str, str] = {}
for row in rows:
    cols = [c.strip() for c in row.strip().strip("|").split("|")]
    rel, want = cols[0], cols[1]
    check(rel not in seen, f"duplicate manifest row: {rel}")
    seen[rel] = want
    pp = PurePosixPath(rel)
    check(not pp.is_absolute() and ".." not in pp.parts,
          f"manifest path escapes freeze dir: {rel}")
    check(pp == FREEZE_REL / pp.relative_to(FREEZE_REL),
          f"manifest path not beneath {FREEZE_REL}: {rel}")
    p = ROOT / rel
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        check(False, f"manifest file missing: {rel}")
        continue
    check(stat.S_ISREG(st.st_mode), f"not a regular file: {rel}")
    check(not os.path.islink(p), f"symlink not allowed: {rel}")
    if stat.S_ISREG(st.st_mode):
        check(sha256_file(p) == want, f"hash mismatch: {rel}")

actual: set[str] = set()
for dirpath, dirnames, filenames in os.walk(FREEZE):
    for name in filenames:
        p = Path(dirpath) / name
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or os.path.islink(p):
            check(False, f"non-regular file or symlink in freeze: "
                         f"{p.relative_to(ROOT).as_posix()}")
            continue
        actual.add(p.relative_to(ROOT).as_posix())
expected = set(seen) | {f"{FREEZE_REL}/{MANIFEST_NAME}"}
check(actual == expected,
      f"manifest inventory mismatch: extra={sorted(actual - expected)[:5]} "
      f"missing={sorted(expected - actual)[:5]}")

record = json.loads((FREEZE / "freeze-record.json").read_text())

# ---------------------------------------------------------------- B. journal
JDIR = FREEZE / "evidence" / "journal"
jfiles = sorted(JDIR.glob("*.json"))
check(len(jfiles) == 196, f"expected 196 journal copies, found {len(jfiles)}")
EXPECTED_FIELDS = {"seq", "prev", "type", "payload", "ts", "digest"}
prev_digest = "GENESIS"
types: dict[str, int] = {}
recomputed_ok = 0
for i, f in enumerate(jfiles, start=1):
    d = json.loads(f.read_text())
    check(set(d.keys()) == EXPECTED_FIELDS, f"{f.name}: unexpected fields "
                                            f"{sorted(set(d.keys()) ^ EXPECTED_FIELDS)}")
    check(d.get("seq") == i, f"{f.name}: seq {d.get('seq')} != {i}")
    check(d.get("prev") == prev_digest, f"{f.name}: prev linkage break")
    check(isinstance(d.get("ts"), (int, float)), f"{f.name}: ts not numeric")
    recomputed = sha256_bytes(canonical_bytes({
        "seq": d["seq"], "prev": d["prev"], "type": d["type"],
        "payload": d["payload"], "ts": d["ts"],
    }))
    check(recomputed == d["digest"], f"{f.name}: digest recompute mismatch")
    prev_digest = d["digest"]
    recomputed_ok += 1
    types[d.get("type")] = types.get(d.get("type"), 0) + 1

want_counts = {"tx_begin": 1, "contact": 1, "observation": 192,
               "restart": 1, "observation_adopted": 1}
check(types == want_counts, f"event counts differ: {types} vs {want_counts}")
check(set(types) <= set(want_counts),
      f"unexpected journal entry types: {sorted(set(types) - set(want_counts))}")

# mutation self-test (in-memory only): tampering must be caught
_st = json.loads(jfiles[99].read_text())
_tampered = json.loads(json.dumps(_st))
_tampered["payload"] = {**_tampered["payload"], "_probe": 1}
_t_recomp = sha256_bytes(canonical_bytes({
    "seq": _tampered["seq"], "prev": _tampered["prev"],
    "type": _tampered["type"], "payload": _tampered["payload"],
    "ts": _tampered["ts"]}))
check(_t_recomp != _st["digest"], "self-test FAILED: payload mutation not caught")
_tampered2 = json.loads(json.dumps(_st))
_tampered2["ts"] = _tampered2["ts"] + 0.5
_t_recomp2 = sha256_bytes(canonical_bytes({
    "seq": _tampered2["seq"], "prev": _tampered2["prev"],
    "type": _tampered2["type"], "payload": _tampered2["payload"],
    "ts": _tampered2["ts"]}))
check(_t_recomp2 != _st["digest"], "self-test FAILED: timestamp mutation not caught")
notes.append("mutation self-test: payload and timestamp tampering both caught")

# ---------------------------------------------------------------- C. orphans
TXID = "2e9b38f6d62e29bd6eb027fe621b984a828d82c169213df86d58831054d06245"
RECEIPT = "d696b239d31893d9a67570a700ffdc14e335ca1fee9e159d8adff4f0c7392923"
PREPARED_SCHEMA = "airlock.rsi-006-q5.execution-prepared.v1"
STARTED_SCHEMA = "airlock.rsi-006-q5.execution-started.v1"
COMPLETION_SCHEMA = "airlock.rsi-006-q5.execution-completion.v1"
ADOPT_EVIDENCE_SCHEMA = "airlock.rsi-006-q5.adopted-execution.v1"

txb = json.loads((FREEZE / "evidence" / "tx-begin.json").read_text())
check(txb["payload"]["txid"] == TXID, "tx-begin txid mismatch")
check(txb["payload"]["receipt_sha256"] == RECEIPT, "tx-begin receipt mismatch")
CODE_HASHES = txb["payload"]["code_hashes"]
LDIR = FREEZE / "evidence" / "ledger"


def load_ledger(name: str) -> dict:
    return json.loads((LDIR / name).read_text())


def check_bindings(rec: dict, name: str, obs: str, schema: str) -> None:
    check(rec.get("schema") == schema, f"{name}: schema {rec.get('schema')!r}")
    check(rec.get("txid") == TXID, f"{name}: txid binding")
    check(rec.get("observation_id") == obs, f"{name}: observation binding")
    check(rec.get("phase") == "discovery", f"{name}: phase binding")
    check(rec.get("receipt_sha256") == RECEIPT, f"{name}: receipt binding")
    check(rec.get("code_hashes") == CODE_HASHES, f"{name}: code-hash binding")


# --- cachetools-A-0048: why it was adoptable, from copied bytes
p48 = load_ledger("cachetools-A-0048.prepared.json")
s48 = load_ledger("cachetools-A-0048.started.json")
c48 = load_ledger("cachetools-A-0048.complete.json")
o48_bytes = (LDIR / "cachetools-A-0048.outcome.json").read_bytes()
for rec, nm, sc in ((p48, "0048.prepared", PREPARED_SCHEMA),
                    (s48, "0048.started", STARTED_SCHEMA),
                    (c48, "0048.complete", COMPLETION_SCHEMA)):
    check_bindings(rec, nm, "cachetools-A-0048", sc)
check(p48.get("attempt") == s48.get("attempt") == 1,
      "0048: prepared/started attempt mismatch")
d48 = sha256_bytes(o48_bytes)
check(d48 == c48["outcome_digest"],
      "0048: sha256(outcome bytes) != completion outcome_digest")
j196 = json.loads((FREEZE / "evidence" / "journal" / "00000196.json").read_text())
pl = j196["payload"]
check(pl["mutant_id"] == "cachetools-A-0048" and pl["phase"] == "discovery",
      "0048: journal adoption payload identity")
check(c48["outcome_digest"] == pl["digest"],
      "0048: completion outcome_digest != adopted journal digest")
# Q4 adoption contract recomputed from copied inputs + frozen constants
evidence48 = {
    "schema": ADOPT_EVIDENCE_SCHEMA,
    "txid": TXID,
    "observation_id": "cachetools-A-0048",
    "phase": "discovery",
    "receipt_sha256": RECEIPT,
    "code_hashes": dict(CODE_HASHES),
    "outcome_digest": d48,
    "ledger_prepared": p48,
    "ledger_started": s48,
    "ledger_completion": c48,
}
check(sha256_bytes(canonical_bytes(evidence48)) == pl["evidence_digest"],
      "0048: recomputed evidence_digest != journal evidence_digest")
launch_blob = canonical_bytes({"mutant_id": "cachetools-A-0048",
                               "phase": "discovery",
                               "observation_digest": d48, "adopted": True})
check(sha256_bytes(launch_blob + b"\n") == pl["launch_digest"],
      "0048: recomputed launch_digest != journal launch_digest")
notes.append("0048: on-disk adoption_evidence/launches artifacts were not "
             "captured in the freeze; their runtime existence is recorded at "
             "capture time, but both digests recompute exactly from copied "
             "inputs + the frozen Q4 contract")

# --- cachetools-A-0049: prepared + started bound; completion absent
p49 = load_ledger("cachetools-A-0049.prepared.json")
s49 = load_ledger("cachetools-A-0049.started.json")
for rec, nm, sc in ((p49, "0049.prepared", PREPARED_SCHEMA),
                    (s49, "0049.started", STARTED_SCHEMA)):
    check_bindings(rec, nm, "cachetools-A-0049", sc)
check(p49.get("attempt") == s49.get("attempt") == 1,
      "0049: prepared/started attempt mismatch")
have49 = {p.name for p in LDIR.glob("cachetools-A-0049.*")}
check(have49 == {"cachetools-A-0049.prepared.json",
                 "cachetools-A-0049.started.json"},
      f"0049: freeze holds unexpected ledger copies: {sorted(have49)}")
notes.append("0049: absence of complete/outcome in the runtime directory is "
             "NOT independently established from the freeze (no hashed "
             "runtime inventory was captured); it is attested by the frozen "
             "protocol's own resume-time scan, preserved in "
             "evidence/uncertain-execution-failure.txt, plus operator "
             "capture-time observation")

# ---------------------------------------------------------------- D. bindings
cm = json.loads((FREEZE / "evidence" / "contact-marker.json").read_text())
check(cm["mutant_id"] == "more-itertools-A-0002", "contact mutant mismatch")
check(abs(cm["ts"] - 1789506420.0496957) < 1e-6, "contact ts mismatch")
check(cm["receipt_sha256"] == RECEIPT, "contact receipt mismatch")
c1 = (FREEZE / "evidence" / "stage2-command.txt").read_bytes()
c2 = (FREEZE / "evidence" / "stage2-resume-command.txt").read_bytes()
check(c1 == c2, "resume command not byte-identical to original")
spec = (ROOT / "experiments" / "rsi-006-q5-durable-substrate-qualification"
        / "RSI_006_Q5_SPEC.md")
check(sha256_file(spec) == record["bound_code"]["q5_spec_sha256"],
      "RSI_006_Q5_SPEC.md no longer hashes to the bound value")
check(record["stage1_receipt_sha256"] == RECEIPT, "record receipt mismatch")
check(record["transaction"]["txid"] == TXID, "record txid mismatch")

# ---------------------------------------------------------------- report
if failures:
    print("FREEZE VERIFICATION FAILED:")
    for f_ in failures:
        print(" -", f_)
    sys.exit(1)

print(f"FREEZE VERIFIED")
print(f"  A. manifest inventory: {len(rows)} rows, unique, complete, "
      f"all hashes match, no extras")
print(f"  B. journal: {recomputed_ok}/196 entry digests recomputed per frozen "
      f"Q4 canonicalization, chain GENESIS-anchored, counts {types}")
print(f"  C. orphan bindings: 0048 adoptability chain independently verified "
      f"(bindings, outcome digest, journal digest, evidence_digest, "
      f"launch_digest); 0049 prepared+started bound, completion absence "
      f"recorded-at-capture (see notes)")
print(f"  D. contact/invocation/spec bindings hold")
print("  claim categories:")
print("    A (independently verified from frozen bytes): journal chain and "
      "counts, 0048 adoption chain, contact binding, byte-identical "
      "invocations, spec hash")
print("    B (recorded at capture time): no report file in runtime dir, no "
      "0049 complete/outcome in runtime dir, no other runtime state, "
      "on-disk existence of adoption/launch artifacts")
for n in notes:
    print(f"  note: {n}")
