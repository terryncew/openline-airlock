"""RSI-006-Q6 runner: Q6Stage2Runner + scoped qa proxy injection.

Q6Stage2Runner(run_rsi_006_q5.Stage2Runner) overrides ONLY _spawn_for:
call the frozen parent, attach spawn.q6_prep = self._prep[observation_id],
return spawn.

q6_injection() scopes a proxy over run_rsi_006_q5.qa: Coordinator
resolves to q6_adapter.Q6Coordinator; every other attribute delegates
to the frozen q5_adapter module. The exact original alias is restored
in finally, on success and on exception. q5_adapter itself is never
mutated. run_q6() builds the Q6 runner and calls frozen parent run().
"""

import contextlib
import sys
from pathlib import Path

Q6_DIR = Path(__file__).resolve().parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q3_DIR = Q6_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(Q6_DIR), str(Q5_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_rsi_006_q5  # noqa: E402
import q5_adapter  # noqa: E402
from q6_adapter import Q6Coordinator  # noqa: E402


class Q6Stage2Runner(run_rsi_006_q5.Stage2Runner):
    """Q6 runner: only _spawn_for is overridden."""

    def _spawn_for(self, observation_id):
        spawn = super()._spawn_for(observation_id)
        spawn.q6_prep = self._prep[observation_id]
        return spawn


class _Q6QAProxy:
    """Scoped run_rsi_006_q5.qa stand-in: Coordinator -> Q6Coordinator."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "Coordinator":
            return Q6Coordinator
        return getattr(q5_adapter, name)


@contextlib.contextmanager
def q6_injection():
    """Scope the qa proxy; restore the exact original alias in finally."""
    original = run_rsi_006_q5.qa
    run_rsi_006_q5.qa = _Q6QAProxy()
    try:
        yield
    finally:
        run_rsi_006_q5.qa = original


def run_q6(*, stage2_dir, pool, pool_dir, budgets, python, receipt_path,
           workers, code_hashes, crash_points=None, **kwargs):
    """Build the Q6 runner; call the frozen parent run() injected."""
    with q6_injection():
        runner = Q6Stage2Runner(
            stage2_dir=stage2_dir, pool=pool, pool_dir=pool_dir,
            budgets=budgets, python=python, receipt_path=receipt_path,
            workers=workers, code_hashes=code_hashes, **kwargs)
        return runner.run(crash_points=crash_points)
