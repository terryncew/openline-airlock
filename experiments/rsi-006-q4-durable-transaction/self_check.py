"""RSI-006-Q4 self-check (non-executing w.r.t. the substrate).

Verifies, without importing the mutation substrate:
  1. every Q3 scientific constant is unchanged (AST-extracted from the Q3
     sources, compared against the frozen table -- which must also appear
     in RSI_006_Q4_SPEC.md);
  2. the Q3 implementation files still hash to the frozen environment
     receipt (proofs/rsi-006-q3/environment-receipt.json): Q3 preserved
     unchanged;
  3. no Q4 module imports researcher/model-access packages, the mutation
     substrate, or the Stage 1 repair module;
  4. the transaction layer round-trips begin/commit/open/resume on a
     scratch directory (no /tmp).

Usage: python self_check.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
REPO_ROOT = EXP_DIR.parent.parent
RECEIPT_PATH = REPO_ROOT / "proofs" / "rsi-006-q3" / "environment-receipt.json"
SPEC_PATH = EXP_DIR / "RSI_006_Q4_SPEC.md"

# Frozen Q3 scientific constants. Must match RSI_006_Q4_SPEC.md exactly.
FROZEN_SEED_A = "RSI-006-Q-discovery-A"
FROZEN_SEED_B = "RSI-006-Q-discovery-B"
FROZEN_BUDGETS = {
    "more-itertools": (72, 72, 10, 20),
    "cachetools": (102, 102, 20, 60),
    "boltons": (70, 70, 20, 60),
    "pluggy": (51, 51, 20, 60),
}
FROZEN_THRESH = {
    "qdet_agreement": 1.0,
    "kill_rate_lo": 0.05,
    "kill_rate_hi": 0.95,
    "stab_abs_tol": 0.25,
    "stab_spearman_min": 0.7,
    "stab_min_operators": 3,
    "stab_min_per_half": 10,
    "fresh_op_tol": 0.30,
    "fresh_overall_tol": 0.15,
    "collection_error_max": 0.10,
}
FROZEN_OPERATORS = ("CMP_SWAP", "ARITH_SWAP", "BOOL_FLIP",
                    "NUM_DELTA", "LOGIC_SWAP", "NOT_DROP")
FROZEN_PINS = {
    "more-itertools": "b2f3aff7633057d234ec9186c18a53f4df306d08",
    "cachetools": "4500e3d04288738d25acbb4973eb3c3e1bf41db9",
    "boltons": "961dcff3f42e73b245aef65e377fe82763b257bb",
    "pluggy": "0a4974175aa2d873f401345b151297af2e74c851",
}

FORBIDDEN_IMPORTS = ("openai", "anthropic", "google.generativeai", "boto3",
                     "langchain", "transformers", "huggingface_hub",
                     "perturb", "observe", "env_qualify")


def _extract_assign(path: Path, name: str):
    tree = ast.parse(path.read_bytes())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name}: assignment {name} not found")


def _assert_no_import_of(path: Path, banned: tuple[str, ...]) -> None:
    tree = ast.parse(path.read_bytes())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        for mod in mods:
            assert not any(mod == b or mod.startswith(b + ".")
                           for b in banned), \
                f"forbidden import {mod} in {path.name}"


def main() -> None:
    # 1. Q3 scientific constants unchanged (AST extraction; the substrate
    #    is never imported).
    runner = Q3_DIR / "run_rsi_006_q3.py"
    assert _extract_assign(runner, "SEED_A") == FROZEN_SEED_A
    assert _extract_assign(runner, "SEED_B") == FROZEN_SEED_B
    assert _extract_assign(runner, "BUDGETS") == FROZEN_BUDGETS
    assert _extract_assign(runner, "THRESH") == FROZEN_THRESH
    assert tuple(_extract_assign(
        Q3_DIR / "perturb.py", "OPERATORS")) == FROZEN_OPERATORS
    sys.path.insert(0, str(Q3_DIR))  # pool_config is pure data, no substrate
    try:
        import pool_config
        pins = {e["name"]: e["sha"] for e in pool_config.POOL}
    finally:
        sys.path.remove(str(Q3_DIR))
        sys.modules.pop("pool_config", None)
    assert pins == FROZEN_PINS, pins

    # 1b. The frozen table is also stated in the Q4 spec.
    spec_text = SPEC_PATH.read_text()
    for needle in (FROZEN_SEED_A, FROZEN_SEED_B, "(72, 72, 10, 20)",
                   "(102, 102, 20, 60)", "b2f3aff7633057d234ec9186c18a53f4df306d08",
                   "CMP_SWAP", "durable, receiver-owned scientific-transaction layer"):
        assert needle in spec_text, f"Q4 spec missing frozen marker: {needle}"

    # 2. Q3 implementation preserved: live files hash to the frozen receipt.
    receipt = json.loads(RECEIPT_PATH.read_bytes())
    assert receipt["schema"] == "airlock.rsi-006-q3.env-receipt.v1"
    for name, frozen_hash in receipt["code_hashes"].items():
        live = hashlib.sha256((Q3_DIR / name).read_bytes()).hexdigest()
        assert live == frozen_hash, f"Q3 file changed: {name}"

    # 3. Q4 modules import nothing forbidden (no researcher packages, no
    #    substrate, no Stage 1 repair module).
    for path in EXP_DIR.glob("*.py"):
        _assert_no_import_of(path, FORBIDDEN_IMPORTS)
    for path in (EXP_DIR / "tests").glob("*.py"):
        _assert_no_import_of(path, FORBIDDEN_IMPORTS)

    # 4. Transaction layer smoke: begin/commit/open/resume round-trip on a
    #    scratch dir outside /tmp.
    sys.path.insert(0, str(EXP_DIR))
    try:
        import stransaction as st
    finally:
        sys.path.remove(str(EXP_DIR))
    scratch = Path(tempfile.mkdtemp(prefix="rsi-006-q4-selfcheck-",
                                    dir=str(Path.home() / "workspace")))
    try:
        code_hashes = {"stransaction.py": st.sha256_file(
            EXP_DIR / "stransaction.py")}
        tx = st.ScientificTransaction.begin(
            scratch, receipt_sha256="f" * 64, code_hashes=code_hashes)
        txid = tx.txid
        r = tx.note_contact(mutant_id="smoke-1", child_pid=1234)
        assert r["created"] is True
        d = tx.commit_observation(mutant_id="smoke-1", phase="discovery",
                                  canonical=b'{"a":1}',
                                  launch={"note": "smoke"})
        assert tx.observations == {"smoke-1": d}
        tx.commit_nonce(nonce_hex="ab" * 32)
        # Resume in a "new process": bindings verified, work skipped.
        tx2 = st.ScientificTransaction.open(
            scratch, receipt_sha256="f" * 64, code_hashes=code_hashes)
        assert tx2.txid == txid
        assert tx2.contact_event["mutant_id"] == "smoke-1"
        assert tx2.nonce == "ab" * 32
        assert tx2.pending(["smoke-1", "smoke-2"]) == ["smoke-2"]
        assert tx2.restart_count == 1
        try:
            tx2.commit_observation(mutant_id="smoke-1", phase="discovery",
                                   canonical=b'{"a":1}', launch={})
        except st.DuplicateWork:
            pass
        else:
            raise AssertionError("duplicate observation not rejected")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print("RSI-006-Q4 self-check clean: Q3 constants bound and unchanged, "
          "Q3 implementation preserved byte-identical to the frozen "
          "receipt, no forbidden imports, transaction layer round-trips. "
          "No scientific contact occurred; the real substrate was not "
          "executed.")


if __name__ == "__main__":
    main()
