"""Uninterrupted fixture full run through the Q5 Stage2Runner.

A synthetic 45-group package (the smallest that passes the frozen Q3
feasibility guard at fixture budget 36) runs the complete mechanism:
receipt verification, static guard, transaction begin, discovery,
seals, confirmation nonce, confirmation, det-reruns, evaluation,
verdict, report. All fixture-only; no production state.
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(EXP_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_rsi_006_q3 as q3_run  # noqa: E402
from q5_fixture_support import (  # noqa: E402
    BUDGETS, CONF_N, DA_N, DB_N, DET_N, N_GROUPS, REPO_NAME,
    build_fixture_receipt, build_fullrun_package, build_tiny_package,
    contact_events, journal_entries, make_runner, observation_commits,
    repo_cfg)

SCRATCH = EXP_DIR / "tests" / "_scratch"


@pytest.fixture(scope="module")
def fx():
    # Module scope (one ~40s full run shared by all tests), but NOT
    # under /tmp: Q4 refuses ephemeral transaction roots.
    work = SCRATCH / f"fullrun-{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    repo_root = work / "repo"
    build_fullrun_package(repo_root)
    cfg = repo_cfg(repo_root)
    receipt_path = build_fixture_receipt(
        work, {REPO_NAME: cfg}, sys.executable)
    stage2 = work / "stage2"
    runner = make_runner(stage2, receipt_path, {REPO_NAME: cfg},
                         workers=4)
    result = runner.run()
    report = json.loads((stage2 / "report.json").read_bytes())
    yield {"work": work, "repo_root": repo_root, "cfg": cfg,
           "receipt_path": receipt_path, "stage2": stage2,
           "runner": runner, "result": result, "report": report}
    shutil.rmtree(work, ignore_errors=True)


def test_fullrun_reaches_terminal_verdict(fx):
    assert fx["result"]["status"] == "complete"
    assert fx["result"]["terminal"] in (
        "QUALIFIED_RSI_006_Q5_SUBSTRATE", "NOT_QUALIFIED_RSI_006_Q5_SUBSTRATE")
    report = fx["report"]
    assert report["stage"] == "complete"
    assert report["verdict"]["terminal"] == fx["result"]["terminal"]
    assert (fx["stage2"] / "report.json").exists()


def test_fullrun_observation_counts(fx):
    """Every planned observation committed exactly once."""
    report = fx["report"]
    obs = report["observations"]
    n_disc = DA_N + DB_N
    n_conf = CONF_N
    n_det = DET_N
    assert len(obs) == n_disc + n_conf + n_det
    ids = [o["observation_id"] for o in obs]
    assert len(set(ids)) == len(ids), "duplicate observation IDs"
    commits = observation_commits(fx["stage2"])
    assert len(commits) == len(obs), \
        f"{len(commits)} journal commits != {len(obs)} observations"
    # Discovery + confirmation observations each name a distinct
    # artifact digest ...
    primary = [o for o in obs
               if not o["observation_id"].startswith("det-rerun-")]
    digests = [o["artifact_sha256"] for o in primary]
    assert len(set(digests)) == len(digests), \
        "two primary observations share an artifact digest"
    # ... and each det-rerun's artifact is byte-identical to the
    # discovery observation it replays: that equality IS the
    # determinism claim.
    by_id = {o["observation_id"]: o for o in obs}
    for o in obs:
        if o["observation_id"].startswith("det-rerun-"):
            orig_id = o["observation_id"][len("det-rerun-"):]
            assert o["artifact_sha256"] == \
                by_id[orig_id]["artifact_sha256"], \
                f"det-rerun {o['observation_id']} diverged from {orig_id}"


def test_fullrun_exactly_one_contact_before_observations(fx):
    """One ContactGate winner, journaled before any observation."""
    contacts = contact_events(fx["stage2"])
    assert len(contacts) == 1, \
        f"expected exactly one contact event, got {len(contacts)}"
    first_obs_seq = min(e["seq"] for e in observation_commits(fx["stage2"]))
    assert contacts[0]["seq"] < first_obs_seq, \
        "contact journal entry is not before the observations"
    assert fx["report"]["contact_entries"], "report names no contact"


def test_fullrun_no_duplicate_executions(fx):
    """No completed execution nonce repeats; one start per observation."""
    stage2 = fx["stage2"]
    ledger_dir = stage2 / "artifacts" / "execution_ledger"
    nonces = []
    for o in fx["report"]["observations"]:
        started = json.loads(
            (ledger_dir / f"{o['observation_id']}.started.json")
            .read_bytes())
        nonces.append(started["exec_nonce"])
        assert o["exec_nonce"] == started["exec_nonce"]
        # Exactly one started record per observation: no filename
        # variants, no second attempt.
        matches = list(ledger_dir.glob(f"{o['observation_id']}.started.json"))
        assert len(matches) == 1
    assert len(set(nonces)) == len(nonces), \
        "a completed execution nonce repeated"


def test_fullrun_seals_and_nonce(fx):
    """Discovery seals committed; confirmation nonce committed once."""
    report = fx["report"]
    assert len(report["discovery_seals"]) == 1
    seal = report["discovery_seals"][0]
    assert seal["repo"] == REPO_NAME
    assert len(seal["member_ids"]) == DA_N + DB_N
    assert len(seal["seal"]) == 64
    nonce = report["confirmation_nonce"]
    assert nonce is not None and len(nonce) == 64
    nonce_entries = [e for e in journal_entries(fx["stage2"])
                     if isinstance(e, dict) and e.get("type") == "nonce"]
    assert len(nonce_entries) == 1, "confirmation nonce committed != once"
    # The seal recomputes from the committed member records (Q3 input
    # ordering: A members then B members, canonical bytes).
    assert report["evaluation"]["repos"][REPO_NAME]["discovery_seal"] == \
        seal["seal"]


def test_fullrun_det_rerun_agreement(fx):
    assert fx["report"]["evaluation"]["repos"][REPO_NAME][
        "det_rerun_agreement"] == 1.0


def test_fullrun_verdict_artifact_journal_bound(fx):
    """The Q4 verdict artifact bytes match the journal-bound digest."""
    verdict_entries = [e for e in journal_entries(fx["stage2"])
                       if isinstance(e, dict) and e.get("type") == "verdict"]
    assert len(verdict_entries) == 1, "verdict committed != once"
    artifact = (fx["stage2"] / "artifacts" / "report.json").read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == \
        verdict_entries[0]["payload"]["report_digest"]
    assert verdict_entries[0]["payload"]["verdict"] == \
        fx["result"]["terminal"]


def test_fullrun_results_digest_stable(fx):
    """The Q4 results digest binds the committed observation digests."""
    report = fx["report"]
    assert len(report["results_digest"]) == 64
    assert fx["report"]["restart_count"] == 0


def test_fullrun_existing_verdict_performs_no_execution(fx):
    """A second run sees the verdict and performs zero execution."""
    before = observation_commits(fx["stage2"])
    n_contacts_before = len(contact_events(fx["stage2"]))
    report_before = fx["report"]
    runner2 = make_runner(fx["stage2"], fx["receipt_path"],
                          {REPO_NAME: fx["cfg"]}, workers=4)
    result2 = runner2.run()
    assert result2["status"] == "complete"
    assert result2["terminal"] == fx["result"]["terminal"]
    after = observation_commits(fx["stage2"])
    assert len(after) == len(before), \
        "existing-verdict run journaled new observations"
    assert len(contact_events(fx["stage2"])) == n_contacts_before
    report2 = json.loads((fx["stage2"] / "report.json").read_bytes())
    # Canonical scientific content is unchanged; only operational
    # metadata (duration, restart count) may move.
    assert report2["results_digest"] == report_before["results_digest"]
    assert report2["discovery_seals"] == report_before["discovery_seals"]
    assert report2["confirmation_nonce"] == \
        report_before["confirmation_nonce"]
    assert report2["verdict"]["terminal"] == \
        report_before["verdict"]["terminal"]


def test_precontact_guard_failure_writes_no_transaction(work_dir):
    """A package that fails the static guard: pre-contact outcome only."""
    repo_root = work_dir / "tiny"
    build_tiny_package(repo_root)
    cfg = repo_cfg(repo_root)
    receipt_path = build_fixture_receipt(work_dir, {REPO_NAME: cfg},
                                         sys.executable)
    stage2 = work_dir / "stage2"
    budgets = {REPO_NAME: (36, 36, 2, 4)}
    runner = make_runner(stage2, receipt_path, {REPO_NAME: cfg},
                         budgets=budgets)
    result = runner.run()
    assert result["status"] == "precontact"
    assert result["outcome"] == "INCONCLUSIVE_RSI_006_Q5_PRECONDITION_FAILURE"
    body = json.loads((work_dir / "stage2" / "precontact-report.json")
                      .read_bytes())
    assert body["stage"] == "pre-contact"
    assert body["precondition_failures"], "guard failure not named"
    # No transaction was created: no journal, no nonce, no contact.
    assert not (stage2 / "journal").exists(), \
        "guard failure must not create a transaction journal"
    assert not (stage2 / "contact_marker.json").exists()
