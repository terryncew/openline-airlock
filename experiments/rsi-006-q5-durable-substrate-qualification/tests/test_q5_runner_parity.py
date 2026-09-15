"""Q5 runner completion-builder parity against frozen Q3.

For each scenario, the Q5 path -- the repaired adapter plus the
runner's real ``build_q3_completion`` -- must produce byte-identical
canonical observation records to the frozen Q3 reference
(``observe_mutant`` / ``run_suite_once``) on the same fixture
scenario. Q3 is imported read-only; the fixture package is synthetic.
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

EXP_DIR = Path(__file__).resolve().parent.parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(EXP_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import observe as q3_observe  # noqa: E402
import perturb as q3_perturb  # noqa: E402
import run_rsi_006_q3 as q3_run  # noqa: E402
import q5_adapter as qa  # noqa: E402
import stransaction as st  # noqa: E402
from contact import ContactGate  # noqa: E402
from run_rsi_006_q5 import build_q3_completion, _code_hashes  # noqa: E402
from q5_fixture_support import build_parity_package, repo_cfg  # noqa: E402

REPO_NAME = "fx-repo"
PARITY_SEED = "PARITY-SEED-001"

Q3_CANONICAL_KEYS = {
    "collection_error", "kill", "mutant_id", "operator", "outcomes",
    "repo", "seed", "site_key", "timeout",
}


# ---------------------------------------------------------------------------
# fixture scaffolding (module scope: the package is built once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def parity_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("parity") / "repo"
    build_parity_package(root)
    return root


@pytest.fixture(scope="module")
def parity_cfg(parity_root):
    return repo_cfg(parity_root, name=REPO_NAME)


@pytest.fixture(scope="module")
def parity_baseline(parity_cfg, tmp_path_factory):
    work = tmp_path_factory.mktemp("parity-base")
    baseline, _ = q3_observe.observe_baseline(parity_cfg, work,
                                              sys.executable)
    assert baseline, "parity fixture baseline is empty"
    return baseline


@pytest.fixture(scope="module")
def parity_mutants(parity_root):
    mutants = q3_perturb.generate_mutants(parity_root / "pkg", PARITY_SEED,
                                          50, "fx-P")
    assert mutants, "no mutants generated"
    return mutants


@pytest.fixture(scope="module")
def parity_records(parity_cfg, parity_baseline, parity_mutants,
                   tmp_path_factory):
    """Full Q3 reference records, one per mutant: the parity oracle."""
    work = tmp_path_factory.mktemp("parity-ref")
    records = {}
    for mutant in parity_mutants:
        ref = q3_observe.observe_mutant(parity_cfg, mutant, parity_baseline,
                                        work, sys.executable)
        records[mutant["mutant_id"]] = (mutant, ref["record"])
    return records


def _bucket(parity_records, parity_baseline):
    # The fixture package is fixed: line 1 is ``VARIANT_UP = True``
    # (a BOOL_FLIP there removes a parametrized case), line 2 is
    # ``VARIANT_DOWN = False`` (a BOOL_FLIP there adds one). The
    # buckets are identified by behavior first, mechanism second.
    buckets: dict[str, tuple] = {}
    for mid, (mutant, record) in parity_records.items():
        outcomes, baseline = record["outcomes"], parity_baseline
        if record["collection_error"] or record["timeout"]:
            continue
        if outcomes == baseline:
            buckets.setdefault("survivor", (mutant, record))
        elif set(baseline) - set(outcomes):
            if mutant["operator"] == "BOOL_FLIP" and mutant["lineno"] == 1:
                buckets["missing"] = (mutant, record)
            else:
                buckets.setdefault("killed_changed", (mutant, record))
        elif set(outcomes) - set(baseline):
            if mutant["operator"] == "BOOL_FLIP" and mutant["lineno"] == 2:
                buckets["extra"] = (mutant, record)
            else:
                buckets.setdefault("killed_changed", (mutant, record))
        else:
            buckets.setdefault("killed_changed", (mutant, record))
    return buckets


@pytest.fixture(scope="module")
def buckets(parity_records, parity_baseline):
    b = _bucket(parity_records, parity_baseline)
    for need in ("survivor", "killed_changed", "missing", "extra"):
        assert need in b, f"parity fixture produced no {need} mutant"
    return b


# ---------------------------------------------------------------------------
# Q5 path driver (repaired adapter + real runner builder)
# ---------------------------------------------------------------------------

def _q5_completion(work_dir: Path, mutant: dict, baseline: dict,
                   tests_dir: Path, repo_root: Path, pkg_dir: Path,
                   wait_timeout_s: float = 60.0,
                   completion_builder=None) -> tuple:
    """Run one observation through the repaired adapter + Q3 builder.

    Returns ``(outcome_bytes, launch, evidence)``: the canonical bytes,
    the Q3 launch sidecar, and the completed-process evidence the
    adapter handed the builder.
    """
    txid = "par" + hashlib.sha256(os.urandom(16)).hexdigest()[:61]
    tx = st.ScientificTransaction.begin(
        work_dir, receipt_sha256="f" * 64,
        code_hashes=_code_hashes(), tx_nonce=os.urandom(32).hex())
    gate = ContactGate(work_dir / "contact_marker.json")
    coord = qa.Coordinator(
        work_dir=work_dir, tx=tx, gate=gate,
        receipt_sha256="f" * 64, code_hashes=_code_hashes(),
        wait_timeout_s=wait_timeout_s)
    prep_root = work_dir / "prep"
    overlay_root = prep_root / "overlay"
    overlay_pkg = overlay_root / "pkg"
    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    shutil.copytree(pkg_dir, overlay_pkg)
    q3_perturb.apply_mutant(pkg_dir, mutant, overlay_pkg)
    run_dir = work_dir / "rundir"
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--tb=no", f"--junitxml={run_dir / 'results.xml'}",
           "--rootdir", str(repo_root), str(tests_dir)]
    env = dict(os.environ)
    env_overrides = {"PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONPATH": str(overlay_root)}
    env.update(env_overrides)

    def spawn(exec_nonce: str):
        return subprocess.Popen(cmd, cwd=str(run_dir), env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

    captured: dict = {}
    built_box: dict = {}

    def builder(observation_id: str, evidence: dict):
        captured.update(evidence)
        inner = completion_builder or build_q3_completion
        built = inner(
            repo_name=REPO_NAME, mutant=mutant, baseline=baseline,
            argv=cmd, python=sys.executable, run_dir=run_dir, env=env,
            env_overrides=env_overrides,
            junit_path=run_dir / "results.xml", evidence=evidence)
        built_box["built"] = built
        return built

    obs_id = mutant["mutant_id"]
    applied = coord.run_all(
        observations=[(obs_id, "discovery")], spawn=spawn,
        argv_for=lambda o: cmd, completion_builder=builder)
    assert applied[0]["status"] == "committed"
    outcome_path = (work_dir / "artifacts" / "execution_ledger"
                    / f"{obs_id}.outcome.json")
    outcome_bytes, launch = built_box["built"]
    assert outcome_path.read_bytes() == outcome_bytes
    return outcome_bytes, launch, captured, {
        "cmd": cmd, "run_dir": run_dir, "env": env,
        "env_overrides": env_overrides}


def _q5_canonical_bytes(work_dir: Path, mutant: dict, baseline: dict,
                        tests_dir: Path, repo_root: Path, pkg_dir: Path,
                        wait_timeout_s: float = 60.0) -> bytes:
    """Run one observation through the repaired adapter + Q3 builder."""
    outcome_bytes, _, _, _ = _q5_completion(
        work_dir, mutant, baseline, tests_dir, repo_root, pkg_dir,
        wait_timeout_s=wait_timeout_s)
    return outcome_bytes


def _want_canonical(record: dict) -> bytes:
    # The parity oracle is Q3's frozen canonical serialization itself
    # (compact separators, no trailing newline), not a local
    # re-serialization: any drift here would mask a real mismatch.
    assert set(record.keys()) == Q3_CANONICAL_KEYS
    return q3_run.canonical_bytes(record)


# ---------------------------------------------------------------------------
# parity cases
# ---------------------------------------------------------------------------

def test_parity_survivor(work_dir, buckets, parity_baseline, parity_root):
    """A mutant in uncovered code: kill=False, byte-identical."""
    mutant, record = buckets["survivor"]
    assert record["kill"] is False
    assert record["collection_error"] is False
    assert record["timeout"] is False
    got = _q5_canonical_bytes(work_dir, mutant, parity_baseline,
                              parity_root / "tests", parity_root,
                              parity_root / "pkg")
    assert got == _want_canonical(record)


def test_parity_killed_mutant(work_dir, buckets, parity_baseline,
                              parity_root):
    """A mutant that changes outcomes: kill=True, byte-identical."""
    mutant, record = buckets["killed_changed"]
    assert record["kill"] is True
    assert record["collection_error"] is False
    assert set(record["outcomes"]) == set(parity_baseline)
    got = _q5_canonical_bytes(work_dir, mutant, parity_baseline,
                              parity_root / "tests", parity_root,
                              parity_root / "pkg")
    assert got == _want_canonical(record)


def test_parity_missing_tests(work_dir, buckets, parity_baseline,
                              parity_root):
    """A mutant that removes collected tests kills via missing IDs."""
    mutant, record = buckets["missing"]
    assert record["kill"] is True
    assert set(parity_baseline) - set(record["outcomes"]), \
        "expected missing baseline test IDs"
    got = _q5_canonical_bytes(work_dir, mutant, parity_baseline,
                              parity_root / "tests", parity_root,
                              parity_root / "pkg")
    assert got == _want_canonical(record)


def test_parity_extra_tests(work_dir, buckets, parity_baseline,
                            parity_root):
    """A mutant that adds collected tests kills via extra IDs."""
    mutant, record = buckets["extra"]
    assert record["kill"] is True
    assert set(record["outcomes"]) - set(parity_baseline), \
        "expected extra test IDs"
    for tid, outcome in parity_baseline.items():
        assert record["outcomes"].get(tid) == outcome
    got = _q5_canonical_bytes(work_dir, mutant, parity_baseline,
                              parity_root / "tests", parity_root,
                              parity_root / "pkg")
    assert got == _want_canonical(record)


def test_parity_collection_error_no_junit(work_dir, parity_cfg,
                                         parity_baseline, parity_root):
    """A child that dies by signal: no JUnit -> collection_error=True.

    Q3 reference is ``observe_mutant`` on the killer suite (a real
    mutant is applied; the suite SIGKILLs its own child).
    """
    mutant = q3_perturb.generate_mutants(parity_root / "pkg", PARITY_SEED,
                                         1, "fx-K")[0]
    killer_cfg = dict(parity_cfg, tests_dir=str(parity_root / "tests_killer"))
    ref = q3_observe.observe_mutant(killer_cfg, mutant, {}, work_dir,
                                    sys.executable)
    record = ref["record"]
    assert record["collection_error"] is True
    assert record["timeout"] is False
    assert record["kill"] is True
    assert record["outcomes"] == {}
    assert ref["launch"]["disposition"] == "collection_error_no_junitxml"
    got = _q5_canonical_bytes(work_dir, mutant, {}, parity_root / "tests_killer",
                              parity_root, parity_root / "pkg")
    assert got == _want_canonical(record)


def test_parity_timeout(work_dir, parity_root):
    """A suite that outlasts the timeout: Q3 timeout semantics."""
    mutant = q3_perturb.generate_mutants(parity_root / "pkg", PARITY_SEED,
                                         1, "fx-T")[0]
    slow_cfg = repo_cfg(parity_root, name=REPO_NAME,
                        tests_subdir="tests_slow")
    real_timeout = q3_observe.RUN_TIMEOUT_S
    q3_observe.RUN_TIMEOUT_S = 0.5
    try:
        ref = q3_observe.observe_mutant(slow_cfg, mutant, {}, work_dir,
                                        sys.executable)
    finally:
        q3_observe.RUN_TIMEOUT_S = real_timeout
    record = ref["record"]
    assert record["timeout"] is True
    assert record["collection_error"] is False
    assert record["kill"] is True
    assert record["outcomes"] == {}
    got = _q5_canonical_bytes(work_dir, mutant, {}, parity_root / "tests_slow",
                              parity_root, parity_root / "pkg",
                              wait_timeout_s=0.5)
    assert got == _want_canonical(record)


def test_parity_unparseable_junit(work_dir, parity_root):
    """Garbage at the JUnit path: Q3's unparseable-XML disposition.

    The builder is driven directly with hand-built completed-process
    evidence (the child exited; its XML is corrupt). The oracle is
    Q3's own branch: ``parse_junitxml_bytes`` raising ``ET.ParseError``
    -> ``collection_error=True`` with disposition
    ``collection_error_unparseable_junitxml``.
    """
    mutant = q3_perturb.generate_mutants(parity_root / "pkg", PARITY_SEED,
                                         1, "fx-U")[0]
    run_dir = work_dir / "rundir"
    run_dir.mkdir()
    junit_path = run_dir / "results.xml"
    junit_path.write_bytes(b"<testsuite><unclosed")
    with pytest.raises(ET.ParseError):
        q3_observe.parse_junitxml_bytes(junit_path.read_bytes())
    cmd = [sys.executable, "-m", "pytest"]
    evidence = {
        "exec_nonce": "u" * 32, "child_pid": 4242, "argv": cmd,
        "exit_status": 0, "timeout": False,
        "stdout": b"", "stderr": b"corrupt xml above",
        "duration_s": 0.123, "started_utc": 1.0, "ended_utc": 1.123,
        "started_monotonic": 2.0, "ended_monotonic": 2.123,
        "contact_created": True,
    }
    outcome_bytes, launch = build_q3_completion(
        repo_name=REPO_NAME, mutant=mutant, baseline={}, argv=cmd,
        python=sys.executable, run_dir=run_dir, env={}, env_overrides={},
        junit_path=junit_path, evidence=evidence)
    record = json.loads(outcome_bytes)
    assert set(record.keys()) == Q3_CANONICAL_KEYS
    assert record["collection_error"] is True
    assert record["timeout"] is False
    assert record["kill"] is True
    assert record["outcomes"] == {}
    assert record["mutant_id"] == mutant["mutant_id"]
    assert launch["disposition"] == "collection_error_unparseable_junitxml"
    # The corrupt bytes are retained in the launch sidecar for forensics.
    assert base64.b64decode(launch["junit_xml"]["bytes_b64"]) == \
        b"<testsuite><unclosed"


def test_builder_exception_propagates(work_dir, buckets, parity_baseline,
                                      parity_root):
    """A builder exception is a deterministic code failure: it propagates
    as-is -- no fallback envelope, no UncertainExecution, no commit.
    """
    mutant, _ = buckets["survivor"]

    def bad_builder(*, repo_name, mutant, baseline, argv, python, run_dir,
                    env, env_overrides, junit_path, evidence):
        raise RuntimeError("builder boom")

    with pytest.raises(RuntimeError, match="builder boom"):
        _q5_completion(work_dir, mutant, parity_baseline,
                       parity_root / "tests", parity_root,
                       parity_root / "pkg",
                       completion_builder=bad_builder)
    ledger_dir = work_dir / "artifacts" / "execution_ledger"
    assert list(ledger_dir.glob("*.outcome.json")) == [], \
        "a failed builder must not leave a committed outcome"


def test_launch_sidecar_matches_q3(work_dir, buckets, parity_baseline,
                                   parity_root):
    """The launch sidecar is Q3's own ``_launch_record`` applied to the
    adapter's evidence: rebuilding it from the captured evidence with
    the frozen Q3 function must be byte-shape-identical. This pins the
    builder's argument mapping, not just its existence.
    """
    mutant, _ = buckets["survivor"]
    _, launch, evidence, ctx = _q5_completion(
        work_dir, mutant, parity_baseline, parity_root / "tests",
        parity_root, parity_root / "pkg")
    junit_path = ctx["run_dir"] / "results.xml"
    junit_bytes = junit_path.read_bytes() if junit_path.is_file() else None
    expected = q3_observe._launch_record(
        list(ctx["cmd"]), sys.executable, Path(ctx["run_dir"]),
        dict(ctx["env"]), dict(ctx["env_overrides"]),
        evidence["started_utc"], evidence["ended_utc"],
        evidence["exit_status"], evidence["stdout"], evidence["stderr"],
        junit_bytes, launch["disposition"],
        child_pid=evidence["child_pid"])
    assert launch == expected


def test_generic_completion_unchanged(work_dir, buckets, parity_baseline,
                                      parity_root):
    """Without a completion builder the adapter still emits the exact
    pre-repair generic envelope: the repair added the seam without
    changing the default path.
    """
    mutant, _ = buckets["survivor"]
    tx = st.ScientificTransaction.begin(
        work_dir, receipt_sha256="f" * 64,
        code_hashes=_code_hashes(), tx_nonce=os.urandom(32).hex())
    gate = ContactGate(work_dir / "contact_marker.json")
    coord = qa.Coordinator(
        work_dir=work_dir, tx=tx, gate=gate,
        receipt_sha256="f" * 64, code_hashes=_code_hashes(),
        wait_timeout_s=60.0)
    cmd = [sys.executable, "-c", "print('ok')"]
    applied = coord.run_all(
        observations=[("fx-generic-0000", "discovery")],
        spawn=lambda nonce: subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE),
        argv_for=lambda o: cmd)
    assert applied[0]["status"] == "committed"
    outcome = json.loads(
        (work_dir / "artifacts" / "execution_ledger"
         / "fx-generic-0000.outcome.json").read_bytes())
    assert set(outcome.keys()) == {
        "argv", "child_pid", "contact_created", "duration_s", "exec_nonce",
        "exit_status", "observation_id", "phase", "schema", "stderr_b64",
        "stdout_b64", "txid"}
    assert outcome["schema"] == qa.OUTCOME_SCHEMA
    assert outcome["exit_status"] == 0
