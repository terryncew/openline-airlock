"""RSI-006-Q3 contract tests: frozen non-scientific properties only.

These tests assert the executable boundary between repeatable environment
qualification (Stage 1) and irreversible scientific contact (Stage 2).
They never touch the real repository pool, the real frozen seeds in an
outcome-bearing way, or the real one-run authorization: all execution
uses tiny local fixture packages with test seeds.

NOTE on imports: this module must not import ``perturb`` or
``run_rsi_006_q3`` at top level, so the dynamic Stage 1 isolation test
can assert the mutation substrate is never loaded by Stage 1.
"""

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import env_qualify
import observe
import pool_config
import receipt as receipt_mod

EXP_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
Q2_DIR = EXP_DIR.parent / "rsi-006-q2-substrate-qualification"

# Frozen Q2 hashes: Q3 must not touch or reinterpret Q2.
Q2_FROZEN = {
    "RSI_006_Q2_SPEC.md":
        "6e2ed29a2242c54645f97d0981f23f83a57b41a50344d501632e02e80e947c79",
    "perturb.py":
        "e4e35ca76a067d26b00b69c53c3b2673bcde4476c8a1ab654cc8679b14da6302",
    "observe.py":
        "b4556add9a67876a5c0040aeb3576de845934a74329c297cfe191afef7a7182c",
    "run_rsi_006_q2.py":
        "28b0d0e43515b2ce280079c56952cc8037df0e5207dac8e024b5072735f71dd9",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# fixture pool builder (local git repos; never the real pool)
# --------------------------------------------------------------------------

N_FUNCS = 20


def _bigpkg_sources():
    pkg_lines = []
    for i in range(N_FUNCS):
        pkg_lines.append(f"def f{i}(x):")
        pkg_lines.append(f"    return {i} + {i + 1} if x > 0 else {i} - 1")
        pkg_lines.append("")
    test_lines = ["from bigpkg import mod", "", "", "def test_all():"]
    test_lines.append(f"    for i in range({N_FUNCS}):")
    test_lines.append("        f = getattr(mod, f'f{i}')")
    test_lines.append("        assert f(1) == 2 * i + 1")
    test_lines.append("        assert f(-1) == i - 1")
    return "\n".join(pkg_lines), "\n".join(test_lines) + "\n"


def build_fixture_pool(base: Path, n_repos: int = 2,
                       tests_dir_name: str = "tests",
                       write_tests: bool = True) -> list[dict]:
    """Create ``n_repos`` tiny local git repos; return pool entries."""
    base.mkdir(parents=True, exist_ok=True)
    pkg_src, test_src = _bigpkg_sources()
    pool = []
    for r in range(n_repos):
        repo = base / f"tiny-{r}"
        (repo / "bigpkg").mkdir(parents=True)
        (repo / "bigpkg" / "__init__.py").write_text("")
        (repo / "bigpkg" / "mod.py").write_text(pkg_src)
        if write_tests:
            (repo / tests_dir_name).mkdir(parents=True, exist_ok=True)
            (repo / tests_dir_name / "test_mod.py").write_text(test_src)
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "fixture"]):
            subprocess.run(["git", *args], cwd=str(repo), check=True,
                           capture_output=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                             capture_output=True, text=True,
                             check=True).stdout.strip()
        pool.append({
            "name": f"tiny-{r}",
            "url": str(repo),
            "sha": sha,
            "pkg": "bigpkg",
            "src_layout": False,
            "tests": tests_dir_name,
        })
    return pool


def run_stage1(pool: list[dict], tmp_path: Path, tag: str) -> Path:
    work_dir = tmp_path / f"env-{tag}"
    pool_dir = tmp_path / f"pool-{tag}"
    receipt_path = work_dir / "environment-receipt.json"
    env_qualify.qualify_environment(
        pool, work_dir, pool_dir, sys.executable,
        install_deps=False, receipt_path=receipt_path)
    return receipt_path


# --------------------------------------------------------------------------
# frozen properties
# --------------------------------------------------------------------------

