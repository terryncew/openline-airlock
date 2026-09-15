"""RSI-006-Q5 Stage 1 qualifier self-check (non-scientific).

Statically and dynamically proves, without touching the four real
repositories and without any scientific contact:

  1. Q3 still matches its frozen environment receipt;
  2. Q4's merged transaction file is unchanged;
  3. the Q5 ledger is unchanged from the merged HEAD, and the Q5
     adapter (changed by design in the pre-contact runner mechanism)
     is bound by the production execution manifest;
  4. the production execution manifest carries the expected required
     entries (including the Q5 Stage 2 runner, now present);
  5. the production execution surface is COMPLETE (runner present and
     listed, manifest validates) AND Stage 1 has still not run: no
     production environment receipt exists, and CI never invokes
     arming or qualification -- asserted statically, since executing
     the modes with a complete manifest would do real environment
     work;
  6. Stage 1 code imports no mutation/runtime scientific substrate and
     references no scientific-contact identifiers.

Usage: python stage1/self_check.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

STAGE1_DIR = Path(__file__).resolve().parent
Q5_DIR = STAGE1_DIR.parent
REPO_ROOT = Q5_DIR.parent.parent
Q3_DIR = REPO_ROOT / "experiments" / "rsi-006-q3-substrate-qualification"
Q4_PATH = REPO_ROOT / "experiments" / "rsi-006-q4-durable-transaction" \
    / "stransaction.py"
Q3_RECEIPT_PATH = REPO_ROOT / "proofs" / "rsi-006-q3" \
    / "environment-receipt.json"
MANIFEST_PATH = Q5_DIR / "execution_manifest.json"
ENV_QUALIFY = STAGE1_DIR / "env_qualify.py"

FROZEN_Q3_RECEIPT_SHA256 = \
    "d89327dcceb1536d7f66c5d1257a15f9b0de3b9f4c19ef75549eadaa7515acaa"
FROZEN_Q4_STRANSACTION_SHA256 = \
    "d7a54c1b4a658d7e566464d6ed5ebaf194ab868a70544c2155053a9a90797b04"

# The mutation/runtime scientific substrate Stage 1 may never touch.
# Q3's frozen helpers (pool_config, receipt, env_qualify, observe) are
# explicitly allowed: they are the reused, already-tested Stage 1
# machinery, not science.
BANNED_IMPORTS = ("perturb", "stransaction", "q5_adapter",
                  "execution_ledger", "contact", "openai", "anthropic",
                  "google.generativeai", "boto3", "langchain",
                  "transformers", "huggingface_hub")
BANNED_IDENTIFIERS = ("ScientificTransaction", "ContactGate",
                      "tx_nonce", "confirmation_nonce")

REQUIRED_MANIFEST_FILES = (
    "experiments/rsi-006-q5-durable-substrate-qualification/execution_ledger.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/q5_adapter.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/environment_receipt.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/stage1/env_qualify.py",
    "experiments/rsi-006-q5-durable-substrate-qualification/run_rsi_006_q5.py",
    "experiments/rsi-006-q4-durable-transaction/stransaction.py",
)

sys.path.insert(0, str(Q5_DIR))
import environment_receipt as q5_receipt  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _referenced_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_bytes())
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _git_show(relpath: str) -> bytes:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{relpath}"],
        capture_output=True, check=True)
    return out.stdout


def main() -> None:
    # 1. Q3 byte-identical to its frozen receipt.
    assert _sha256(Q3_RECEIPT_PATH) == FROZEN_Q3_RECEIPT_SHA256, \
        "frozen Q3 receipt file drifted"
    q3_receipt = json.loads(Q3_RECEIPT_PATH.read_bytes())
    assert q3_receipt["schema"] == "airlock.rsi-006-q3.env-receipt.v1"
    for name, frozen_hash in q3_receipt["code_hashes"].items():
        live = _sha256(Q3_DIR / name)
        assert live == frozen_hash, f"Q3 file changed: {name}"

    # 2. Q4 transaction layer unchanged from the merged PR #161.
    live_q4 = _sha256(Q4_PATH)
    assert live_q4 == FROZEN_Q4_STRANSACTION_SHA256, \
        f"Q4 stransaction.py changed: {live_q4}"

    # 3. Q5 ledger unchanged from the merged HEAD. The adapter is NOT
    #    HEAD-pinned: it changed by design in the pre-contact runner
    #    mechanism change, so it is validated through the
    #    manifest/runner mechanism instead -- see step 5, which asserts
    #    the adapter is manifest-bound (any adapter change invalidates
    #    the manifest binding, and therefore any frozen receipt).
    ledger_rel = ("experiments/rsi-006-q5-durable-substrate-qualification/"
                  "execution_ledger.py")
    live_ledger = (REPO_ROOT / ledger_rel).read_bytes()
    assert live_ledger == _git_show(ledger_rel), \
        f"Q5 ledger changed: {ledger_rel}"

    # 4. Production manifest carries the expected required entries.
    manifest = q5_receipt.load_manifest(MANIFEST_PATH)
    assert manifest["schema"] == q5_receipt.MANIFEST_SCHEMA
    for req in REQUIRED_MANIFEST_FILES:
        assert req in manifest["code_files"], \
            f"production manifest omits required entry: {req}"
    assert manifest["q3_receipt"]["path"] == \
        "proofs/rsi-006-q3/environment-receipt.json"
    assert manifest["q3_receipt"]["sha256"] == FROZEN_Q3_RECEIPT_SHA256

    # 5. Production execution surface is COMPLETE: the required Q5
    #    Stage 2 runner is present and listed, and the production
    #    manifest validates. Completeness is not authorization: Stage 1
    #    has not run -- no production environment receipt exists -- and
    #    nothing in CI can invoke arming or qualification. The modes
    #    are deliberately NOT executed here: with a complete manifest
    #    they would proceed past the preflight toward real environment
    #    work, so the self-check asserts the boundary statically.
    runner_rel = ("experiments/rsi-006-q5-durable-substrate-qualification/"
                  "run_rsi_006_q5.py")
    assert (REPO_ROOT / runner_rel).is_file(), \
        "Q5 Stage 2 runner file missing"
    binding = q5_receipt.validate_manifest(MANIFEST_PATH, REPO_ROOT)
    assert runner_rel in binding["files"], \
        "runner present but not bound by the manifest"
    # The adapter changed by design in the pre-contact runner
    # mechanism change, so instead of the merged-HEAD pin it is
    # validated through the manifest binding: it must be listed, and
    # its live bytes must hash to the bound hash. Any adapter change
    # moves the binding and invalidates any frozen receipt.
    adapter_rel = ("experiments/rsi-006-q5-durable-substrate-qualification/"
                   "q5_adapter.py")
    assert adapter_rel in binding["files"], \
        "adapter present but not bound by the manifest"
    assert _sha256(REPO_ROOT / adapter_rel) == binding["files"][adapter_rel], \
        "adapter live bytes do not match the manifest binding"
    manifest = q5_receipt.load_manifest(MANIFEST_PATH)
    assert "does not exist yet" not in manifest.get("note", ""), \
        "manifest note still claims the runner is absent"
    # No production receipt anywhere in the repo outside transient
    # fixture scratch (cleaned up by the test fixtures): Stage 1 has
    # not run.
    scratch = Q5_DIR / "tests" / "_scratch"
    receipts = [p for p in REPO_ROOT.rglob("q5-environment-receipt.json")
                if scratch not in p.parents]
    assert receipts == [], \
        f"production environment receipt exists: Stage 1 has run: {receipts}"
    # CI never invokes arming or qualification.
    for wf in ("rsi-006-q5-stage1-gate.yml", "rsi-006-q5-runner-gate.yml"):
        text = (REPO_ROOT / ".github" / "workflows" / wf).read_text()
        assert "--qualify-env" not in text, f"{wf} invokes --qualify-env"
        assert "--arm-storage" not in text, f"{wf} invokes --arm-storage"

    # 6. Stage 1 code imports no mutation/runtime scientific substrate
    #    (static), and references no scientific-contact identifiers.
    for path in (Q5_DIR / "environment_receipt.py", ENV_QUALIFY,
                 STAGE1_DIR / "self_check.py"):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for mod in mods:
                assert not any(mod == b or mod.startswith(b + ".")
                               for b in BANNED_IMPORTS), \
                    f"forbidden import {mod} in {path.name}"
    names = _referenced_names(ENV_QUALIFY)
    bad_names = set(BANNED_IDENTIFIERS) & names
    assert not bad_names, \
        f"scientific-contact identifiers in stage1/env_qualify.py: {bad_names}"

    # 6b. Dynamic: loading stage1/env_qualify.py in a fresh interpreter
    #     loads no mutation/runtime scientific substrate.
    probe = (
        "import importlib.util, json, sys; "
        f"spec = importlib.util.spec_from_file_location("
        f"'q5_stage1_probe', {str(ENV_QUALIFY)!r}); "
        "mod = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(mod); "
        "print(json.dumps(sorted(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", probe],
                         capture_output=True, text=True, timeout=60,
                         cwd=str(Q5_DIR))
    assert out.returncode == 0, f"stage1 probe failed: {out.stderr[:500]}"
    loaded = set(json.loads(out.stdout))
    bad_loaded = loaded & {"perturb", "stransaction", "q5_adapter",
                           "execution_ledger", "contact"}
    assert not bad_loaded, \
        f"stage1 dynamically loaded scientific substrate: {bad_loaded}"

    # 7. Receipt module exposes the verifier the future Stage 2 runner
    #    needs, with the v1 schema.
    assert q5_receipt.RECEIPT_SCHEMA == "airlock.rsi-006-q5.env-receipt.v1"
    assert callable(q5_receipt.verify_receipt)
    assert callable(q5_receipt.freeze_receipt)

    # 7b. The qualifier implementation binding covers exactly the three
    #     qualification-critical files and is computable (pure read):
    #     the receipt binds what decided admissibility.
    qhashes = q5_receipt.qualifier_code_hashes(Q5_DIR)
    assert set(qhashes) == set(q5_receipt.QUALIFIER_CRITICAL_FILES), qhashes
    assert all(len(h) == 64 for h in qhashes.values())

    print("RSI-006-Q5 Stage 1 self-check clean: Q3 byte-identical to its "
          "frozen receipt, Q4 unchanged from the merged PR #161, Q5 "
          "ledger unchanged from HEAD with the adapter manifest-bound "
          "(pre-contact runner mechanism), production manifest carries "
          "the required execution surface and validates with the runner "
          "present and listed, no production Stage 1 run (no receipt), "
          "CI never invokes arming or qualification, Stage 1 code imports "
          "no scientific substrate. No real repositories, no Stage 1 run, "
          "no scientific contact occurred.")


if __name__ == "__main__":
    main()
