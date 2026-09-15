"""Crash/resume convergence through the Q5 Stage2Runner.

Crashes are injected in a SUBPROCESS (``tests/q5_crash_driver.py``):
adapter crash windows kill via ``os._exit`` and phase-level hooks
raise ``qa._Crash`` -- either would kill an in-process test runner.
The test then resumes in-process on the same stage2 dir and asserts
the resumed run converges to the uninterrupted canonical
report/verdict.

Recoverable points: after_first_contact, partial_discovery,
after_discovery, after_seal, after_nonce, mid_confirmation,
after_confirmation, after_det_rerun, pre_verdict, verdict_gap. The
fail-closed window (crash after a real child start but before its
completion is durable) is asserted separately: resume must raise
``UncertainExecution`` and never rerun.

Nonce oracle (2026-09-15): the terminal verdict depends on Q-FRESH,
which samples confirmation mutants from the per-run confirmation
nonce -- so an independent-nonce reference is not a valid oracle for
the verdict. The reference run and every crash variant therefore share
one fixed fixture confirmation nonce (``FIXTURE_NONCE``), injected
through the runner's internal test-only ``confirmation_nonce_source``
(no CLI flag; production always uses OS entropy). The oracle then
compares runs under identical confirmation randomness: same receipt,
same frozen constants, same discovery state, same planned
observations, different interruption history -- and requires identical
canonical observations, seals, nonce, final report digest, and
verdict. Per-case nonce-source call tags additionally prove the
successor never mints a second nonce: crash points before nonce
creation see exactly one source call (on resume); points after the
nonce commit see exactly one call (in the doomed run) and the resume
reuses the journaled nonce without calling the source again.

Sampling variance, documented: two runs with deliberately different
confirmation nonces are NOT required to agree on Q-FRESH or the
verdict (see test_q5_runner_nonce_semantics.py). That is expected
confirmation sampling variance on the toy fixture, not a runner
defect.
"""

import hashlib
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
from execution_ledger import UncertainExecution  # noqa: E402
from q5_fixture_support import (  # noqa: E402
    CONF_N, DA_N, DB_N, DET_N, REPO_NAME,
    build_fixture_receipt, build_fullrun_package,
    contact_events, journal_entries, make_runner, observation_commits,
    repo_cfg)

DRIVER = EXP_DIR / "tests" / "q5_crash_driver.py"
SCRATCH = EXP_DIR / "tests" / "_scratch"

# One fixed valid 64-hex fixture confirmation nonce, shared by the
# uninterrupted reference run and every crash variant. Pinning the
# nonce pins the confirmation sampling, so the oracle tests
# interruption history -- not randomness.
FIXTURE_NONCE = "deadbeef" * 8
assert len(FIXTURE_NONCE) == 64 and all(
    c in "0123456789abcdef" for c in FIXTURE_NONCE)


class _NonceSourceSpy:
    """Test-only counting confirmation-nonce source.

    Returns the fixed fixture nonce and appends one line per call to
    ``count_path``, so nonce-source calls in the doomed subprocess and
    the resume process are distinguishable across the process boundary.
    """

    def __init__(self, value: str, count_path: Path, tag: str):
        self._value = value
        self._count_path = Path(count_path)
        self._tag = tag

    def __call__(self) -> str:
        with open(self._count_path, "a") as fh:
            fh.write(self._tag + "\n")
        return self._value


# (case name, crash points for the doomed run, nonce phase:
#  "pre"  = crash before the confirmation nonce is created --
#           the source must be called exactly once, on resume;
#  "post" = crash after the nonce is committed --
#           the source must have been called exactly once, in the
#           doomed run, and never again on resume.)
CRASH_MATRIX = [
    ("after_first_contact", {"after_first_contact": True}, "pre"),
    ("partial_discovery", {"partial_discovery": True}, "pre"),
    ("after_discovery", {"after_discovery": True}, "pre"),
    ("after_seal", {"after_seal:fx-pool": True}, "pre"),
    ("after_nonce", {"after_nonce": True}, "post"),
    ("mid_confirmation", {"mid_confirmation": True}, "post"),
    ("after_confirmation", {"after_confirmation": True}, "post"),
    ("after_det_rerun", {"after_det_rerun": True}, "post"),
    ("pre_verdict", {"pre_verdict": True}, "post"),
    ("verdict_gap", {"verdict_gap": True}, "post"),
]