def test_spec_frozen_markers():
    text = (EXP_DIR / "RSI_006_Q3_SPEC.md").read_text()
    for needle in ("RSI-006-Q3", "QUALIFIED_RSI_006_Q3_SUBSTRATE",
                   "NOT_QUALIFIED_RSI_006_Q3_SUBSTRATE",
                   "INCONCLUSIVE_RSI_006_Q3_PRECONDITION_FAILURE",
                   "INCONCLUSIVE_RSI_006_Q2_PRECONDITION_FAILURE",
                   "1.0 exact", "[0.05, 0.95]", "0.25", "0.7", "0.10",
                   "feasibility guard", "environment receipt",
                   "scientific contact",
                   "more-itertools (72, 72, 10, 20)",
                   "cachetools (102, 102, 20, 60)",
                   "boltons (70, 70, 20, 60)",
                   "pluggy (51, 51, 20, 60)"):
        assert needle in text, f"spec missing frozen marker: {needle}"


def test_perturb_byte_identical_to_q2():
    assert sha256_file(EXP_DIR / "perturb.py") == Q2_FROZEN["perturb.py"]


def test_q2_stage_untouched():
    for name, frozen in Q2_FROZEN.items():
        assert sha256_file(Q2_DIR / name) == frozen, f"Q2 file changed: {name}"


def test_pool_matches_q2_pins():
    q2_pool = {
        "more-itertools": "b2f3aff7633057d234ec9186c18a53f4df306d08",
        "cachetools": "4500e3d04288738d25acbb4973eb3c3e1bf41db9",
        "boltons": "961dcff3f42e73b245aef65e377fe82763b257bb",
        "pluggy": "0a4974175aa2d873f401345b151297af2e74c851",
    }
    assert {e["name"]: e["sha"] for e in pool_config.POOL} == q2_pool


def test_no_forbidden_imports():
    # Function-level import: this module must not load the Stage 2 runner
    # (or the mutation substrate) at top level, so the dynamic Stage 1
    # isolation test stays hermetic.
    import run_rsi_006_q3  # noqa: F401
    forbidden = ("openai", "anthropic", "google.generativeai", "boto3",
                 "langchain", "transformers", "huggingface_hub")
    for path in EXP_DIR.glob("*.py"):
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            else:
                continue
            for mod in mods:
                assert not any(mod == f or mod.startswith(f + ".")
                               for f in forbidden), f"{mod} in {path.name}"


def test_generator_determinism_and_single_site(tmp_path):
    import perturb
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(
        "def f(x):\n    return x + 1 if x > 0 else x - 1\n")
    m1 = perturb.generate_mutants(pkg, "seed-1", 10, "t")
    m2 = perturb.generate_mutants(pkg, "seed-1", 10, "t")
    m3 = perturb.generate_mutants(pkg, "seed-2", 10, "t")
    assert [m["site_key"] for m in m1] == [m["site_key"] for m in m2]
    assert [m["site_key"] for m in m1] != [m["site_key"] for m in m3]
    assert tuple(perturb.OPERATORS) == (
        "CMP_SWAP", "ARITH_SWAP", "BOOL_FLIP",
        "NUM_DELTA", "LOGIC_SWAP", "NOT_DROP")


def test_canonical_record_shape_and_seal(tmp_path):
    """Observation records keep the exact Q2 shape; seal relationship holds."""
    import run_rsi_006_q3 as q3
    import perturb
    repo = tmp_path / "repo"
    (repo / "bigpkg").mkdir(parents=True)
    (repo / "bigpkg" / "__init__.py").write_text("")
    pkg_src, test_src = _bigpkg_sources()
    (repo / "bigpkg" / "mod.py").write_text(pkg_src)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_mod.py").write_text(test_src)
    cfg = {"name": "tiny", "repo_root": str(repo),
           "package_dir": str(repo / "bigpkg"),
           "import_root": str(repo), "tests_dir": str(repo / "tests")}
    work = tmp_path / "work"
    work.mkdir()
    base, _ = observe.observe_baseline(cfg, work, sys.executable)
    muts = perturb.generate_mutants(repo / "bigpkg", "seed-9", 3, "t")
    rows = [observe.observe_mutant(cfg, m, base, work, sys.executable)["record"]
            for m in muts]
    for row in rows:
        assert set(row.keys()) == {
            "repo", "mutant_id", "operator", "site_key", "seed",
            "outcomes", "kill", "collection_error", "timeout"}, row.keys()
    rows.sort(key=lambda o: o["mutant_id"])
    blob = q3.discovery_seal_input(rows)
    seal = hashlib.sha256(blob).hexdigest()
    # The persisted JSONL file is exactly the seal bytes plus one \n.
    q3.persist_records(work, {}, "tiny-discovery.jsonl", rows)
    file_bytes = (work / "tiny-discovery.jsonl").read_bytes()
    assert hashlib.sha256(file_bytes[:-1]).hexdigest() == seal


