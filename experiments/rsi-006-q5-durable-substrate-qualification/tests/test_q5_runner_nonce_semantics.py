"""Production confirmation-nonce semantics (no fixture injection).

Proves the production path -- the runner's default OS-entropy source,
with NO test injection -- behaves exactly as specified:

1. a fresh transaction calls the real entropy source exactly once, when
   confirmation becomes eligible (after all discovery seals);
2. the nonce is committed to the journal before any confirmation mutant
   is generated or dispatched (journal seq ordering);
3. a resume with an existing committed nonce never calls the entropy
   source again and reuses the journaled nonce exactly;
4. two runs with deliberately different confirmation nonces are NOT
   required to agree on Q-FRESH or the terminal verdict.

On (4): the toy fixture draws CONF_N=4 confirmation mutants per nonce,
so the confirmation kill-rate sample varies with the nonce. That is
expected sampling variance, not a runner defect -- which is why the
crash/resume oracle pins one fixed fixture nonce (see
test_q5_runner_crash.py).

Fixture-only. No Stage 1, no production storage arming, no real repos.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = EXP_DIR / "tests"
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(TESTS_DIR), str(EXP_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import q5_adapter as qa  # noqa: E402
import run_rsi_006_q5 as runner_mod  # noqa: E402
from q5_fixture_support import (  # noqa: E402
    REPO_NAME,
    build_fixture_receipt,
    build_fullrun_package,
    journal_entries,
    make_runner,
    repo_cfg,
)

SCRATCH = EXP_DIR / "tests" / "_scratch"

NONCE_A = "aa" * 32
NONCE_B = "bb" * 32


def _build(tag: str):
    """Fresh fixture work dir with package, receipt, and config."""
    work = SCRATCH / f"nonce-sem-{tag}-{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    repo_root = work / "repo"
    build_fullrun_package(repo_root)
    cfg = repo_cfg(repo_root)
    receipt_path = build_fixture_receipt(work, {REPO_NAME: cfg},
                                         sys.executable)
    return {"work": work, "repo_root": repo_root, "cfg": cfg,
            "receipt_path": receipt_path}


@pytest.fixture(scope="module")
def prod_run():
    """One full fixture run with the REAL production entropy source.

    The module attribute is swapped for a counting wrapper around the
    real source for the duration of this fixture only; the runner binds
    it at construction time.
    """
    env = _build("prod")
    real = runner_mod._production_confirmation_nonce_source
    seen: list[str] = []

    def counting() -> str:
        value = real()
        seen.append(value)
        return value

    runner_mod._production_confirmation_nonce_source = counting
    try:
        stage2 = env["work"] / "stage2"
        runner = make_runner(stage2, env["receipt_path"],
                             {REPO_NAME: env["cfg"]}, workers=1)
        result = runner.run()
        assert result["status"] == "complete"
        report = json.loads((stage2 / "report.json").read_bytes())
        yield {"env": env, "stage2": stage2, "report": report,
               "seen": seen}
    finally:
        runner_mod._production_confirmation_nonce_source = real
        shutil.rmtree(env["work"], ignore_errors=True)


def test_production_source_called_exactly_once(prod_run):
    """No injection: the real entropy source fires exactly once per
    fresh transaction, when confirmation becomes eligible."""
    seen = prod_run["seen"]
    assert len(seen) == 1, \
        f"production entropy source called {len(seen)}x, expected 1"
    value = seen[0]
    assert len(value) == 64 and all(
        c in "0123456789abcdef" for c in value)
    # The committed nonce is exactly the generated value.
    nonces = [e for e in journal_entries(prod_run["stage2"])
              if isinstance(e, dict) and e.get("type") == "nonce"]
    assert len(nonces) == 1
    assert nonces[0]["payload"]["nonce"] == value
    assert prod_run["report"]["confirmation_nonce"] == value


def test_nonce_committed_before_confirmation_mutants(prod_run):
    """Journal ordering: the nonce entry precedes every confirmation
    observation commit -- the seed is fixed before any confirmation
    mutant is generated or dispatched."""
    entries = journal_entries(prod_run["stage2"])
    nonce_seqs = [e["seq"] for e in entries
                  if isinstance(e, dict) and e.get("type") == "nonce"]
    assert len(nonce_seqs) == 1
    conf_seqs = [e["seq"] for e in entries
                 if isinstance(e, dict)
                 and e.get("type") == "observation"
                 and e.get("payload", {}).get("mutant_id", "")
                 .startswith(f"{REPO_NAME}-C-")]
    assert conf_seqs, "no confirmation observation commits found"
    assert nonce_seqs[0] < min(conf_seqs), \
        f"nonce seq {nonce_seqs[0]} not before first confirmation " \
        f"commit seq {min(conf_seqs)}"


def test_resume_with_committed_nonce_never_calls_source():
    """A successor that finds a committed nonce never calls the entropy
    source and reuses the journaled nonce exactly."""
    env = _build("resume")
    try:
        stage2 = env["work"] / "stage2"
        doomed = make_runner(stage2, env["receipt_path"],
                             {REPO_NAME: env["cfg"]}, workers=1)
        with pytest.raises(qa._Crash):
            doomed.run(crash_points={"after_nonce": True})
        journal_nonce = [e for e in journal_entries(stage2)
                         if isinstance(e, dict)
                         and e.get("type") == "nonce"]
        assert len(journal_nonce) == 1
        committed = journal_nonce[0]["payload"]["nonce"]

        real = runner_mod._production_confirmation_nonce_source
        seen: list[str] = []

        def counting() -> str:
            value = real()
            seen.append(value)
            return value

        runner_mod._production_confirmation_nonce_source = counting
        try:
            resumed = make_runner(stage2, env["receipt_path"],
                                  {REPO_NAME: env["cfg"]}, workers=1)
            result = resumed.run()
        finally:
            runner_mod._production_confirmation_nonce_source = real
        assert result["status"] == "complete"
        assert seen == [], \
            f"resume called the entropy source {len(seen)}x"
        report = json.loads((stage2 / "report.json").read_bytes())
        assert report["confirmation_nonce"] == committed
        nonces = [e for e in journal_entries(stage2)
                  if isinstance(e, dict) and e.get("type") == "nonce"]
        assert len(nonces) == 1, "resume must never mint a second nonce"
    finally:
        shutil.rmtree(env["work"], ignore_errors=True)


def _fullrun_with_nonce(tag: str, nonce: str):
    env = _build(tag)
    stage2 = env["work"] / "stage2"
    runner = make_runner(stage2, env["receipt_path"],
                         {REPO_NAME: env["cfg"]}, workers=1,
                         confirmation_nonce_source=lambda: nonce)
    result = runner.run()
    assert result["status"] == "complete"
    report = json.loads((stage2 / "report.json").read_bytes())
    return env, report


def _confirmation_samples(stage2: Path):
    """The (operator, site_key) pairs actually sampled for
    confirmation -- what the nonce drives. Mutant IDs are sequential
    labels; the sample content is in the canonical records."""
    art = Path(stage2) / "artifacts" / "observations"
    samples = []
    for path in sorted(art.glob("fx-pool-C-*.json")):
        rec = json.loads(path.read_bytes())
        samples.append((rec["operator"], rec["site_key"]))
    return sorted(samples)


def test_different_nonces_not_required_to_agree():
    """Expected sampling variance, pinned: two runs with deliberately
    different confirmation nonces draw different confirmation mutant
    samples and are NOT required to produce the same Q-FRESH result or
    verdict. This is the fixture's confirmation sampling behaving as
    designed -- not a runner defect."""
    env_a, rep_a = _fullrun_with_nonce("nonceA", NONCE_A)
    env_b, rep_b = _fullrun_with_nonce("nonceB", NONCE_B)
    try:
        samples_a = _confirmation_samples(env_a["work"] / "stage2")
        samples_b = _confirmation_samples(env_b["work"] / "stage2")
        assert samples_a and samples_b
        assert samples_a != samples_b, \
            "different nonces must drive different confirmation samples"
        qf_a = rep_a["evaluation"]["repos"][REPO_NAME][
            "op_kill_rates"]["confirmation"]
        qf_b = rep_b["evaluation"]["repos"][REPO_NAME][
            "op_kill_rates"]["confirmation"]
        # Pinned observation: the confirmation kill-rate sample differs
        # across nonces on the toy fixture. The oracle must not demand
        # cross-nonce Q-FRESH/verdict equality.
        assert qf_a != qf_b, \
            "expected Q-FRESH confirmation sampling variance"
        print(f"\n[NONCE_A] verdict={rep_a['verdict']['terminal']} "
              f"conf_rates={qf_a}")
        print(f"[NONCE_B] verdict={rep_b['verdict']['terminal']} "
              f"conf_rates={qf_b}")
    finally:
        shutil.rmtree(env_a["work"], ignore_errors=True)
        shutil.rmtree(env_b["work"], ignore_errors=True)