@pytest.fixture(scope="module")
def crash_env():
    work = SCRATCH / f"crash-{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    repo_root = work / "repo"
    build_fullrun_package(repo_root)
    cfg = repo_cfg(repo_root)
    receipt_path = build_fixture_receipt(work, {REPO_NAME: cfg},
                                         sys.executable)
    # The uninterrupted canonical reference, under the same fixed
    # fixture nonce as every crash variant.
    ref_stage2 = work / "ref" / "stage2"
    ref_runner = make_runner(ref_stage2, receipt_path, {REPO_NAME: cfg},
                             workers=1,
                             confirmation_nonce_source=lambda: FIXTURE_NONCE)
    ref_result = ref_runner.run()
    assert ref_result["status"] == "complete"
    ref_report = json.loads((ref_stage2 / "report.json").read_bytes())
    yield {"work": work, "repo_root": repo_root, "cfg": cfg,
           "receipt_path": receipt_path,
           "ref_stage2": ref_stage2, "ref_report": ref_report,
           "ref_result": ref_result}
    shutil.rmtree(work, ignore_errors=True)


def _doomed_run(env, case_name, crash_points, extra_env=None) -> Path:
    """Run the driver subprocess with crash points; expect it to die."""
    stage2 = env["work"] / f"case-{case_name}" / "stage2"
    run_env = dict(os.environ)
    if extra_env:
        run_env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(DRIVER), str(env["repo_root"]),
         str(env["receipt_path"]), str(stage2),
         json.dumps(crash_points)],
        cwd=str(EXP_DIR), timeout=900, env=run_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.returncode != 0, \
        f"case {case_name}: crash injection did not kill the driver " \
        f"(rc={proc.returncode}, stdout={proc.stdout!r})"
    assert "complete" not in proc.stdout, \
        f"case {case_name}: driver reported completion despite crash point"
    return stage2


