"""Launch/provenance evidence is fully restart-verifiable.

Every committed observation carries a launch/provenance sidecar bound by
a journaled launch digest; adopted observations additionally persist the
exact orphan-evidence record relied upon, bound by a journaled evidence
digest. open() verifies all three artifact classes (outcome, launch,
adoption evidence) against the journal on every resume. Missing or
tampered launch sidecars and missing or tampered adopted-evidence
artifacts fail closed.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stransaction as st

RECEIPT = "c" * 64
CODE_HASHES = {"stransaction.py": "h" * 64}

TESTS_DIR = Path(__file__).resolve().parent
SCRATCH = TESTS_DIR / ".scratch-provenance"


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


def _begun_tx(d: Path):
    return st.ScientificTransaction.begin(
        d, receipt_sha256=RECEIPT, code_hashes=CODE_HASHES,
        tx_nonce=os.urandom(32).hex())


def _open(d: Path):
    return st.ScientificTransaction.open(
        d, receipt_sha256=RECEIPT, code_hashes=CODE_HASHES)


def _commit(tx, mid: str = "m1"):
    return tx.commit_observation(mutant_id=mid, phase="discovery",
                                 canonical=b'{"m":1}',
                                 launch={"restart_count": 0, "pid": 7})


def _adopt(tx, mid: str = "m1"):
    outcome = b'{"m":9}'
    evidence = {
        "txid": tx.txid,
        "observation_id": mid,
        "phase": "discovery",
        "outcome_digest": st.sha256_bytes(outcome),
        "receipt_sha256": RECEIPT,
        "code_hashes": dict(CODE_HASHES),
        "launch": {"restart_count": 0, "pid": 7},
    }
    tx.adopt_orphan_observation(mutant_id=mid, phase="discovery",
                                outcome_bytes=outcome, evidence=evidence)


def _tamper(path: Path):
    blob = bytearray(path.read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    path.write_bytes(bytes(blob))


# --- ordinary observations: launch sidecar verification --------------------

def test_missing_launch_sidecar_fails_closed(fresh_dir):
    tx = _begun_tx(fresh_dir)
    _commit(tx)
    (fresh_dir / "artifacts" / "launches" / "m1.json").unlink()
    with pytest.raises(st.CheckpointCorrupt):
        _open(fresh_dir)


def test_tampered_launch_sidecar_fails_closed(fresh_dir):
    tx = _begun_tx(fresh_dir)
    _commit(tx)
    _tamper(fresh_dir / "artifacts" / "launches" / "m1.json")
    with pytest.raises(st.CheckpointCorrupt):
        _open(fresh_dir)


def test_intact_launch_sidecar_resumes(fresh_dir):
    """Positive control: an untouched launch sidecar verifies and the
    resume succeeds."""
    tx = _begun_tx(fresh_dir)
    d = _commit(tx)
    tx2 = _open(fresh_dir)
    assert tx2.observations == {"m1": d}


# --- adopted observations: outcome + launch + evidence verification --------

def test_missing_adoption_evidence_fails_closed(fresh_dir):
    tx = _begun_tx(fresh_dir)
    _adopt(tx)
    (fresh_dir / "artifacts" / "adoption_evidence" / "m1.json").unlink()
    with pytest.raises(st.CheckpointCorrupt):
        _open(fresh_dir)


def test_tampered_adoption_evidence_fails_closed(fresh_dir):
    tx = _begun_tx(fresh_dir)
    _adopt(tx)
    _tamper(fresh_dir / "artifacts" / "adoption_evidence" / "m1.json")
    with pytest.raises(st.CheckpointCorrupt):
        _open(fresh_dir)


def test_tampered_adopted_launch_sidecar_fails_closed(fresh_dir):
    tx = _begun_tx(fresh_dir)
    _adopt(tx)
    _tamper(fresh_dir / "artifacts" / "launches" / "m1.json")
    with pytest.raises(st.CheckpointCorrupt):
        _open(fresh_dir)


def test_missing_adopted_outcome_fails_closed(fresh_dir):
    tx = _begun_tx(fresh_dir)
    _adopt(tx)
    (fresh_dir / "artifacts" / "observations" / "m1.json").unlink()
    with pytest.raises(st.CheckpointCorrupt):
        _open(fresh_dir)


def test_intact_adoption_resumes_with_all_artifacts(fresh_dir):
    """Positive control: adopted outcome, launch sidecar, and evidence
    artifact all verify on resume."""
    tx = _begun_tx(fresh_dir)
    _adopt(tx)
    tx2 = _open(fresh_dir)
    assert "m1" in tx2.observations
    assert tx2.pending(["m1"]) == []