# --------------------------------------------------------------------------
# stage separation: Stage 1 can never touch the mutation substrate
# --------------------------------------------------------------------------

def _assert_no_import_of(path: Path, banned: tuple[str, ...]) -> None:
    tree = ast.parse(path.read_bytes())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        for mod in mods:
            assert not any(mod == b or mod.startswith(b + ".")
                           for b in banned), \
                f"forbidden import {mod} in {path.name}"


def test_stage1_never_imports_perturb_static():
    _assert_no_import_of(EXP_DIR / "env_qualify.py", ("perturb",))


def test_stage2_never_imports_env_qualify_static():
    _assert_no_import_of(EXP_DIR / "run_rsi_006_q3.py", ("env_qualify",))


def test_stage1_never_loads_perturb_dynamic(tmp_path):
    """Stage 1 in a fresh interpreter: the mutation substrate stays unloaded."""
    driver = (
        "import sys;"
        f"sys.path.insert(0, {str(EXP_DIR)!r});"
        f"sys.path.insert(0, {str(TESTS_DIR)!r});"
        "from pathlib import Path;"
        "from test_rsi_006_q3_contract import build_fixture_pool;"
        "import env_qualify;"
        f"pool = build_fixture_pool(Path({str(tmp_path / 'src')!r}));"
        "env_qualify.qualify_environment("
        f"pool, Path({str(tmp_path / 'env')!r}),"
        f"Path({str(tmp_path / 'pool')!r}),"
        "sys.executable, False,"
        f"Path({str(tmp_path / 'env' / 'environment-receipt.json')!r}));"
        "print('PERTURB_LOADED' if 'perturb' in sys.modules "
        "else 'PERTURB_ABSENT')"
    )
    proc = subprocess.run([sys.executable, "-c", driver],
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "PERTURB_ABSENT" in proc.stdout


def test_stage1_repeatable(tmp_path):
    """Stage 1 run twice: both green, bindings identical, no mutant residue."""
    pool = build_fixture_pool(tmp_path / "src")
    r1 = run_stage1(pool, tmp_path, "a")
    r2 = run_stage1(pool, tmp_path, "b")

    def bindings(path: Path) -> dict:
        rec = json.loads(path.read_bytes())
        rec.pop("frozen_at", None)
        rec.get("host", {}).pop("frozen_at", None)
        # Launch timestamps are evidence, not bindings.
        for ev in rec["baseline_evidence"].values():
            ev.pop("launch_sha256", None)
        return rec

    assert bindings(r1) == bindings(r2)

    for tag in ("a", "b"):
        work_dir = tmp_path / f"env-{tag}"
        assert not (work_dir / "scientific-contact.json").exists()
        assert not (work_dir / "records").exists()
        assert not (work_dir / "launches").exists()

    # Stage 1 freezes no confirmation nonce and leaves no mutant residue.
    for rp in (r1, r2):
        rec = json.loads(rp.read_bytes())
        assert "confirmation_nonce" not in rec


def test_stage1_interpreter_probe_failure_preserves_evidence(tmp_path):
    """An unlaunchable interpreter fails Stage 1 with the probe preserved.

    This is the Q2 failure mode generalized: Q2 could only report that
    pytest was missing; here the failed probe itself is evidence.
    """
    pool = build_fixture_pool(tmp_path / "src", n_repos=1)
    work_dir = tmp_path / "env-nopy"
    pool_dir = tmp_path / "pool-nopy"
    receipt_path = work_dir / "environment-receipt.json"
    with pytest.raises(env_qualify.EnvironmentNotReady):
        env_qualify.qualify_environment(
            pool, work_dir, pool_dir, "/nonexistent/python-xyz",
            install_deps=False, receipt_path=receipt_path)
    assert not receipt_path.exists()
    assert not (work_dir / "scientific-contact.json").exists()

    probe_path = work_dir / "env-evidence" / "00-interpreter-probe.json"
    assert probe_path.exists(), "interpreter probe evidence missing"
    rec = json.loads(probe_path.read_bytes())
    assert rec["classification"] == "interpreter_probe_failed"
    launch = rec["launch"]
    assert launch["argv"] == ["/nonexistent/python-xyz", "--version"]
    assert launch["disposition"] == "launch_spawn_failed"
    assert launch["exit_status"] is None
    assert launch["end_ts"] >= launch["start_ts"]


def test_stage1_baseline_failure_preserves_full_launch_evidence(tmp_path):
    """A broken baseline launch keeps argv/exit/stdout/stderr/timestamps."""
    pool = build_fixture_pool(tmp_path / "src", n_repos=1,
                              tests_dir_name="tests_missing",
                              write_tests=False)
    work_dir = tmp_path / "env-bad"
    pool_dir = tmp_path / "pool-bad"
    receipt_path = work_dir / "environment-receipt.json"
    with pytest.raises(env_qualify.EnvironmentNotReady):
        env_qualify.qualify_environment(
            pool, work_dir, pool_dir, sys.executable,
            install_deps=False, receipt_path=receipt_path)
    assert not receipt_path.exists()
    assert not (work_dir / "scientific-contact.json").exists()

    evidence_files = sorted((work_dir / "env-evidence").glob("*.json"))
    assert evidence_files, "no launch evidence preserved"
    rec = json.loads(evidence_files[0].read_bytes())
    assert rec["classification"] == "baseline_launch_failed"
    launch = rec["launch"]
    for field in ("argv", "interpreter", "cwd", "env_fingerprint",
                  "exit_status", "stdout", "stderr", "start_ts", "end_ts",
                  "disposition"):
        assert field in launch, f"launch evidence missing {field}"
    # pytest 9 writes an (empty) junit xml even on usage error, so the
    # disposition is ok-but-empty: the empty-outcome guard, not the
    # missing-xml guard, is what fails the baseline. Stated as observed.
    assert launch["exit_status"] == 4
    assert launch["end_ts"] >= launch["start_ts"]
    assert launch["argv"][0] == sys.executable
    assert "-m" in launch["argv"] and "pytest" in launch["argv"]
    # The underlying stderr is preserved byte-exact, not summarized.
    assert "file or directory not found" in launch["stderr"]["text"]


# --------------------------------------------------------------------------
# Stage 2 gating: no receipt, no scientific contact
# --------------------------------------------------------------------------

def _fixture_stage2_setup(tmp_path: Path):
    import run_rsi_006_q3 as q3
    pool = build_fixture_pool(tmp_path / "src")
    receipt_path = run_stage1(pool, tmp_path, "s2")
    return q3, pool, receipt_path


def test_stage2_refuses_without_receipt(tmp_path):
    import run_rsi_006_q3 as q3
    work_dir = tmp_path / "work"
    with pytest.raises(SystemExit) as ei:
        q3.qualify_science(work_dir, tmp_path / "pool", 1, sys.executable,
                           tmp_path / "no-such-receipt.json")
    assert ei.value.code == 3
    assert not (work_dir / q3.CONTACT_MARKER).exists()
    assert not (work_dir / "records").exists()


def test_stage2_refuses_on_drifted_receipt(tmp_path):
    import run_rsi_006_q3 as q3
    pool = build_fixture_pool(tmp_path / "src")
    receipt_path = run_stage1(pool, tmp_path, "drift")
    pool_dir = tmp_path / "pool-drift"
    # Modify a tracked file: the tree hash must drift.
    target = pool_dir / "tiny-0" / "bigpkg" / "mod.py"
    with target.open("a") as f:
        f.write("\n# drift\n")
    work_dir = tmp_path / "work-drift"
    with pytest.raises(SystemExit) as ei:
        q3.qualify_science(work_dir, pool_dir, 1, sys.executable,
                           receipt_path)
    assert ei.value.code == 3
    assert not (work_dir / q3.CONTACT_MARKER).exists()
    assert not (work_dir / "records").exists()


def test_contact_consumed_at_first_actual_process_start(tmp_path, monkeypatch):
    """Authorization is consumed exactly once, at actual process start.

    The marker names a real discovery mutant and the pid of a real
    mutant-observation subprocess, cross-checked against the persisted
    launch evidence; a later start neither rewrites nor duplicates it.
    """
    import run_rsi_006_q3 as q3
    q3, pool, receipt_path = _fixture_stage2_setup(tmp_path)
    monkeypatch.setattr(q3, "POOL", pool)
    monkeypatch.setattr(q3, "BUDGETS",
                        {e["name"]: (12, 12, 2, 4) for e in pool})
    small_thresh = dict(q3.THRESH)
    # Test-only: the fixture package's budgets admit few qualifying
    # operators; the guard is not what this test exercises.
    small_thresh.update({"stab_min_operators": 1, "stab_min_per_half": 1,
                         "kill_rate_lo": 0.0, "kill_rate_hi": 1.0,
                         "collection_error_max": 1.0})
    monkeypatch.setattr(q3, "THRESH", small_thresh)

    work_dir = tmp_path / "work-contact"
    pool_dir = tmp_path / "pool-s2"
    report = q3.qualify_science(work_dir, pool_dir, 1, sys.executable,
                               receipt_path)

    marker_path = work_dir / q3.CONTACT_MARKER
    assert marker_path.exists(), "contact marker missing after Stage 2"
    marker = json.loads(marker_path.read_bytes())
    assert marker["schema"] == "airlock.rsi-006-q3.scientific-contact.v1"
    assert marker["event"] == "scientific_contact"
    assert marker["receipt_sha256"] == receipt_mod.receipt_sha256(
        receipt_path)

    # The marker names a real discovery mutant and the pid of a real
    # mutant-observation subprocess recorded in the launch evidence.
    launches = [json.loads(p.read_bytes())
                for p in (work_dir / "launches").glob("*.json")]
    assert launches, "no observation launches persisted"
    child_pids = {l["child_pid"] for l in launches
                  if l.get("child_pid") is not None}
    assert marker["child_pid"] in child_pids, \
        "marker pid is not a real observed subprocess pid"
    records = []
    for f in (work_dir / "records").glob("*-discovery.jsonl"):
        records.extend(
            json.loads(line) for line in f.read_text().splitlines())
    assert marker["mutant_id"] in {r["mutant_id"] for r in records}

    # Exactly once: a later start neither rewrites nor duplicates the event.
    before = marker_path.read_bytes()
    gate = q3.contact_mod.ContactGate(marker_path)
    again = gate.note_process_started("some-other-mutant", "0" * 64,
                                      999999999)
    assert again["created"] is False
    assert again["marker"] == marker
    assert marker_path.read_bytes() == before

    # The report binds the receipt and the contact event.
    assert report["schema"] == "airlock.rsi-006-q3.report.v1"
    assert report["environment_receipt_sha256"] == marker["receipt_sha256"]
    assert report["scientific_contact"]["mutant_id"] == marker["mutant_id"]


def test_contact_hook_fires_only_after_popen_returns(tmp_path, monkeypatch):
    """The hook fires after -- never before -- the suite process starts."""
    import perturb
    import contact as contact_mod
    repo = tmp_path / "repo"
    (repo / "bigpkg").mkdir(parents=True)
    (repo / "bigpkg" / "__init__.py").write_text("")
    pkg_src, test_src = _bigpkg_sources()
    (repo / "bigpkg" / "mod.py").write_text(pkg_src)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_mod.py").write_text(test_src)
    cfg = {"name": "tiny", "repo_root": str(repo),
           "package_dir": str(repo / "bigpkg"),
           "import_root": str(repo), "tests_dir": str(repo / "tests")}
    work = tmp_path / "work"
    work.mkdir()
    base, _ = observe.observe_baseline(cfg, work, sys.executable)
    muts = perturb.generate_mutants(repo / "bigpkg", "seed-hook", 1, "t")

    events: list[tuple[str, int]] = []
    real_popen = subprocess.Popen

    def spy_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        events.append(("popen_returned", proc.pid))
        return proc

    monkeypatch.setattr(observe.subprocess, "Popen", spy_popen)
    gate = contact_mod.ContactGate(work / "contact.json")

    def spy_hook(pid: int) -> None:
        events.append(("contact_noted", pid))
        gate.note_process_started(muts[0]["mutant_id"], "r" * 64, pid)

    out = observe.observe_mutant(cfg, muts[0], base, work, sys.executable,
                                 on_process_start=spy_hook)
    assert [k for k, _ in events] == ["popen_returned", "contact_noted"], \
        events
    assert events[0][1] == events[1][1]
    marker = json.loads((work / "contact.json").read_bytes())
    assert marker["child_pid"] == events[0][1]
    assert out["launch"]["child_pid"] == events[0][1]
    assert gate.consumed


def test_hook_failure_reaps_child(tmp_path):
    """A hook that raises after Popen still reaps the suite process."""
    import perturb
    repo = tmp_path / "repo"
    (repo / "bigpkg").mkdir(parents=True)
    (repo / "bigpkg" / "__init__.py").write_text("")
    pkg_src, test_src = _bigpkg_sources()
    (repo / "bigpkg" / "mod.py").write_text(pkg_src)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_mod.py").write_text(test_src)
    cfg = {"name": "tiny", "repo_root": str(repo),
           "package_dir": str(repo / "bigpkg"),
           "import_root": str(repo), "tests_dir": str(repo / "tests")}
    work = tmp_path / "work"
    work.mkdir()
    base, _ = observe.observe_baseline(cfg, work, sys.executable)
    muts = perturb.generate_mutants(repo / "bigpkg", "seed-hookfail", 1, "t")
    pids: list[int] = []

    def bad_hook(pid: int) -> None:
        pids.append(pid)
        raise RuntimeError("hook exploded")

    with pytest.raises(RuntimeError, match="hook exploded"):
        observe.observe_mutant(cfg, muts[0], base, work, sys.executable,
                               on_process_start=bad_hook)
    assert len(pids) == 1
    # The child was killed and reaped: no stranded suite subprocess.
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


def test_contact_gate_exactly_once_under_concurrency(tmp_path):
    """Eight racing starters, independent gates: one atomic transition.

    Each racer holds its own ContactGate instance over the same marker
    file, so their in-process locks are independent and only the atomic
    O_CREAT|O_EXCL create arbitrates. Establishes, without touching the
    atomic-file guarantee in contact.py:
    - exactly one O_CREAT|O_EXCL transition succeeds (one created=True);
    - exactly one marker file exists, and it parses as JSON (no
      truncation or partial write);
    - the marker names the PID of a started child process;
    - every competing starter reads back the identical receipt binding;
    - no racer overwrites the marker (bytes unchanged afterward);
    - a later mutant start is a no-op, not an error, so duplicate starts
      can never perturb observation collection.
    """
    import contact as contact_mod
    import threading
    marker_path = tmp_path / "contact.json"
    receipt_sha = "ab" * 32  # fixed immutable binding for this run

    # One live child process per racer, kept alive for the whole race:
    # the winning marker's PID must belong to a started child.
    children = [subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"])
        for _ in range(8)]
    try:
        child_pids = [c.pid for c in children]
        assert all(isinstance(p, int) and p > 0 for p in child_pids)

        # A barrier forces all eight starters onto the gate at once, so
        # the O_EXCL contention is genuine rather than incidental.
        barrier = threading.Barrier(8)
        results: list[dict] = []

        def worker(i: int) -> None:
            gate = contact_mod.ContactGate(marker_path)
            barrier.wait(timeout=60)
            results.append(
                gate.note_process_started(f"m{i}", receipt_sha,
                                          child_pids[i]))

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one successful atomic transition.
        assert len(results) == 8
        winners = [r for r in results if r["created"]]
        assert len(winners) == 1
        winner_marker = winners[0]["marker"]

        # Every competitor -- winner and losers -- reads back the
        # identical marker with the same immutable receipt binding.
        assert all(r["marker"] == winner_marker for r in results)
        assert all(r["marker"]["receipt_sha256"] == receipt_sha
                   for r in results)
        assert winner_marker["child_pid"] in child_pids
        assert winner_marker["schema"] == \
            "airlock.rsi-006-q3.scientific-contact.v1"
        assert winner_marker["event"] == "scientific_contact"

        # Exactly one marker on disk; it parses (no truncation/partial
        # write) and no racer overwrote it.
        assert [p.name for p in tmp_path.glob("*.json")] == ["contact.json"]
        on_disk = json.loads(marker_path.read_bytes())
        assert on_disk == winner_marker
        assert contact_mod.ContactGate(marker_path).consumed

        # A later mutant start is a no-op, never an error: duplicate
        # starts must not perturb observation collection.
        before = marker_path.read_bytes()
        later_gate = contact_mod.ContactGate(marker_path)
        later = later_gate.note_process_started("some-later-mutant",
                                                receipt_sha, child_pids[0])
        assert later["created"] is False
        assert later["marker"] == winner_marker
        assert marker_path.read_bytes() == before
    finally:
        for c in children:
            c.terminate()
        for c in children:
            c.wait(timeout=60)


def test_failed_submission_consumes_nothing(tmp_path):
    """A submission failure never reaches a worker: no contact."""
    import run_rsi_006_q3 as q3
    import perturb
    pool = build_fixture_pool(tmp_path / "src")
    run_stage1(pool, tmp_path, "subfail")
    work_dir = tmp_path / "work-submit-fail"
    gate = q3.contact_mod.ContactGate(work_dir / q3.CONTACT_MARKER)

    class FailingExecutor:
        def submit(self, *args, **kwargs):
            raise RuntimeError("executor unavailable")

    pkg = tmp_path / "src" / "tiny-0" / "bigpkg"
    repo = tmp_path / "src" / "tiny-0"
    muts = perturb.generate_mutants(pkg, "seed-submit-fail", 2, "t")
    cfg = {"name": "tiny-0", "repo_root": str(repo),
           "package_dir": str(pkg), "import_root": str(repo),
           "tests_dir": str(repo / "tests")}
    with pytest.raises(RuntimeError, match="executor unavailable"):
        q3._dispatch_discovery_observations(
            FailingExecutor(), {}, "tiny-0", cfg, muts, {}, work_dir,
            sys.executable, "A", gate, "r" * 64)
    assert not gate.consumed
    assert not (work_dir / q3.CONTACT_MARKER).exists()


def test_precontact_guard_failure_consumes_nothing(tmp_path, monkeypatch):
    """A failing feasibility guard stops Stage 2 before any contact."""
    import run_rsi_006_q3 as q3
    q3, pool, receipt_path = _fixture_stage2_setup(tmp_path)
    monkeypatch.setattr(q3, "POOL", pool)
    # Budgets far below the Q-STAB reachability minimum: the guard must
    # fail before any mutant is generated or observed.
    monkeypatch.setattr(q3, "BUDGETS",
                        {e["name"]: (2, 2, 1, 1) for e in pool})
    work_dir = tmp_path / "work-guard-fail"
    pool_dir = tmp_path / "pool-s2"
    report = q3.qualify_science(work_dir, pool_dir, 1, sys.executable,
                               receipt_path)
    assert report["verdict"] == "INCONCLUSIVE_RSI_006_Q3_PRECONDITION_FAILURE"
    assert report["precondition_failures"]
    assert not (work_dir / q3.CONTACT_MARKER).exists()
    assert not (work_dir / "records").exists()
    assert "scientific_contact" not in report


def _receipt_and_pool_dir(tmp_path, tag="rec"):
    pool = build_fixture_pool(tmp_path / "src")
    receipt_path = run_stage1(pool, tmp_path, tag)
    return receipt_path, tmp_path / f"pool-{tag}"


def test_receipt_rejects_tampered_baseline_vector(tmp_path):
    """A tampered baseline vector breaks its frozen hash: Stage 2 refuses."""
    receipt_path, pool_dir = _receipt_and_pool_dir(tmp_path)
    rec = json.loads(receipt_path.read_bytes())
    name = next(iter(rec["baseline_vectors"]))
    vec = rec["baseline_vectors"][name]
    key = next(iter(vec))
    vec[key] = "failed" if vec[key] == "passed" else "passed"
    receipt_path.write_bytes(
        json.dumps(rec, indent=1, sort_keys=True).encode("utf-8") + b"\n")
    with pytest.raises(receipt_mod.ReceiptError):
        receipt_mod.verify_receipt(receipt_path, pool_dir, sys.executable)


def test_receipt_rejects_code_drift(tmp_path, monkeypatch):
    receipt_path, pool_dir = _receipt_and_pool_dir(tmp_path)
    live = receipt_mod.live_code_hashes()
    live["observe.py"] = "0" * 64
    monkeypatch.setattr(receipt_mod, "live_code_hashes", lambda: live)
    with pytest.raises(receipt_mod.ReceiptError, match="code drift"):
        receipt_mod.verify_receipt(receipt_path, pool_dir, sys.executable)


def test_receipt_rejects_interpreter_drift(tmp_path):
    receipt_path, pool_dir = _receipt_and_pool_dir(tmp_path)
    with pytest.raises(receipt_mod.ReceiptError):
        receipt_mod.verify_receipt(receipt_path, pool_dir,
                                   "/nonexistent/python-xyz")


def test_receipt_rejects_dependency_drift(tmp_path, monkeypatch):
    receipt_path, pool_dir = _receipt_and_pool_dir(tmp_path)
    monkeypatch.setattr(receipt_mod, "dependency_lock",
                        lambda python, pkgs: {"pytest": "0.0.0-fake"})
    with pytest.raises(receipt_mod.ReceiptError,
                       match="dependency lock drift"):
        receipt_mod.verify_receipt(receipt_path, pool_dir, sys.executable)


def test_launch_evidence_byte_exact(tmp_path):
    """Sidecar bytes decode to exactly the hashed/length-bound payloads."""
    import base64
    import perturb
    repo = tmp_path / "repo"
    (repo / "bigpkg").mkdir(parents=True)
    (repo / "bigpkg" / "__init__.py").write_text("")
    pkg_src, test_src = _bigpkg_sources()
    (repo / "bigpkg" / "mod.py").write_text(pkg_src)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_mod.py").write_text(test_src)
    cfg = {"name": "tiny", "repo_root": str(repo),
           "package_dir": str(repo / "bigpkg"),
           "import_root": str(repo), "tests_dir": str(repo / "tests")}
    work = tmp_path / "work"
    work.mkdir()
    base, _ = observe.observe_baseline(cfg, work, sys.executable)
    muts = perturb.generate_mutants(repo / "bigpkg", "seed-evidence", 1, "t")
    out = observe.observe_mutant(cfg, muts[0], base, work, sys.executable)
    launch = out["launch"]
    assert launch["disposition"] == "ok"
    # A killed mutant exits nonzero; byte-exactness is what matters here.
    assert launch["exit_status"] in (0, 1)
    assert isinstance(launch["child_pid"], int) and launch["child_pid"] > 0
    assert launch["end_ts"] >= launch["start_ts"]
    for stream in ("stdout", "stderr"):
        ev = launch[stream]
        raw = base64.b64decode(ev["bytes_b64"])
        assert hashlib.sha256(raw).hexdigest() == ev["sha256"]
        assert len(raw) == ev["len"]
    junit = launch["junit_xml"]
    assert junit is not None
    junit_raw = base64.b64decode(junit["bytes_b64"])
    assert hashlib.sha256(junit_raw).hexdigest() == junit["sha256"]
    assert len(junit_raw) == junit["len"]
    # The preserved JUnit bytes parse to exactly the recorded outcomes.
    assert observe.parse_junitxml_bytes(junit_raw) == out["record"]["outcomes"]


def test_stage1_failure_then_repaired_repeat(tmp_path):
    """Stage 1 fails with evidence, then a repaired invocation goes green."""
    pool = build_fixture_pool(tmp_path / "src", n_repos=1, write_tests=False)
    work_bad = tmp_path / "env-bad2"
    pool_bad = tmp_path / "pool-bad2"
    with pytest.raises(env_qualify.EnvironmentNotReady):
        env_qualify.qualify_environment(
            pool, work_bad, pool_bad, sys.executable, False,
            work_bad / "environment-receipt.json")
    assert not (work_bad / "environment-receipt.json").exists()
    assert not (work_bad / "scientific-contact.json").exists()

    # Repair: add the missing tests and commit; the pool pin follows the
    # repaired tree (repair is a new environment, not a rescue).
    repo = tmp_path / "src" / "tiny-0"
    _, test_src = _bigpkg_sources()
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_mod.py").write_text(test_src)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "repair"],
                   check=True, capture_output=True)
    pool[0]["sha"] = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()

    work_ok = tmp_path / "env-ok"
    receipt_path = work_ok / "environment-receipt.json"
    env_qualify.qualify_environment(
        pool, work_ok, tmp_path / "pool-ok", sys.executable, False,
        receipt_path)
    assert receipt_path.exists()
    assert not (work_ok / "scientific-contact.json").exists()
    assert not (work_ok / "records").exists()


