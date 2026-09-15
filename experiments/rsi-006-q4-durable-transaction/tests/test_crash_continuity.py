"""RSI-006-Q4 crash-continuity contract tests.

Deterministic fixtures only: no real repositories, no real mutants, no
scientific contact. Termination is injected as a real ``os._exit(1)`` in
a driver subprocess; resume runs in a fresh process on the same work
directory (which is never under /tmp).

For every recoverable crash point: resumed canonical results digest and
verdict must equal the uninterrupted control exactly; launch metadata
may differ and must record the restart.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXP_DIR))
import stransaction as st

DRIVER = EXP_DIR / "tests" / "fixture_driver.py"
SCRATCH = Path(__file__).resolve().parent / ".scratch"

CRASH_POINTS = [
    "after_contact",
    "after_discovery_seal",
    "after_nonce_commit",
    "mid_confirmation",
    "before_verdict_commit",
    "mid_verdict_commit",
]


def run_driver(work_dir: Path, crash_point: str | None = None):
    cmd = [sys.executable, str(DRIVER), "--work-dir", str(work_dir)]
    if crash_point:
        cmd += ["--crash-point", crash_point]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def parse_summary(cp) -> dict:
    out = {}
    for line in cp.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


@pytest.fixture(scope="session", autouse=True)
def scratch_root():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    yield SCRATCH
    # Keep the evidence on failure for inspection; clean on success is
    # handled per-test. Session teardown removes leftovers.
    import shutil
    shutil.rmtree(SCRATCH, ignore_errors=True)


@pytest.fixture()
def fresh_dir(scratch_root, request):
    d = scratch_root / request.node.name
    if d.exists():
        import shutil
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


@pytest.fixture(scope="session")
def control(scratch_root):
    d = scratch_root / "control"
    if d.exists():
        import shutil
        shutil.rmtree(d)
    d.mkdir(parents=True)
    cp = run_driver(d)
    assert cp.returncode == 0, cp.stderr
    s = parse_summary(cp)
    assert s["VERDICT"] in ("QUALIFIED_FIXTURE", "NOT_QUALIFIED_FIXTURE")
    assert s["MAX_RESTART_COUNT"] == "0"
    return s


def journal_entries(work_dir: Path) -> list[dict]:
    entries = []
    for p in sorted((work_dir / "journal").glob("[0-9]*.json")):
        entries.append(json.loads(p.read_bytes()))
    return entries


def assert_clean_resume(work_dir: Path) -> None:
    """Exactly one contact event; no observation committed twice."""
    entries = journal_entries(work_dir)
    assert sum(1 for e in entries if e["type"] == "contact") == 1
    seen: dict[str, int] = {}
    for e in entries:
        if e["type"] == "observation":
            mid = e["payload"]["mutant_id"]
            seen[mid] = seen.get(mid, 0) + 1
    assert seen and all(v == 1 for v in seen.values()), seen
    assert sum(1 for e in entries if e["type"] == "nonce") == 1


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_crash_point_resumes_equal(control, fresh_dir, point):
    cp1 = run_driver(fresh_dir, crash_point=point)
    assert cp1.returncode == 1, (point, cp1.stderr)
    cp2 = run_driver(fresh_dir)
    assert cp2.returncode == 0, (point, cp2.stderr)
    r = parse_summary(cp2)
    assert r["CANONICAL_DIGEST"] == control["CANONICAL_DIGEST"], point
    assert r["VERDICT"] == control["VERDICT"], point
    assert r["NONCE"] == control["NONCE"], point
    assert r["TXID"] == control["TXID"], point
    assert r["CONTACT_MID"] == control["CONTACT_MID"], point
    assert int(r["MAX_RESTART_COUNT"]) >= 1, point
    assert_clean_resume(fresh_dir)


def test_double_crash_resumes_equal(control, fresh_dir):
    cp1 = run_driver(fresh_dir, crash_point="after_contact")
    assert cp1.returncode == 1
    cp2 = run_driver(fresh_dir, crash_point="mid_confirmation")
    assert cp2.returncode == 1
    cp3 = run_driver(fresh_dir)
    assert cp3.returncode == 0, cp3.stderr
    r = parse_summary(cp3)
    assert r["CANONICAL_DIGEST"] == control["CANONICAL_DIGEST"]
    assert r["VERDICT"] == control["VERDICT"]
    assert int(r["MAX_RESTART_COUNT"]) >= 2
    assert_clean_resume(fresh_dir)


# --------------------------------------------------------------------------
# negative tests: fail closed, reject duplicates
# --------------------------------------------------------------------------

def _unit_tx(d: Path, receipt: str = "a" * 64):
    return st.ScientificTransaction.begin(
        d, receipt_sha256=receipt, code_hashes={"k": "v"})


def _unit_open(d: Path, receipt: str = "a" * 64):
    return st.ScientificTransaction.open(
        d, receipt_sha256=receipt, code_hashes={"k": "v"})


def test_tampered_journal_fails_closed(fresh_dir):
    tx = _unit_tx(fresh_dir)
    tx.commit_observation(mutant_id="m1", phase="discovery",
                          canonical=b'{"m":1}', launch={})
    entry = fresh_dir / "journal" / "00000002.json"
    blob = bytearray(entry.read_bytes())
    blob[60] ^= 0xFF
    entry.write_bytes(bytes(blob))
    with pytest.raises(st.CheckpointCorrupt):
        _unit_open(fresh_dir)


def test_tampered_artifact_fails_closed(fresh_dir):
    tx = _unit_tx(fresh_dir)
    tx.commit_observation(mutant_id="m1", phase="discovery",
                          canonical=b'{"m":1}', launch={})
    art = fresh_dir / "artifacts" / "observations" / "m1.json"
    art.write_bytes(b'{"m":2}')
    with pytest.raises(st.CheckpointCorrupt):
        _unit_open(fresh_dir)


def test_receipt_binding_drift_fails_closed(fresh_dir):
    _unit_tx(fresh_dir)
    with pytest.raises(st.BindingMismatch):
        _unit_open(fresh_dir, receipt="b" * 64)


def test_code_hash_binding_drift_fails_closed(fresh_dir):
    _unit_tx(fresh_dir)
    with pytest.raises(st.BindingMismatch):
        st.ScientificTransaction.open(
            fresh_dir, receipt_sha256="a" * 64, code_hashes={"k": "CHANGED"})


def test_duplicate_observation_rejected(fresh_dir):
    tx = _unit_tx(fresh_dir)
    tx.commit_observation(mutant_id="m1", phase="discovery",
                          canonical=b'{"m":1}', launch={})
    with pytest.raises(st.DuplicateWork):
        tx.commit_observation(mutant_id="m1", phase="discovery",
                              canonical=b'{"m":1}', launch={})


def test_duplicate_nonce_rejected(fresh_dir):
    tx = _unit_tx(fresh_dir)
    tx.commit_nonce(nonce_hex="cd" * 32)
    with pytest.raises(st.DuplicateWork):
        tx.commit_nonce(nonce_hex="ef" * 32)
    assert tx.nonce == "cd" * 32


def test_contact_exactly_once_across_restart(fresh_dir):
    tx = _unit_tx(fresh_dir)
    r1 = tx.note_contact(mutant_id="c1", child_pid=111)
    assert r1["created"] is True
    # "Restart": reopen and attempt contact again.
    tx2 = _unit_open(fresh_dir)
    r2 = tx2.note_contact(mutant_id="c2", child_pid=222)
    assert r2["created"] is False
    assert r2["event"]["mutant_id"] == "c1"
    assert r2["event"]["child_pid"] == 111
    assert sum(1 for e in journal_entries(fresh_dir)
               if e["type"] == "contact") == 1


def test_tmp_work_dir_refused():
    with pytest.raises(st.TransactionError):
        st.ScientificTransaction.begin("/tmp/q4-must-not-exist",
                                       receipt_sha256="a" * 64,
                                       code_hashes={})


def test_begin_over_existing_journal_refused(fresh_dir):
    _unit_tx(fresh_dir)
    with pytest.raises(st.TransactionError):
        _unit_tx(fresh_dir)


def test_seal_requires_all_members_committed(fresh_dir):
    tx = _unit_tx(fresh_dir)
    tx.commit_observation(mutant_id="m1", phase="discovery",
                          canonical=b'{"m":1}', launch={})
    with pytest.raises(st.TransactionError):
        tx.commit_discovery_seal(repo="r", seal="s", member_ids=["m1", "m2"])


def test_self_check_passes():
    cp = subprocess.run([sys.executable, str(EXP_DIR / "self_check.py")],
                        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stderr + cp.stdout
    assert "self-check clean" in cp.stdout
