"""Q6 test fixtures: durable work dirs (never /tmp)."""

import os
import shutil
from pathlib import Path

import pytest

# NOTE: No global COLUMNS/LINES pin. The Q6 mechanism binds the ACTUAL
# prepared environment values (see test_09_f1.py which parameterizes
# explicit values, and test_14_env_binding.py which proves drift ->
# refusal). Tests that launch the recorder inherit the ambient env;
# if the harness injects terminal vars into subprocesses, those tests
# document the injection rather than silently normalizing it.

SCRATCH = Path(__file__).resolve().parent / "_scratch"


@pytest.fixture
def work_dir(tmp_path_factory):
    """A durable work dir under the Q6 tests tree (never /tmp).

    Earned scope: same-host filesystem outside /tmp, surviving
    coordinator-process death during the test. No reboot, host-crash,
    or power-loss claim is established by these fixtures.
    """
    d = SCRATCH / "wq6"
    d.mkdir(parents=True, exist_ok=True)
    # Unique per test via the factory's basename.
    sub = Path(str(tmp_path_factory.mktemp("q6")))
    target = d / sub.name
    target.mkdir(parents=True, exist_ok=True)
    yield target
    shutil.rmtree(target, ignore_errors=True)


@pytest.fixture
def explicit_env():
    """Explicit terminal-env control for recorder tests.

    Sets COLUMNS/LINES to known values for the duration of the test,
    restoring the ambient values afterward. This is explicit per-test
    control, not a silent global pin. The values are arbitrary; the
    mechanism must bind whatever is actually present.
    """
    old_columns = os.environ.get("COLUMNS")
    old_lines = os.environ.get("LINES")
    os.environ["COLUMNS"] = "80"
    os.environ["LINES"] = "24"
    try:
        yield ("80", "24")
    finally:
        if old_columns is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = old_columns
        if old_lines is None:
            os.environ.pop("LINES", None)
        else:
            os.environ["LINES"] = old_lines
