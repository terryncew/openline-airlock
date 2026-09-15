"""RSI-006-Q5 Stage 1 qualifier self-check (non-scientific).

Statically and dynamically proves, without touching the four real
repositories and without any scientific contact:

  1. Q3 still matches its frozen environment receipt;
  2. Q4's merged transaction file is unchanged;
  3. the existing Q5 adapter/ledger are unchanged from the merged HEAD;
  4. the production execution manifest carries the expected required
     entries (including the not-yet-existing Q5 Stage 2 runner);
  5. production qualification is currently LOCKED because
     ``run_rsi_006_q5.py`` is absent -- and the refusal happens before
     any environment mutation (the missing runner is a PASS condition
     for this pre-contact mechanism, not a reason to fake a runner);
  6. Stage 1 code imports no mutation/runtime scientific substrate and
     references no scientific-contact identifiers.

Usage: python stage1/self_check.py
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

    # 3. Existing Q5 adapter/ledger unchanged from the merged HEAD.
    for rel in ("experiments/rsi-006-q5-durable-substrate-qualification/"
                "execution_ledger.py",
                "experiments/rsi-006-q5-durable-substrate-qualification/"
                "q5_adapter.py"):
        live = (REPO_ROOT / rel).read_bytes()
        assert live == _git_show(rel), f"Q5 runtime file changed: {rel}"

    # 4. Production manifest carries the expected required entries.
    manifest = q5_receipt.load_manifest(MANIFEST_PATH)
    assert manifest["schema"] == q5_receipt.MANIFEST_SCHEMA
    for req in REQUIRED_MANIFEST_FILES:
        assert req in manifest["code_files"], \
            f"production manifest omits required entry: {req}"
    assert manifest["q3_receipt"]["path"] == \
        "proofs/rsi-006-q3/environment-receipt.json"
    assert manifest["q3_receipt"]["sha256"] == FROZEN_Q3_RECEIPT_SHA256

    # 5. Production qualification is LOCKED: the required Q5 Stage 2
    #    runner is absent, and the refusal happens before any
    #    environment mutation. The missing runner is a PASS condition.
    try:
        q5_receipt.validate_manifest(MANIFEST_PATH, REPO_ROOT)
    except q5_receipt.ManifestIncomplete as e:
        assert "experiments/rsi-006-q5-durable-substrate-qualification/" \
            "run_rsi_006_q5.py" in e.missing, e.missing
    else:
        raise AssertionError(
            "production manifest unexpectedly complete: the Q5 Stage 2 "
            "runner must be absent until its own reviewed change lands")

    scratch = Path(tempfile.mkdtemp(prefix="rsi-006-q5-stage1-selfcheck-",
                                    dir=str(Path.home() / "workspace")))
    try:
        for mode in ("--qualify-env", "--arm-storage"):
            target = scratch / ("refused-" + mode.strip("-"))
            proc = subprocess.run(
                [sys.executable, str(ENV_QUALIFY), mode,
                 "--durable-root", str(target)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=120)
            assert proc.returncode != 0, \
                f"{mode} unexpectedly succeeded without the runner"
            combined = proc.stdout + proc.stderr
            assert "run_rsi_006_q5.py" in combined, \
                f"{mode} refusal did not name the missing runner"
            # Refusal before ANY mutation: no attempt dir, no witness,
            # no receipt, no lock file.
            leftovers = [p.name for p in target.rglob("*")] \
                if target.exists() else []
            assert leftovers == [], \
                f"{mode} mutated the durable root before refusing: " \
                f"{leftovers}"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

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
          "adapter/ledger unchanged from HEAD, production manifest carries "
          "the required execution surface, production qualification is "
          "LOCKED (run_rsi_006_q5.py absent; refusal before any mutation), "
          "Stage 1 code imports no scientific substrate. No real "
          "repositories, no Stage 1 run, no scientific contact occurred.")


if __name__ == "__main__":
    main()
