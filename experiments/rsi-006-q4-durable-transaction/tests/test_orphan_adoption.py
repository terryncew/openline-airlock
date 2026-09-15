"""RSI-006-Q4 orphan-adoption contract tests.

Discriminating tests for the observation-completion/commit gap: the
fixture maintains an independently durable, append-only execution
receipt OUTSIDE the Q4 journal, recording every physical observation
execution (fsync'd) with a fresh random ``exec_nonce`` per execution.
A crash is forced after the outcome is durably recorded but before the
transaction commits it -- either before ``commit_observation`` runs
(execution gap) or inside it after the artifact rename but before the
journal append (commit gap).

Strict acceptance: the crashed observation must not execute a second
time. The resume must either adopt the exact first completed outcome
from the independently durable, transaction-bound evidence (verifying
transaction ID, observation ID, receipt/code bindings, and artifact
digest), or fail closed. Re-executing and obtaining the same
deterministic result is not acceptable -- and is detectable here,
because a re-execution would carry a different ``exec_nonce``.

No real repositories, no real mutants, no scientific contact.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(TESTS_DIR.parent))
import stransaction as st
from fixture_driver import (FIXTURE_RECEIPT_SHA, append_exec_entry,
                            code_hashes, exec_log_dir, read_exec_log,
                            scan_and_adopt_orphans)

DRIVER = TESTS_DIR / "fixture_driver.py"
SCRATCH = TESTS_DIR / ".scratch-orphan"

EXEC_GAP_TARGET = "alpha-A-0003"
COMMIT_GAP_TARGET = "alpha-B-0002"


def run_driver(work_dir: Path, *extra: str):
    cmd = [sys.executable, str(DRIVER), "--work-dir", str(work_dir), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


def parse_summary(cp) -> dict:
    out = {}
    for line in cp.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def journal_entries(work_dir: Path) -> list[dict]:
    return [json.loads(p.read_bytes())
            for p in sorted((work_dir / "journal").glob("[0-9]*.json"))]


def exec_count(work_dir: Path, mid: str) -> int:
    entries, torn = read_exec_log(work_dir)
    assert not torn
    return sum(1 for e in entries if e["observation_id"] == mid)


@pytest.fixture(scope="session", autouse=True)
def scratch_root():
    import shutil
    SCRATCH.mkdir(parents=True, exist_ok=True)
    yield SCRATCH
    shutil.rmtree(SCRATCH, ignore_errors=True)


@pytest.fixture()
def fresh_dir(scratch_root, request):
    import shutil
    d = scratch_root / request.node.name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def test_execution_gap_adopted_not_rerun(fresh_dir):
    """Crash after the outcome is durably recorded, before commit.

    The observation must not execute a second time: the resume adopts
    the exact first outcome from the independent evidence.
    """
    d = fresh_dir
    cp1 = run_driver(d, "--exec-log", "--crash-target", EXEC_GAP_TARGET,
                     "--crash-point", "execution_gap")
    assert cp1.returncode == 1, cp1.stderr

    # Independently durable evidence of exactly one physical execution,
    # outside the Q4 journal; the transaction has no record of it yet.
    assert exec_count(d, EXEC_GAP_TARGET) == 1
    original = (exec_log_dir(d) / "outcomes"
                / f"{EXEC_GAP_TARGET}.json").read_bytes()
    assert not (d / "artifacts" / "observations"
                / f"{EXEC_GAP_TARGET}.json").exists()
    assert not any(e["type"] in ("observation", "observation_adopted")
                   and e["payload"]["mutant_id"] == EXEC_GAP_TARGET
                   for e in journal_entries(d))

    cp2 = run_driver(d, "--exec-log")
    assert cp2.returncode == 0, cp2.stderr
    r = parse_summary(cp2)
    assert r["VERDICT"] in ("QUALIFIED_FIXTURE", "NOT_QUALIFIED_FIXTURE")
    assert r["N_OBSERVATIONS"] == "36"
    assert int(r["MAX_RESTART_COUNT"]) >= 1

    # Strict acceptance: still exactly one execution ...
    assert exec_count(d, EXEC_GAP_TARGET) == 1
    # ... and the adopted outcome is byte-identical to the first
    # completed outcome (same exec_nonce: not a rerun).
    adopted = (d / "artifacts" / "observations"
               / f"{EXEC_GAP_TARGET}.json").read_bytes()
    assert adopted == original
    assert json.loads(adopted)["exec_nonce"] == \
        json.loads(original)["exec_nonce"]
    adopted_entries = [
        e for e in journal_entries(d)
        if e["type"] in ("observation", "observation_adopted")
        and e["payload"]["mutant_id"] == EXEC_GAP_TARGET]
    assert len(adopted_entries) == 1
    assert adopted_entries[0]["type"] == "observation_adopted"
    assert adopted_entries[0]["payload"]["adopted_from"] == "orphan_evidence"


def test_commit_gap_orphan_artifact_adopted(fresh_dir):
    """Crash inside commit_observation: artifact written, no journal entry.

    The orphan artifact must be adopted only after verification against
    the independent digest -- never silently re-executed.
    """
    d = fresh_dir
    cp1 = run_driver(d, "--exec-log", "--crash-target", COMMIT_GAP_TARGET,
                     "--crash-point", "commit_gap")
    assert cp1.returncode == 1, cp1.stderr

    orphan = (d / "artifacts" / "observations"
              / f"{COMMIT_GAP_TARGET}.json")
    assert orphan.exists(), "the crashed commit left its artifact"
    assert not any(e["type"] in ("observation", "observation_adopted")
                   and e["payload"]["mutant_id"] == COMMIT_GAP_TARGET
                   for e in journal_entries(d)), \
        "no journal entry was appended"
    original = (exec_log_dir(d) / "outcomes"
                / f"{COMMIT_GAP_TARGET}.json").read_bytes()
    assert orphan.read_bytes() == original
    assert exec_count(d, COMMIT_GAP_TARGET) == 1

    cp2 = run_driver(d, "--exec-log")
    assert cp2.returncode == 0, cp2.stderr
    r = parse_summary(cp2)
    assert r["N_OBSERVATIONS"] == "36"

    assert exec_count(d, COMMIT_GAP_TARGET) == 1
    adopted = (d / "artifacts" / "observations"
               / f"{COMMIT_GAP_TARGET}.json").read_bytes()
    assert adopted == original
    adopted_entries = [
        e for e in journal_entries(d)
        if e["type"] in ("observation", "observation_adopted")
        and e["payload"]["mutant_id"] == COMMIT_GAP_TARGET]
    assert len(adopted_entries) == 1
    assert adopted_entries[0]["type"] == "observation_adopted"


# --------------------------------------------------------------------------
# negative tests: unverifiable orphans fail closed
# --------------------------------------------------------------------------

def _begun_tx(d: Path, tx_nonce: str | None = None):
    return st.ScientificTransaction.begin(
        d, receipt_sha256=FIXTURE_RECEIPT_SHA, code_hashes=code_hashes(),
        tx_nonce=tx_nonce or os.urandom(32).hex())


def _evidence(tx, mid: str, digest: str, **over) -> dict:
    ev = {
        "txid": tx.txid,
        "observation_id": mid,
        "phase": "discovery",
        "outcome_digest": digest,
        "receipt_sha256": FIXTURE_RECEIPT_SHA,
        "code_hashes": code_hashes(),
        "launch": {"restart_count": 0, "pid": 1},
    }
    ev.update(over)
    return ev


def test_orphan_adoption_rejects_binding_drift(fresh_dir):
    tx = _begun_tx(fresh_dir)
    outcome = b'{"m":1}'
    ev = _evidence(tx, "m1", st.sha256_bytes(outcome),
                   receipt_sha256="0" * 64)
    with pytest.raises(st.OrphanUnverifiable):
        tx.adopt_orphan_observation(mutant_id="m1", phase="discovery",
                                    outcome_bytes=outcome, evidence=ev)
    assert "m1" not in tx.observations


def test_orphan_adoption_rejects_digest_mismatch(fresh_dir):
    tx = _begun_tx(fresh_dir)
    ev = _evidence(tx, "m1", st.sha256_bytes(b'{"m":2}'))
    with pytest.raises(st.OrphanUnverifiable):
        tx.adopt_orphan_observation(mutant_id="m1", phase="discovery",
                                    outcome_bytes=b'{"m":1}', evidence=ev)
    assert "m1" not in tx.observations


def test_orphan_adoption_rejects_wrong_txid(fresh_dir):
    tx = _begun_tx(fresh_dir)
    outcome = b'{"m":1}'
    ev = _evidence(tx, "m1", st.sha256_bytes(outcome), txid="0" * 64)
    with pytest.raises(st.OrphanUnverifiable):
        tx.adopt_orphan_observation(mutant_id="m1", phase="discovery",
                                    outcome_bytes=outcome, evidence=ev)
    assert "m1" not in tx.observations


def test_torn_exec_receipt_fails_closed(fresh_dir):
    """A torn execution receipt can hide a second execution: the orphan
    outcome cannot be proven, so the resume must fail closed rather
    than adopt or re-execute."""
    d = fresh_dir
    tx = _begun_tx(d)
    outcome = b'{"m":1}'
    append_exec_entry(d, _evidence(tx, "m1", st.sha256_bytes(outcome)))
    # Simulate a crash mid-append: torn trailing bytes, no newline.
    with open(exec_log_dir(d) / "exec_receipt.jsonl", "ab") as f:
        f.write(b'{"txid": "incomplete')
        f.flush()
        os.fsync(f.fileno())
    with pytest.raises(st.OrphanUnverifiable):
        scan_and_adopt_orphans(tx, d, [("m1", "discovery")])
    assert "m1" not in tx.observations


# --------------------------------------------------------------------------
# authorization-instance tests: distinct txids per fresh authorization,
# nonce recovered and verified on resume, cross-transaction adoption
# --------------------------------------------------------------------------

def test_two_fresh_transactions_have_different_txids(fresh_dir):
    """Identical receipt/code bindings, fresh authorization nonces ->
    different transaction IDs."""
    a = _begun_tx(fresh_dir / "a")
    b = _begun_tx(fresh_dir / "b")
    assert a.tx_nonce != b.tx_nonce
    assert a.txid != b.txid


def test_resume_recovers_same_nonce_and_txid(fresh_dir):
    """open() recovers the persisted authorization-instance value and
    re-derives the identical transaction ID."""
    tx = _begun_tx(fresh_dir)
    nonce, txid = tx.tx_nonce, tx.txid
    tx2 = st.ScientificTransaction.open(
        fresh_dir, receipt_sha256=FIXTURE_RECEIPT_SHA,
        code_hashes=code_hashes())
    assert tx2.tx_nonce == nonce
    assert tx2.txid == txid
    assert tx2.txid == st.derive_txid(FIXTURE_RECEIPT_SHA, code_hashes(),
                                      nonce)


def test_adopt_cross_transaction_evidence_fails_closed(fresh_dir):
    """A's valid orphan evidence is foreign to B: B must fail closed --
    never adopt, never silently re-execute."""
    txA = _begun_tx(fresh_dir / "a")
    txB = _begun_tx(fresh_dir / "b")
    assert txA.txid != txB.txid
    outcome = b'{"m":1}'
    ev = _evidence(txA, "m1", st.sha256_bytes(outcome))
    # The evidence is genuinely valid for A: adoption succeeds there.
    txA.adopt_orphan_observation(mutant_id="m1", phase="discovery",
                                 outcome_bytes=outcome, evidence=ev)
    assert "m1" in txA.observations
    # The same evidence is rejected by B on the txid binding.
    with pytest.raises(st.OrphanUnverifiable):
        txB.adopt_orphan_observation(mutant_id="m1", phase="discovery",
                                     outcome_bytes=outcome, evidence=ev)
    assert "m1" not in txB.observations
    assert txB.pending(["m1"]) == ["m1"]