def _discovery_record_digests(stage2: Path) -> dict[str, str]:
    digests = {}
    obs_dir = stage2 / "artifacts" / "observations"
    for path in sorted(obs_dir.glob("*.json")):
        obs_id = path.stem
        if obs_id.startswith(f"{REPO_NAME}-A-") \
                or obs_id.startswith(f"{REPO_NAME}-B-"):
            digests[obs_id] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _assert_converged(env, stage2: Path, result: dict, report: dict,
                      nonce_phase: str, count_path: Path):
    ref = env["ref_report"]
    # Same terminal verdict as the uninterrupted same-nonce run.
    assert result["status"] == "complete"
    assert result["terminal"] == ref["verdict"]["terminal"]
    assert report["verdict"]["terminal"] == ref["verdict"]["terminal"]
    # Exact final report digest equality: the resumed run converged to
    # the identical canonical result, not merely the same verdict.
    assert report["results_digest"] == ref["results_digest"], \
        "resumed results_digest != same-nonce reference digest"
    # Nonce-source call discipline across the process boundary.
    # "pre": crash before nonce creation -- the source is called exactly
    # once, on resume. "post": crash after the nonce commit -- the source
    # was called exactly once, in the doomed run, and the resume reuses
    # the journaled nonce without calling the source again.
    tags = count_path.read_text().split()
    expected = ["resumed"] if nonce_phase == "pre" else ["doomed"]
    assert tags == expected, \
        f"nonce source call tags {tags} != expected {expected}"
    assert report["confirmation_nonce"] == FIXTURE_NONCE
    # Exactly one restart: the one genuine successor.
    assert report["restart_count"] == 1, \
        f"restart_count={report['restart_count']}"
    # Exactly one ContactGate winner, journaled before observations.
    contacts = contact_events(stage2)
    assert len(contacts) == 1, f"{len(contacts)} contact events"
    commits = observation_commits(stage2)
    assert contacts[0]["seq"] < min(e["seq"] for e in commits)
    # No completed execution nonce repeats; one start per observation.
    ledger_dir = stage2 / "artifacts" / "execution_ledger"
    nonces = []
    for o in report["observations"]:
        started = json.loads(
            (ledger_dir / f"{o['observation_id']}.started.json")
            .read_bytes())
        assert o["exec_nonce"] == started["exec_nonce"]
        nonces.append(started["exec_nonce"])
    assert len(set(nonces)) == len(nonces), \
        "a completed execution nonce repeated"
    # Identical discovery seals (seeded determinism).
    assert report["discovery_seals"] == ref["discovery_seals"]
    # Identical canonical discovery records.
    assert _discovery_record_digests(stage2) == \
        _discovery_record_digests(env["ref_stage2"])
    # Determinism holds on the resumed run.
    assert report["evaluation"]["repos"][REPO_NAME][
        "det_rerun_agreement"] == 1.0
    # The confirmation nonce was committed exactly once and the
    # confirmation mutants are deterministic in it.
    nonce_entries = [e for e in journal_entries(stage2)
                     if isinstance(e, dict) and e.get("type") == "nonce"]
    assert len(nonce_entries) == 1
    nonce = report["confirmation_nonce"]
    assert nonce == nonce_entries[0]["payload"]["nonce"], \
        "report nonce != journal-committed nonce"
    expected_c = q3_perturb.generate_mutants(
        env["repo_root"] / "pkg", f"RSI-006-Q3-confirmation-{nonce}",
        CONF_N, f"{REPO_NAME}-C")
    expected_ids = sorted(m["mutant_id"] for m in expected_c)
    got_ids = sorted(o["mutant_id"] for o in report["observations"]
                     if o["observation_id"].startswith(f"{REPO_NAME}-C-"))
    assert got_ids == expected_ids


@pytest.mark.parametrize("case_name,crash_points,nonce_phase", CRASH_MATRIX,
                         ids=[c[0] for c in CRASH_MATRIX])
def test_crash_resume_converges(crash_env, case_name, crash_points,
                                nonce_phase):
    count_path = (crash_env["work"] / f"case-{case_name}"
                  / "nonce_calls.log")
    count_path.parent.mkdir(parents=True, exist_ok=True)
    stage2 = _doomed_run(crash_env, case_name, crash_points, {
        "Q5_FIXTURE_CONFIRMATION_NONCE": FIXTURE_NONCE,
        "Q5_FIXTURE_NONCE_COUNT_PATH": str(count_path),
        "Q5_FIXTURE_NONCE_TAG": "doomed",
    })
    resume_spy = _NonceSourceSpy(FIXTURE_NONCE, count_path, "resumed")
    runner = make_runner(stage2, crash_env["receipt_path"],
                         {REPO_NAME: crash_env["cfg"]}, workers=1,
                         confirmation_nonce_source=resume_spy)
    result = runner.run()
    report = json.loads((stage2 / "report.json").read_bytes())
    _assert_converged(crash_env, stage2, result, report, nonce_phase,
                      count_path)


def test_crash_after_real_child_start_fails_closed(crash_env):
    """Crash after the child started but before completion is durable.

    The child may have run; rerunning risks a second physical
    execution. Resume must fail closed with UncertainExecution --
    never rerun, never mint a verdict.
    """
    first_id = f"{REPO_NAME}-A-0000"
    stage2 = _doomed_run(crash_env, "after_started_failclosed",
                         {first_id: "after_started"})
    runner = make_runner(stage2, crash_env["receipt_path"],
                         {REPO_NAME: crash_env["cfg"]}, workers=1)
    with pytest.raises(UncertainExecution):
        runner.run()
    # The contact happened (exactly once); nothing was committed.
    assert len(contact_events(stage2)) == 1
    assert observation_commits(stage2) == []
    verdicts = [e for e in journal_entries(stage2)
                if isinstance(e, dict) and e.get("type") == "verdict"]
    assert verdicts == []
