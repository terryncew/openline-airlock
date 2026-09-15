"""Post-repair verification for the Q5 scientific runner bridge.

These began as pre-repair falsifiers (recorded 2026-09-15):
  FALSIFIER A -- timeout semantics: the pre-repair adapter raised
  ``UncertainExecution: observation fx-A-0000: subprocess timed out
  and was killed; completion unverifiable, refusing to rerun`` while
  Q3 treated the same timeout as a completed observation
  (timeout=True, collection_error=False, kill=True, outcomes={}).
  FALSIFIER B -- canonical binding: the pre-repair adapter committed
  ``airlock.rsi-006-q5.observation-outcome.v1`` envelope keys
  ['argv', 'child_pid', 'contact_created', 'duration_s', 'exec_nonce',
  'exit_status', 'observation_id', 'phase', 'schema', 'stderr_b64',
  'stdout_b64', 'txid'] instead of Q3's canonical keys ['collection_error',
  'kill', 'mutant_id', 'operator', 'outcomes', 'repo', 'seed', 'site_key',
  'timeout'].

Both now run through the repaired adapter with the runner's real Q3
completion builder (``run_rsi_006_q5.build_q3_completion`` -- exact Q3
parser, launch record, and kill semantics) and assert byte-equality
with the Q3 reference path. Tiny fixture repositories under the test
work dir only -- never the real pool, never production.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import observe as q3_observe
import perturb as q3_perturb
import q5_adapter as qa
import run_rsi_006_q5 as runner
from contact import ContactGate

Q3_CANONICAL_KEYS = {"repo", "mutant_id", "operator", "site_key", "seed",
                     "outcomes", "kill", "collection_error", "timeout"}

FX_SEED = "RSI-006-Q-discovery-A"

PKG_MOD = '''\
def classify(n):
    if n > 0:
        return "positive"
    return "non-positive"


def add(a, b):
    return a + b


def flag(x):
    return not x


def scale(v):
    return v * 2
'''

TEST_FAST = '''\
from pkg.mod import classify, add, flag, scale


def test_classify_positive():
    assert classify(3) == "positive"


def test_classify_non_positive():
    assert classify(-1) == "non-positive"


def test_add():
    assert add(1, 2) == 3


def test_flag():
    assert flag(False) is True


def test_scale():
    assert scale(3) == 6
'''

TEST_SLOW = '''\
import time
from pkg.mod import add


def test_slow_add():
    time.sleep(30)
    assert add(1, 1) == 2
'''


def q3_canonical_bytes(record: dict) -> bytes:
    """Q3's exact canonical record bytes (run_rsi_006_q3.canonical_bytes)."""
    return json.dumps(record, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


@pytest.fixture()
def fx_repo(work_dir):
    """Tiny fixture repository: package + fast tests + slow tests."""
    root = work_dir / "fxrepo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(PKG_MOD)
    fast = root / "tests" / "fast"
    slow = root / "tests" / "slow"
    fast.mkdir(parents=True)
    slow.mkdir(parents=True)
    (fast / "test_fast.py").write_text(TEST_FAST)
    (slow / "test_slow.py").write_text(TEST_SLOW)
    return {"root": root, "pkg": pkg,
            "tests_fast": fast, "tests_slow": slow}


@pytest.fixture()
def fx_mutant(fx_repo):
    mutants = q3_perturb.generate_mutants(fx_repo["pkg"], FX_SEED, 4,
                                          "fx-A")
    assert mutants, "fixture package produced no mutation sites"
    return mutants[0]


def repo_cfg_for(fx_repo, tests_dir: Path) -> dict:
    return {"name": "fx-repo",
            "package_dir": str(fx_repo["pkg"]),
            "tests_dir": str(tests_dir),
            "repo_root": str(fx_repo["root"]),
            "import_root": str(fx_repo["root"])}


def prepare_overlay(fx_repo, mutant: dict, dest_root: Path) -> Path:
    """Mirror Q3 observe_mutant's overlay prep, kept on disk."""
    overlay_root = dest_root / "overlay"
    overlay_pkg = overlay_root / "pkg"
    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    shutil.copytree(fx_repo["pkg"], overlay_pkg)
    q3_perturb.apply_mutant(fx_repo["pkg"], mutant, overlay_pkg)
    return overlay_root


def q3_style_pytest_cmd(python: str, run_dir: Path, repo_root: Path,
                        tests_dir: Path):
    """Byte-identical pytest invocation to Q3 run_suite_once."""
    xml_path = run_dir / "results.xml"
    cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--tb=no", f"--junitxml={xml_path}", "--rootdir",
           str(repo_root), str(tests_dir)]
    env = dict(os.environ)
    env.update({"PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(run_dir.parent / "overlay")})
    return cmd, env, run_dir


def make_spawn(cmd, env, cwd: Path):
    def spawn(exec_nonce: str):
        return subprocess.Popen(
            cmd, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return spawn


def make_coordinator(work_dir, tx, bindings, wait_timeout_s=60.0):
    # The timeout is passed explicitly: the Coordinator binds its
    # default at import time, so monkeypatching qa.WAIT_TIMEOUT_S
    # after import cannot change the effective ceiling.
    gate = ContactGate(work_dir / "contact.json")
    return qa.Coordinator(
        work_dir=work_dir, tx=tx, gate=gate,
        receipt_sha256=bindings["receipt_sha256"],
        code_hashes=bindings["code_hashes"],
        wait_timeout_s=wait_timeout_s)


def make_builder(repo_name, mutant, baseline, argv, python, run_dir,
                 env, env_overrides, junit_path):
    """The runner's real Q3 completion builder, bound to one observation."""
    def builder(observation_id: str, evidence: dict):
        return runner.build_q3_completion(
            repo_name=repo_name, mutant=mutant, baseline=baseline,
            argv=argv, python=python, run_dir=run_dir, env=env,
            env_overrides=env_overrides, junit_path=junit_path,
            evidence=evidence)
    return builder


def ledger_outcome_bytes(work_dir: Path, observation_id: str) -> bytes:
    return (work_dir / "artifacts" / "execution_ledger"
            / f"{observation_id}.outcome.json").read_bytes()


# ---------------------------------------------------------------------------
# FALSIFIER A -- timeout semantics
# ---------------------------------------------------------------------------

def test_timeout_is_q3_observation_not_uncertain(
        work_dir, tx, bindings, monkeypatch, fx_repo, fx_mutant):
    """A timed-out suite is a completed Q3 observation, not uncertainty."""
    # SAME effective timeout on both paths: falsifies treatment, not
    # threshold choice. Milliseconds, not 60/120 seconds.
    monkeypatch.setattr(q3_observe, "RUN_TIMEOUT_S", 0.3)

    # Reference: real Q3 observe_mutant on the slow fixture suite.
    q3_work = work_dir / "q3work"
    q3_work.mkdir()
    ref = q3_observe.observe_mutant(
        repo_cfg_for(fx_repo, fx_repo["tests_slow"]), fx_mutant, {},
        q3_work, sys.executable)
    record = ref["record"]
    assert record["timeout"] is True
    assert record["collection_error"] is False
    assert record["kill"] is True
    assert record["outcomes"] == {}
    want = q3_canonical_bytes(record)

    # Q5 path: the same pytest boundary through the repaired adapter
    # with the runner's Q3 completion builder.
    prep_root = work_dir / "q5prep"
    prep_root.mkdir()
    overlay_root = prepare_overlay(fx_repo, fx_mutant, prep_root)
    run_dir = work_dir / "q5run"
    run_dir.mkdir()
    cmd, env, _ = q3_style_pytest_cmd(
        sys.executable, run_dir, fx_repo["root"], fx_repo["tests_slow"])
    # PYTHONPATH must point at THIS overlay, not run_dir.parent/overlay.
    env_overrides = {"PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONPATH": str(overlay_root)}
    env.update(env_overrides)
    coord = make_coordinator(work_dir, tx, bindings, wait_timeout_s=0.3)
    obs_id = fx_mutant["mutant_id"]
    applied = coord.run_all(
        observations=[(obs_id, "discovery")],
        spawn=make_spawn(cmd, env, run_dir),
        argv_for=lambda o: cmd,
        completion_builder=make_builder(
            "fx-repo", fx_mutant, {}, cmd, sys.executable, run_dir,
            env, env_overrides, run_dir / "results.xml"))
    assert applied[0]["status"] == "committed"
    got = ledger_outcome_bytes(work_dir, obs_id)
    assert got == want


# ---------------------------------------------------------------------------
# FALSIFIER B -- canonical observation binding
# ---------------------------------------------------------------------------

def test_committed_bytes_are_q3_canonical_record(
        work_dir, tx, bindings, fx_repo, fx_mutant):
    """Committed bytes must be the exact Q3 canonical record shape."""
    q3_work = work_dir / "q3work"
    q3_work.mkdir()
    cfg = repo_cfg_for(fx_repo, fx_repo["tests_fast"])
    baseline, _ = q3_observe.observe_baseline(cfg, q3_work, sys.executable)
    assert baseline, "fixture baseline produced no outcomes"
    ref = q3_observe.observe_mutant(cfg, fx_mutant, baseline, q3_work,
                                    sys.executable)
    want = q3_canonical_bytes(ref["record"])
    assert set(ref["record"].keys()) == Q3_CANONICAL_KEYS

    # Q5 path through the repaired adapter with the runner's Q3
    # completion builder.
    prep_root = work_dir / "q5prep"
    prep_root.mkdir()
    overlay_root = prepare_overlay(fx_repo, fx_mutant, prep_root)
    run_dir = work_dir / "q5run"
    run_dir.mkdir()
    cmd, env, _ = q3_style_pytest_cmd(
        sys.executable, run_dir, fx_repo["root"], fx_repo["tests_fast"])
    env_overrides = {"PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONPATH": str(overlay_root)}
    env.update(env_overrides)
    coord = make_coordinator(work_dir, tx, bindings)
    obs_id = fx_mutant["mutant_id"]
    applied = coord.run_all(
        observations=[(obs_id, "discovery")],
        spawn=make_spawn(cmd, env, run_dir),
        argv_for=lambda o: cmd,
        completion_builder=make_builder(
            "fx-repo", fx_mutant, baseline, cmd, sys.executable, run_dir,
            env, env_overrides, run_dir / "results.xml"))
    assert applied[0]["status"] == "committed"
    got = ledger_outcome_bytes(work_dir, obs_id)
    got_record = json.loads(got)
    assert set(got_record.keys()) == Q3_CANONICAL_KEYS, \
        f"Q5 committed envelope keys {sorted(got_record.keys())} != " \
        f"Q3 canonical keys {sorted(Q3_CANONICAL_KEYS)}"
    assert got == want
