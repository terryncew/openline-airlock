"""Shared fixtures for Q6 mechanism tests (fixture-only, no scientific)."""

import hashlib
import json
import os
import sys
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent.parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q4_DIR = Q6_DIR.parent / "rsi-006-q4-durable-transaction"
Q3_DIR = Q6_DIR.parent / "rsi-006-q3-substrate-qualification"
for _d in (str(Q6_DIR), str(Q5_DIR), str(Q4_DIR), str(Q3_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)


TESTS_DIR = str(Q6_DIR / "tests")
# The recorder subprocess must import fixture_builders; it inherits the
# coordinator's environment, so PYTHONPATH is set here once.
_pp = os.environ.get("PYTHONPATH", "")
if TESTS_DIR not in _pp.split(os.pathsep):
    os.environ["PYTHONPATH"] = TESTS_DIR + (
        os.pathsep + _pp if _pp else "")

import q6_adapter  # noqa: E402
import q6_recorder  # noqa: E402
from contact import ContactGate  # noqa: E402
from stransaction import ScientificTransaction  # noqa: E402

RECEIPT_SHA = "0" * 64
CODE_HASHES = {"q6-test": "fixture"}


def make_tx(work_dir):
    """Begin a fresh fixture transaction."""
    nonce = hashlib.sha256(os.urandom(32)).hexdigest()
    return ScientificTransaction.begin(
        work_dir, receipt_sha256=RECEIPT_SHA, code_hashes=CODE_HASHES,
        tx_nonce=nonce)


def open_tx(work_dir):
    """Open an existing fixture transaction (successor)."""
    return ScientificTransaction.open(
        work_dir, receipt_sha256=RECEIPT_SHA, code_hashes=CODE_HASHES)


def make_gate(work_dir):
    return ContactGate(Path(work_dir) / "contact_marker.json")


def make_coordinator(work_dir, tx=None, gate=None):
    tx = tx or make_tx(work_dir)
    gate = gate or make_gate(work_dir)
    return q6_adapter.Q6Coordinator(
        work_dir=work_dir, tx=tx, gate=gate,
        receipt_sha256=RECEIPT_SHA, code_hashes=CODE_HASHES)


class FixtureSpawn:
    """Minimal spawn object carrying the q6_prep for _worker_run."""

    def __init__(self, observation_id, *, phase="discovery", attempt=1,
                 child_argv=None, run_dir=None, timeout_s=30,
                 env_overrides=None):
        self.observation_id = observation_id
        self.phase = phase
        self.attempt = attempt
        self.child_argv = child_argv or [sys.executable, "-c", "pass"]
        self.run_dir = Path(run_dir) if run_dir else Path.cwd()
        self.env = dict(os.environ)
        self.timeout_s = timeout_s
        self.repo_name = "fixture-repo"
        self.mutant = {"mutant_id": "fixture-mutant"}
        self.baseline = {}
        self.python = sys.executable
        self.junit_path = str(self.run_dir / "junit.xml")
        # q6_prep mirrors the runner's prep dict: the full spawn fields
        # plus the Q6 scientific bindings.
        self.q6_prep = {
            "classification": "scientific",
            "argv": list(self.child_argv),
            "run_dir": self.run_dir,
            "env": dict(self.env),
            "repo_name": self.repo_name,
            "mutant": dict(self.mutant),
            "baseline": dict(self.baseline),
            "python": self.python,
            "junit_path": self.junit_path,
            "builder_context": {},
            "env_overrides": dict(env_overrides or {}),
            "timeout_s": timeout_s,
            "builder": "fixture_builders.fixture_completion",
            "spawn_failure_builder":
                "fixture_builders.fixture_spawn_failure",
        }
        self.child_pid = None
        self.exec_nonce = None
        self._finished = False
        # prep["env"] is the exact child env: os.environ + overrides.
        _env = dict(self.env)
        _env.update(self.q6_prep["env_overrides"])
        self.q6_prep["env"] = _env

    def mark_finished(self, observation_id):
        self._finished = True


def ledger_file(work_dir, observation_id, name):
    return (Path(work_dir) / "artifacts" / "execution_ledger" /
            f"{observation_id}.{name}.json")


def read_json(path):
    return json.loads(Path(path).read_bytes())


def run_fixture(coord, spawn):
    """Drive one fixture observation through Q6Coordinator._worker_run."""
    return coord._worker_run(
        observation_id=spawn.observation_id, phase=spawn.phase,
        spawn=spawn, argv=spawn.child_argv, barrier=None,
        _crash_hook=None, completion_builder=object(),
        spawn_failure_builder=object())
