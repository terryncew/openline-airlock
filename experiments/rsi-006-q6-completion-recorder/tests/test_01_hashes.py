"""Q6 frozen-dependency hash pins (exact base main b947b3d)."""

import hashlib
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent.parent
EXP = Q6_DIR.parent

# Frozen at implementation time; verified against base main b947b3d.
# Paths are relative to the experiments/ directory.
PINS = {
    "rsi-006-q4-durable-transaction/stransaction.py":
        "d7a54c1b4a658d7e566464d6ed5ebaf194ab868a70544c2155053a9a90797b04",
    "rsi-006-q5-durable-substrate-qualification/execution_ledger.py":
        "54faba957fadc2e4bb2d7bab587c064dc4e437f5c04e1dadb4540c1a6c74167f",
    "rsi-006-q5-durable-substrate-qualification/q5_adapter.py":
        "b425f393f192e50a22090ad4d433ff82c9949f111b3fc5551e3b5a70a796e7ff",
    "rsi-006-q5-durable-substrate-qualification/run_rsi_006_q5.py":
        "0d9063676cd983bec3a480206b8edccdb9ae1e74e7f99ecf42c92a5e75a374c1",
    "rsi-006-q5-durable-substrate-qualification/environment_receipt.py":
        "bc2a7476d7906df5bcb3d4ba4812d2ce356c37beb6dc2ca7c9103f2f423d4086",
    "rsi-006-q5-durable-substrate-qualification/stage1/env_qualify.py":
        "e0f4725bc675f34f7f38502ec81a0981ad764a2ef0335650685c9329476b8988",
    "rsi-006-q3-substrate-qualification/contact.py":
        "5b2ad96067fd7a399988f9439e091511cef56bc6cab2135eeddffb10c2030197",
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_frozen_dependency_hashes():
    for rel, pin in PINS.items():
        p = EXP / rel
        assert p.is_file(), f"missing frozen file: {rel}"
        assert _sha256(p) == pin, f"hash drift in frozen file: {rel}"


def test_frozen_q3_receipt_hash():
    p = EXP.parent / "proofs" / "rsi-006-q3" / "environment-receipt.json"
    assert p.is_file()
    assert _sha256(p) == \
        "d89327dcceb1536d7f66c5d1257a15f9b0de3b9f4c19ef75549eadaa7515acaa"
