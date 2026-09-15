"""Shared fixture builders for the Q5 runner mechanism tests.

Everything in this module is fixture-only: synthetic packages,
synthetic environment receipts, and an injectable receipt verifier.
No production Stage 1, no real repositories, no scientific contact
with the real substrate. The fixture pool is built fresh under each
test's work dir (never under /tmp: VM reboots wipe /tmp).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

EXP_DIR = Path(__file__).resolve().parent.parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(EXP_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_rsi_006_q3 as q3_run  # noqa: E402
import observe as q3_observe  # noqa: E402
from run_rsi_006_q5 import Stage2Runner, _code_hashes  # noqa: E402

REPO_NAME = "fx-pool"
# Discovery budget per half: the smallest budget at which the frozen
# Q3 feasibility guard passes on the 45-group fixture package
# (empirically probed against the real guard).
DA_N = DB_N = 36
DET_N = 2
CONF_N = 4
BUDGETS = {REPO_NAME: (DA_N, DB_N, DET_N, CONF_N)}
N_GROUPS = 45
N_TESTED_GROUPS = 35

RECEIPT_SCHEMA = "airlock.rsi-006-q5.fixture-environment-receipt.v1"


# ---------------------------------------------------------------------------
# fixture package builders
# ---------------------------------------------------------------------------

def build_fullrun_package(root: Path) -> Path:
    """The 45-group fixture package for full-run / crash tests.

    Each group contributes exactly one CMP_SWAP, one ARITH_SWAP, and
    one LOGIC_SWAP site (no number/bool literals in the package, so no
    NUM_DELTA/BOOL_FLIP/NOT_DROP sites). The first N_TESTED_GROUPS are
    covered by tests (their mutants kill); the rest are uncovered (their
    mutants survive).
    """
    pkg = root / "pkg"
    tests = root / "tests"
    pkg.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    lines = []
    for i in range(N_GROUPS):
        lines.append(f"def cmp_{i:02d}(x, y):\n    return x > y\n")
        lines.append(f"def arith_{i:02d}(a, b):\n    return a + b\n")
        lines.append(f"def logic_{i:02d}(p, q):\n    return p and q\n")
    (pkg / "mod.py").write_text("\n".join(lines))
    tlines = []
    for i in range(N_TESTED_GROUPS):
        tlines.append(
            f"from pkg.mod import cmp_{i:02d}, arith_{i:02d}, logic_{i:02d}")
    tlines.append("")
    for i in range(N_TESTED_GROUPS):
        tlines.append(
            f"def test_cmp_{i:02d}():\n    assert cmp_{i:02d}(2, 1) is True\n")
        tlines.append(
            f"def test_arith_{i:02d}():\n    assert arith_{i:02d}(1, 2) == 3\n")
        tlines.append(
            f"def test_logic_{i:02d}():\n"
            f"    assert logic_{i:02d}(True, False) is False\n")
    (tests / "test_mod.py").write_text("\n".join(tlines))
    return root


def build_tiny_package(root: Path) -> Path:
    """A package too small to pass the feasibility guard (precontact)."""
    pkg = root / "pkg"
    tests = root / "tests"
    pkg.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("def f(x):\n    return x + 1\n")
    (tests / "test_mod.py").write_text(
        "from pkg.mod import f\n\ndef test_f():\n    assert f(1) == 2\n")
    return root


def build_parity_package(root: Path) -> Path:
    """Small package exercising every parity bucket.

    - ``VARIANT_UP`` (True): a BOOL_FLIP mutant removes a parametrized
      case -> missing baseline tests.
    - ``VARIANT_DOWN`` (False): a BOOL_FLIP mutant adds a parametrized
      case -> extra tests.
    - ``unused``: covered by no test -> survivor.
    - ``tests_slow/``: a suite that outlasts a tiny timeout.
    - ``tests_killer/``: a suite whose child dies by signal (no JUnit).
    """
    pkg = root / "pkg"
    tests = root / "tests"
    slow = root / "tests_slow"
    killer = root / "tests_killer"
    for d in (pkg, tests, slow, killer):
        d.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text('''\
VARIANT_UP = True
VARIANT_DOWN = False

def classify(n):
    if n > 0:
        return "positive"
    return "non-positive"

def add(a, b):
    return a + b

def flag(x):
    return not x

def unused(x):
    if x > 100:
        return "big"
    return "small"
''')
    (tests / "test_mod.py").write_text('''\
import pytest
from pkg import mod
from pkg.mod import classify, add, flag

def test_classify_positive():
    assert classify(3) == "positive"

def test_classify_non_positive():
    assert classify(-1) == "non-positive"

def test_add():
    assert add(1, 2) == 3

def test_flag():
    assert flag(False) is True

CASES_UP = [(1, 2), (3, 4)] if mod.VARIANT_UP else [(1, 2)]

@pytest.mark.parametrize("a,b", CASES_UP)
def test_variant_up(a, b):
    assert add(a, b) == a + b

CASES_DOWN = [(1, 2), (3, 4)] if mod.VARIANT_DOWN else [(1, 2)]

@pytest.mark.parametrize("a,b", CASES_DOWN)
def test_variant_down(a, b):
    assert add(a, b) == a + b
''')
    (slow / "test_slow.py").write_text(
        "import time\n\n"
        "def test_slow():\n"
        "    time.sleep(30)\n")
    (killer / "test_killer.py").write_text(
        "import os, signal\n\n"
        "def test_killer():\n"
        "    os.kill(os.getpid(), signal.SIGKILL)\n")
    return root


# ---------------------------------------------------------------------------
# repo configs, receipts, verifiers
# ---------------------------------------------------------------------------

def repo_cfg(root: Path, name: str = REPO_NAME,
             tests_subdir: str = "tests") -> dict:
    """Q3-shaped repo config for a fixture repo root."""
    return {
        "name": name,
        "repo_root": str(root),
        "package_dir": str(root / "pkg"),
        "import_root": str(root),
        "tests_dir": str(root / tests_subdir),
    }


def tree_hash(root: Path) -> str:
    """The frozen Q3 tree hash (read-only reuse)."""
    return q3_run.tree_hash(Path(root))


def build_fixture_receipt(work_dir: Path, repo_cfgs: dict[str, dict],
                          python: str) -> Path:
    """Freeze a fixture environment receipt: baselines + tree hashes.

    The baselines are produced by Q3's own ``observe_baseline`` on the
    unmutated fixture suites -- the same helper Stage 1 uses, read-only.
    """
    work_dir = Path(work_dir)
    receipt: dict = {
        "schema": RECEIPT_SCHEMA,
        "repos": {},
        "baseline_vectors": {},
    }
    for name, cfg in repo_cfgs.items():
        base_work = work_dir / f"baseline-{name}"
        base_work.mkdir(parents=True, exist_ok=True)
        baseline, _launch = q3_observe.observe_baseline(
            cfg, base_work, python)
        assert baseline, f"fixture repo {name}: empty baseline"
        receipt["baseline_vectors"][name] = baseline
        receipt["repos"][name] = {"tree_hash": tree_hash(cfg["repo_root"])}
    path = work_dir / "fixture_receipt.json"
    path.write_bytes(
        (json.dumps(receipt, sort_keys=True, indent=1) + "\n").encode())
    return path


def receipt_sha256(receipt_path: Path) -> str:
    return hashlib.sha256(Path(receipt_path).read_bytes()).hexdigest()


def make_fixture_verifier(receipt_path: Path,
                          repo_roots: dict[str, Path]):
    """Injectable verifier: frozen receipt + live tree-hash identity.

    Re-probes the live fixture trees on every call and fails closed on
    drift, mirroring the production verifier's contract without
    touching production state.
    """
    receipt_path = Path(receipt_path)
    repo_roots = {n: Path(r) for n, r in repo_roots.items()}

    def verify() -> tuple[dict, str]:
        blob = receipt_path.read_bytes()
        sha = hashlib.sha256(blob).hexdigest()
        receipt = json.loads(blob)
        for name, root in repo_roots.items():
            live = tree_hash(root)
            frozen = receipt["repos"][name]["tree_hash"]
            if live != frozen:
                raise RuntimeError(
                    f"fixture repo {name} drifted under the receipt: "
                    f"{frozen[:16]}... -> {live[:16]}...")
        return receipt, sha

    return verify


# ---------------------------------------------------------------------------
# runner construction
# ---------------------------------------------------------------------------

def make_runner(stage2_dir: Path, receipt_path: Path,
                repo_cfgs: dict[str, dict], budgets: dict | None = None,
                python: str | None = None, workers: int = 1,
                wait_timeout_s: float = 60.0,
                confirmation_nonce_source=None) -> Stage2Runner:
    """Build a Stage2Runner bound to the fixture pool and receipt.

    ``confirmation_nonce_source`` is the internal test-only injection
    point (default: the runner's production OS-entropy source). The
    crash/resume oracle passes one fixed fixture nonce so the reference
    run and every crash variant share identical confirmation
    randomness.
    """
    repo_roots = {n: Path(c["repo_root"]) for n, c in repo_cfgs.items()}
    return Stage2Runner(
        stage2_dir=stage2_dir,
        pool=dict(repo_cfgs),
        pool_dir=str(Path(next(iter(repo_cfgs.values()))["repo_root"]).parent),
        budgets=budgets or BUDGETS,
        python=python or sys.executable,
        receipt_path=receipt_path,
        workers=workers,
        code_hashes=_code_hashes(),
        receipt_verifier=make_fixture_verifier(receipt_path, repo_roots),
        wait_timeout_s=wait_timeout_s,
        confirmation_nonce_source=confirmation_nonce_source,
    )


def journal_entries(stage2_dir: Path) -> list[dict]:
    """Read the Q4 journal entries in order (best-effort decode)."""
    journal_dir = Path(stage2_dir) / "journal"
    entries: list[dict] = []
    if not journal_dir.is_dir():
        return entries
    for path in sorted(journal_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        try:
            entries.append(json.loads(blob))
        except ValueError:
            entries.append({"_raw_file": path.name,
                            "_raw_sha256": hashlib.sha256(blob).hexdigest()})
    return entries


def contact_events(stage2_dir: Path) -> list[dict]:
    """Journal entries of type ``contact``, in seq order."""
    return [e for e in journal_entries(stage2_dir)
            if isinstance(e, dict) and e.get("type") == "contact"]


def observation_commits(stage2_dir: Path) -> list[dict]:
    """Journal entries committing or adopting observations, in order."""
    return [e for e in journal_entries(stage2_dir)
            if isinstance(e, dict)
            and e.get("type") in ("observation", "observation_adopted")]
