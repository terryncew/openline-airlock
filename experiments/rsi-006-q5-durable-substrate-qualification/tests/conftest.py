"""Shared fixtures for RSI-006-Q5 tests.

All durable state lives under the repository (never /tmp): the
transaction layer, the ledger, and the driver all refuse ephemeral
work directories by design.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
EXP_DIR = TESTS_DIR.parent
Q4_DIR = EXP_DIR.parent / "rsi-006-q4-durable-transaction"
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
SCRATCH_ROOT = TESTS_DIR / "_scratch"

for _d in (str(EXP_DIR), str(Q4_DIR), str(Q3_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import stransaction as st  # noqa: E402
import execution_ledger as ledger  # noqa: E402
import q5_adapter as qa  # noqa: E402
from contact import ContactGate  # noqa: E402

DRIVER = TESTS_DIR / "fixture_driver.py"

FIXTURE_RECEIPT_SHA256 = hashlib.sha256(
    b"rsi-006-q5-fixture-receipt").hexdigest()


def fresh_nonce() -> str:
    return os.urandom(32).hex()


@pytest.fixture()
def work_dir(tmp_path_factory, request):
    d = SCRATCH_ROOT / f"{request.node.name}-{os.getpid()}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def bindings():
    return {
        "receipt_sha256": FIXTURE_RECEIPT_SHA256,
        "code_hashes": {
            "stransaction.py": hashlib.sha256(
                (Q4_DIR / "stransaction.py").read_bytes()).hexdigest(),
            "execution_ledger.py": hashlib.sha256(
                (EXP_DIR / "execution_ledger.py").read_bytes()).hexdigest(),
            "q5_adapter.py": hashlib.sha256(
                (EXP_DIR / "q5_adapter.py").read_bytes()).hexdigest(),
        },
    }


@pytest.fixture()
def tx(work_dir, bindings):
    return st.ScientificTransaction.begin(
        work_dir, receipt_sha256=bindings["receipt_sha256"],
        code_hashes=bindings["code_hashes"], tx_nonce=fresh_nonce())


def run_driver(work_dir: Path, *args, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DRIVER), "--work-dir", str(work_dir),
         "--tx-nonce", fresh_nonce(), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        timeout=timeout)


def run_driver_with_nonce(work_dir: Path, tx_nonce: str, *args,
                          timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DRIVER), "--work-dir", str(work_dir),
         "--tx-nonce", tx_nonce, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        timeout=timeout)


def marker_dir(work_dir: Path) -> Path:
    return work_dir / "exec_markers"


def marker_nonces(work_dir: Path) -> set:
    d = marker_dir(work_dir)
    if not d.exists():
        return set()
    return {p.stem for p in d.glob("*.json")}


def wait_for_markers(work_dir: Path, count: int, timeout=30) -> set:
    deadline = time.time() + timeout
    while time.time() < deadline:
        nonces = marker_nonces(work_dir)
        if len(nonces) >= count:
            return nonces
        time.sleep(0.05)
    raise TimeoutError(
        f"only {len(marker_nonces(work_dir))} markers after {timeout}s")


def ledger_outcome(work_dir: Path, observation_id: str) -> dict:
    p = (work_dir / "artifacts" / "execution_ledger"
         / f"{observation_id}.outcome.json")
    return json.loads(p.read_bytes())


def journal_types(work_dir: Path) -> list:
    types = []
    for p in sorted((work_dir / "journal").glob("*.json")):
        try:
            types.append(json.loads(p.read_bytes()).get("type"))
        except ValueError:
            types.append("<unparseable>")
    return types


def restart_entry_count(work_dir: Path) -> int:
    """Count durable ``restart`` entries straight from the journal files.

    Reads the raw journal (no ``ScientificTransaction.open()``), because
    opening would itself append a restart entry and corrupt the count.
    """
    return sum(1 for t in journal_types(work_dir) if t == "restart")


def ledger_record(work_dir: Path, observation_id: str, kind: str) -> dict:
    p = (work_dir / "artifacts" / "execution_ledger"
         / f"{observation_id}.{kind}.json")
    return json.loads(p.read_bytes())


def ledger_record_path(work_dir: Path, observation_id: str,
                       kind: str) -> Path:
    return (work_dir / "artifacts" / "execution_ledger"
            / f"{observation_id}.{kind}.json")


def reopen_tx(work_dir: Path, bindings) -> st.ScientificTransaction:
    return st.ScientificTransaction.open(
        work_dir, receipt_sha256=bindings["receipt_sha256"],
        code_hashes=bindings["code_hashes"])
