"""Spawn-failure semantics through the Q5 Stage2Runner.

Frozen Q3 treats a Popen OSError as a completed canonical observation
(disposition launch_spawn_failed): the runner's scientific path must do
the same -- commit it normally, never retry it. A crash after the
spawn-failure completion is durable but before the Q4 commit must
adopt the exact first result with zero second Popen; a spawn_failed
without verified completion must fail closed, never retry.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(EXP_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import perturb as q3_perturb  # noqa: E402
import run_rsi_006_q3 as q3_run  # noqa: E402
import stransaction as st  # noqa: E402
import execution_ledger as ledger  # noqa: E402
from execution_ledger import UncertainExecution  # noqa: E402
from run_rsi_006_q5 import _code_hashes  # noqa: E402
from q5_fixture_support import (  # noqa: E402
    DA_N, REPO_NAME, build_fixture_receipt, build_fullrun_package,
    contact_events, journal_entries, make_runner, observation_commits,
    repo_cfg)

DRIVER = EXP_DIR / "tests" / "q5_crash_driver.py"
SCRATCH = EXP_DIR / "tests" / "_scratch"

FIXTURE_NONCE = "deadbeef" * 8
assert len(FIXTURE_NONCE) == 64


def _first_discovery_mutant(cfg: dict) -> dict:
    """The runner's first discovery mutant, recomputed identically.

    The runner generates ``generate_mutants(pkg, SEED_A, da_n,
    f"{name}-A")`` and runs A mutants first, so element zero is the
    first observation of the discovery phase.
    """
    mutants = q3_perturb.generate_mutants(
        Path(cfg["package_dir"]), q3_run.SEED_A, DA_N, f"{REPO_NAME}-A")
    assert mutants, "no discovery mutants generated"
    return mutants[0]


@pytest.fixture(scope="module")
def spawnfail_env():
    work = SCRATCH / f"spawnfail-{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    repo_root = work / "repo"
    build_fullrun_package(repo_root)
    cfg = repo_cfg(repo_root)
    receipt_path = build_fixture_receipt(work, {REPO_NAME: cfg},
                                         sys.executable)
    first = _first_discovery_mutant(cfg)
    yield {"work": work, "repo_root": repo_root, "cfg": cfg,
           "receipt_path": receipt_path,
           "first_id": first["mutant_id"], "first_mutant": first}
    shutil.rmtree(work, ignore_errors=True)


class _TaggedNonceSource:
    """Test-only counting confirmation-nonce source (in-process)."""

    def __init__(self, value: str, count_path: Path, tag: str):
        self._value = value
        self._count_path = Path(count_path)
        self._tag = tag

    def __call__(self) -> str:
        with open(self._count_path, "a") as fh:
            fh.write(self._tag + "\n")
        return self._value


def _doomed_spawnfail_run(env, extra_env: dict):
    """Doomed driver run: forced spawn failure on the first observation,
    then crash after its completion is durable. Expect death."""
    stage2 = env["work"] / "case-spawnfail" / "stage2"
    count_path = env["work"] / "spawn-count.txt"
    nonce_count = env["work"] / "nonce-count.txt"
    run_env = dict(os.environ)
    run_env.update({
        "Q5_FIXTURE_CONFIRMATION_NONCE": FIXTURE_NONCE,
        "Q5_FIXTURE_NONCE_COUNT_PATH": str(nonce_count),
        "Q5_FIXTURE_NONCE_TAG": "doomed",
        "Q5_FIXTURE_SPAWN_FAIL_OBS": env["first_id"],
        "Q5_FIXTURE_SPAWN_COUNT_PATH": str(count_path),
    })
    run_env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(DRIVER), str(env["repo_root"]),
         str(env["receipt_path"]), str(stage2),
         json.dumps({env["first_id"]: "after_spawn_failure_completion"})],
        cwd=str(EXP_DIR), timeout=900, env=run_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.returncode != 0, \
        f"crash injection did not kill the driver (rc={proc.returncode})"
    assert "complete" not in proc.stdout, \
        "driver reported completion despite crash point"
    return stage2, count_path, nonce_count


def test_spawn_failure_crash_adopt(spawnfail_env):
    """Crash after the spawn-failure completion is durable: resume adopts
    it with zero second Popen, and the run completes."""
    env = spawnfail_env
    stage2, count_path, nonce_count = _doomed_spawnfail_run(env, {})

    first_id = env["first_id"]
    ldir = stage2 / "artifacts" / "execution_ledger"
    # Doomed state: the proof, outcome, and completion are durable; no
    # child ever existed; nothing is journaled yet.
    assert (ldir / f"{first_id}.spawn_failed.json").exists()
    assert (ldir / f"{first_id}.complete.json").exists()
    assert not (ldir / f"{first_id}.started.json").exists()
    assert not any(
        e.get("payload", {}).get("mutant_id") == first_id
        for e in observation_commits(stage2)), \
        "spawn-failure observation journaled before the crash"

    # Resume in-process on the same stage2 dir.
    resume_runner = make_runner(
        stage2, env["receipt_path"], {REPO_NAME: env["cfg"]}, workers=1,
        confirmation_nonce_source=_TaggedNonceSource(
            FIXTURE_NONCE, nonce_count, "resumed"))
    result = resume_runner.run()
    assert result["status"] == "complete"
    report = json.loads((stage2 / "report.json").read_bytes())

    # The spawn-failure observation was adopted, not re-executed: the
    # journal carries an adoption entry for it.
    commits = observation_commits(stage2)
    adopted = [e for e in commits
               if e.get("type") == "observation_adopted"
               and e.get("payload", {}).get("mutant_id") == first_id]
    assert len(adopted) == 1, \
        f"expected one adoption of {first_id}, got {len(adopted)}"
    # Zero second Popen: the failed spawn was attempted exactly once,
    # in the doomed run.
    attempts = [l for l in count_path.read_text().split() if l == first_id]
    assert attempts == [first_id], \
        f"spawn re-attempted on resume: {attempts}"
    # The committed record is Q3's launch_spawn_failed canonical shape.
    artifact = json.loads(
        (stage2 / "artifacts" / "observations"
         / f"{first_id}.json").read_bytes())
    assert artifact["mutant_id"] == first_id
    assert artifact["outcomes"] == {}
    assert artifact["kill"] is True
    assert artifact["collection_error"] is True
    assert artifact["timeout"] is False
    # A no-child observation reports a null exec_nonce in the report.
    by_id = {o["observation_id"]: o for o in report["observations"]}
    assert by_id[first_id]["exec_nonce"] is None
    assert not (ldir / f"{first_id}.started.json").exists()
    # The rest of the run is healthy: one contact (from a later real
    # child), one restart, one nonce minted on resume. (det_rerun_agreement
    # is not asserted here: the det-rerun of the failed mutant is a fresh
    # observation with a working spawner, so it legitimately records the
    # real outcome instead of the forced spawn failure.)
    assert len(contact_events(stage2)) == 1
    assert report["restart_count"] == 1
    assert nonce_count.read_text().split() == ["resumed"]
    assert report["confirmation_nonce"] == FIXTURE_NONCE


def test_spawn_failure_without_completion_fails_closed(work_dir):
    """Ledger classify: scientific spawn_failed without verified
    completion fails closed; the generic path keeps retry_allowed."""
    tx = st.ScientificTransaction.begin(
        work_dir, receipt_sha256="f" * 64,
        code_hashes=_code_hashes(), tx_nonce=os.urandom(32).hex())
    obs_id = "fx-spawnfail-0001"
    bindings = dict(receipt_sha256="f" * 64, code_hashes=_code_hashes())
    ledger.record_prepared(
        work_dir=work_dir, txid=tx.txid, observation_id=obs_id,
        phase="discovery", attempt=1, pid=os.getpid(), **bindings)
    ledger.record_spawn_failed(
        work_dir=work_dir, txid=tx.txid, observation_id=obs_id,
        phase="discovery", attempt=1,
        error="OSError: fixture forced spawn failure", **bindings)
    # Scientific path: the spawn failure is already Q3's scored
    # observation -- fail closed, never retry.
    with pytest.raises(UncertainExecution):
        ledger.classify(
            work_dir=work_dir, tx=tx, observation_id=obs_id,
            phase="discovery", scientific=True, **bindings)
    # Generic path: unchanged, a genuine first attempt remains allowed.
    status, payload = ledger.classify(
        work_dir=work_dir, tx=tx, observation_id=obs_id,
        phase="discovery", scientific=False, **bindings)
    assert status == "retry_allowed"
    assert payload == {"attempt": 2}
