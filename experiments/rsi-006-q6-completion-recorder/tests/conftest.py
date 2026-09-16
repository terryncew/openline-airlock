"""Q6 test fixtures: durable work dirs (never /tmp)."""

import os
import shutil
from pathlib import Path

import pytest

# Pin volatile terminal vars so the recorder subprocess (which inherits
# os.environ via Popen) sees the same values the test captured. The
# terminal driver injects COLUMNS/LINES into subprocesses otherwise.
os.environ["COLUMNS"] = "80"
os.environ["LINES"] = "24"

SCRATCH = Path(__file__).resolve().parent / "_scratch"


@pytest.fixture
def work_dir(tmp_path_factory):
    """A durable work dir under the Q6 tests tree (survives reboot)."""
    d = SCRATCH / "wq6"
    d.mkdir(parents=True, exist_ok=True)
    # Unique per test via the factory's basename.
    sub = Path(str(tmp_path_factory.mktemp("q6")))
    target = d / sub.name
    target.mkdir(parents=True, exist_ok=True)
    yield target
    shutil.rmtree(target, ignore_errors=True)
