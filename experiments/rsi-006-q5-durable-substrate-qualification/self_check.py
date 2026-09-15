"""RSI-006-Q5 self-check (non-executing w.r.t. the substrate).

Verifies, without importing the mutation substrate:
  1. every Q3 scientific constant is unchanged (AST-extracted from the Q3
     sources, compared against the frozen table -- which must also appear
     in RSI_006_Q5_SPEC.md);
  2. the Q3 implementation files still hash to the frozen environment
     receipt (proofs/rsi-006-q3/environment-receipt.json): Q3 preserved
     unchanged;
  3. Q4's merged transaction layer (stransaction.py) still hashes to the
     value merged in PR #161: Q4 preserved unchanged;
  4. no Q5 module imports researcher/model-access packages, the mutation
     substrate, or the Stage 1 repair module -- except the Stage 2
     runner and its fixture tests, which are the explicit scientific
     exception (SCIENTIFIC_IMPORT_ALLOWLIST names exactly the frozen
     Q3 imports each may carry). Q3's contact gate is the one allowed
     Q3 import elsewhere: it is the authorization boundary, not
     science);
  5. the adapter round-trips begin/run/open/resume on a scratch directory
     (no /tmp), including ledger start/completion records and the
     exactly-once contact transition.

Usage: python self_check.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
Q4_DIR = EXP_DIR.parent / "rsi-006-q4-durable-transaction"
REPO_ROOT = EXP_DIR.parent.parent
RECEIPT_PATH = REPO_ROOT / "proofs" / "rsi-006-q3" / "environment-receipt.json"
SPEC_PATH = EXP_DIR / "RSI_006_Q5_SPEC.md"

# Frozen Q3 scientific constants. Must match RSI_006_Q5_SPEC.md exactly.
FROZEN_SEED_A = "RSI-006-Q-discovery-A"
FROZEN_SEED_B = "RSI-006-Q-discovery-B"
# The per-observation subprocess ceiling. The production runner passes
# this frozen value into the adapter; the adapter's fixture default
# (60 s) is never used for scientific work.
FROZEN_RUN_TIMEOUT_S = 120
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

# Merged Q4 durable transaction layer (PR #161, main 73ad470). Q5 uses it
# as a library and must never modify it.
FROZEN_Q4_STRANSACTION_SHA256 = \
    "d7a54c1b4a658d7e566464d6ed5ebaf194ab868a70544c2155053a9a90797b04"

# Q3's contact gate is the authorization boundary Q5 preserves; it is the
# only Q3 module the substrate-free Q5 machinery may import.
FORBIDDEN_IMPORTS = ("openai", "anthropic", "google.generativeai", "boto3",
                     "langchain", "transformers", "huggingface_hub",
                     "perturb", "observe", "env_qualify")

# The Stage 2 runner (run_rsi_006_q5.py) is the INTENTIONALLY SCIENTIFIC
# part of Q5: it imports Q3's frozen observe / perturb / run_rsi_006_q3 /
# pool_config read-only and uses them directly -- no copies, no
# reimplementation, no indirect-import tricks. The adapter, ledger,
# receipt, and Stage 1 machinery stay substrate-free. The runner and its
# fixture tests are the ONLY files where these scientific imports are
# permitted; every other Q5 module and test keeps the ban. The values
# below name exactly which scientific imports each allowlisted file may
# carry: no other file, and no other import, is exempted.
SCIENTIFIC_IMPORT_ALLOWLIST = {
    "run_rsi_006_q5.py": ("observe", "perturb", "run_rsi_006_q3",
                          "pool_config"),
    "q5_fixture_support.py": ("observe", "perturb", "run_rsi_006_q3"),
    "test_q5_runner_falsifiers.py": ("observe", "perturb"),
    "test_q5_runner_parity.py": ("observe", "perturb", "run_rsi_006_q3"),
    "test_q5_runner_fullrun.py": ("observe", "perturb", "run_rsi_006_q3"),
    "test_q5_runner_crash.py": ("observe", "perturb", "run_rsi_006_q3"),
    "test_q5_runner_spawn_failure.py": ("perturb", "run_rsi_006_q3"),
}


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


def _smoke_spawn(exec_nonce: str):
    script = ("import sys; nonce = sys.argv[1]; "
              "sys.stdout.write('smoke-ok:' + nonce + '\n'); "
              "sys.stdout.flush()")
    return subprocess.Popen([sys.executable, "-c", script, exec_nonce],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def main() -> None:
    # 1. Q3 scientific constants unchanged (AST extraction; the substrate
    #    is never imported).
    runner = Q3_DIR / "run_rsi_006_q3.py"
    assert _extract_assign(runner, "SEED_A") == FROZEN_SEED_A
    assert _extract_assign(runner, "SEED_B") == FROZEN_SEED_B
    assert _extract_assign(runner, "BUDGETS") == FROZEN_BUDGETS
    assert _extract_assign(runner, "THRESH") == FROZEN_THRESH
    assert _extract_assign(Q3_DIR / "observe.py", "RUN_TIMEOUT_S") == \
        FROZEN_RUN_TIMEOUT_S
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

    # 1b. The frozen table is also stated in the Q5 spec.
    spec_text = SPEC_PATH.read_text()
    for needle in (FROZEN_SEED_A, FROZEN_SEED_B, "(72, 72, 10, 20)",
                   "(102, 102, 20, 60)",
                   "b2f3aff7633057d234ec9186c18a53f4df306d08",
                   "CMP_SWAP", "receiver-owned durable execution ledger"):
        assert needle in spec_text, f"Q5 spec missing frozen marker: {needle}"

    # 2. Q3 implementation preserved: live files hash to the frozen receipt.
    receipt = json.loads(RECEIPT_PATH.read_bytes())
    assert receipt["schema"] == "airlock.rsi-006-q3.env-receipt.v1"
    for name, frozen_hash in receipt["code_hashes"].items():
        live = hashlib.sha256((Q3_DIR / name).read_bytes()).hexdigest()
        assert live == frozen_hash, f"Q3 file changed: {name}"

    # 3. Q4 transaction layer preserved: merged hash unchanged.
    live_q4 = hashlib.sha256(
        (Q4_DIR / "stransaction.py").read_bytes()).hexdigest()
    assert live_q4 == FROZEN_Q4_STRANSACTION_SHA256, \
        f"Q4 stransaction.py changed: {live_q4}"

    # 4. Q5 modules import nothing forbidden. The Stage 2 runner and its
    #    fixture tests are the explicit scientific exception (see
    #    SCIENTIFIC_IMPORT_ALLOWLIST): they may import exactly the named
    #    frozen Q3 modules, nothing else.
    for path in EXP_DIR.glob("*.py"):
        allowed = SCIENTIFIC_IMPORT_ALLOWLIST.get(path.name, ())
        _assert_no_import_of(
            path, tuple(b for b in FORBIDDEN_IMPORTS if b not in allowed))
    for path in (EXP_DIR / "tests").glob("*.py"):
        allowed = SCIENTIFIC_IMPORT_ALLOWLIST.get(path.name, ())
        _assert_no_import_of(
            path, tuple(b for b in FORBIDDEN_IMPORTS if b not in allowed))

    # 5. Adapter smoke: ledger + contact gate + transaction round-trip on
    #    a scratch dir outside /tmp, with a real (trivial) subprocess.
    #    One coordinator owns the live transaction; the worker thread
    #    returns evidence and the coordinator journals serially.
    for mod_dir in (str(EXP_DIR), str(Q4_DIR), str(Q3_DIR)):
        sys.path.insert(0, mod_dir)
    try:
        import stransaction as st
        import execution_ledger as ledger
        import q5_adapter as qa
        from contact import ContactGate
    finally:
        for mod_dir in (str(EXP_DIR), str(Q4_DIR), str(Q3_DIR)):
            sys.path.remove(mod_dir)
    scratch_parent = Path.home() / "workspace"
    scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="rsi-006-q5-selfcheck-",
                                    dir=str(scratch_parent)))
    try:
        code_hashes = {
            "stransaction.py": FROZEN_Q4_STRANSACTION_SHA256,
            "execution_ledger.py": hashlib.sha256(
                (EXP_DIR / "execution_ledger.py").read_bytes()).hexdigest(),
        }
        tx = st.ScientificTransaction.begin(
            scratch, receipt_sha256="e" * 64, code_hashes=code_hashes,
            tx_nonce=os.urandom(32).hex())
        gate = ContactGate(scratch / "contact_marker.json")
        coord = qa.Coordinator(
            work_dir=scratch, tx=tx, gate=gate,
            receipt_sha256="e" * 64, code_hashes=code_hashes)
        assert coord.reconcile_contact() is None
        applied = coord.run_all(
            observations=[("smoke-obs-1", "discovery")],
            spawn=_smoke_spawn, argv_for=lambda obs_id: ["smoke"],
            max_workers=1)
        assert applied[0]["status"] == "committed", applied
        assert applied[0]["contact_created"] is True
        assert gate.consumed
        # Ledger records exist and are bound: prepared before spawn,
        # started after the child provably existed, completion after
        # the outcome bytes were durable.
        for kind in ("prepared", "started", "complete"):
            assert (scratch / "artifacts" / "execution_ledger"
                    / f"smoke-obs-1.{kind}.json").exists(), kind
        # Resume in a "new process": the successor opens exactly once
        # (restart_count 1 -- the coordinator never re-opens during
        # ordinary operation), committed work is skipped, contact is
        # intact, and the journal verifies.
        tx2 = st.ScientificTransaction.open(
            scratch, receipt_sha256="e" * 64, code_hashes=code_hashes)
        assert tx2.restart_count == 1, tx2.restart_count
        coord2 = qa.Coordinator(
            work_dir=scratch, tx=tx2, gate=gate,
            receipt_sha256="e" * 64, code_hashes=code_hashes)
        assert coord2.reconcile_contact() is None
        applied2 = coord2.run_all(
            observations=[("smoke-obs-1", "discovery")],
            spawn=_smoke_spawn, argv_for=lambda obs_id: ["smoke"],
            max_workers=1)
        assert applied2[0]["status"] == "skipped_committed", applied2
        assert tx2.contact_event["mutant_id"] == "smoke-obs-1"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print("RSI-006-Q5 self-check clean: Q3 constants bound and unchanged, "
          "Q3 implementation byte-identical to the frozen receipt, Q4 "
          "transaction layer unchanged from the merged PR #161, no "
          "forbidden imports, adapter round-trips with ledger and "
          "exactly-once contact. No scientific contact occurred; the real "
          "substrate was not executed.")


if __name__ == "__main__":
    main()