def test_pip_install_evidence_shape(tmp_path, monkeypatch):
    """Pip evidence carries argv/interpreter/cwd/env/outputs/lock/timestamps."""
    real_subprocess = subprocess

    def fake_run(argv, **kwargs):
        assert argv[:3] == [sys.executable, "-m", "pip"]
        return real_subprocess.CompletedProcess(argv, 0, b"ok\n", b"")

    monkeypatch.setattr(env_qualify.subprocess, "run", fake_run)
    monkeypatch.setattr(receipt_mod, "dependency_lock",
                        lambda python, pkgs: {pkgs[0]: "9.9.9"})
    ev = env_qualify._pip_install(sys.executable, "pytest", tmp_path)
    assert (tmp_path / "pip-install-pytest.json").exists()
    launch = ev["launch"]
    assert launch["argv"] == [sys.executable, "-m", "pip", "install",
                              "pytest"]
    assert launch["interpreter"] == str(Path(sys.executable).resolve())
    assert launch["cwd"] == os.getcwd()
    assert launch["exit_status"] == 0
    assert launch["disposition"] == "ok"
    for field in ("env_fingerprint", "stdout", "stderr",
                  "start_ts", "end_ts"):
        assert field in launch, field
    assert launch["end_ts"] >= launch["start_ts"]
    assert ev["dependency_lock"] == {"pytest": "9.9.9"}


def test_self_check_clean():
    import run_rsi_006_q3 as q3
    q3.self_check()  # raises on any frozen-property violation
