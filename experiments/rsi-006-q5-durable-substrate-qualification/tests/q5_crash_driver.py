#!/usr/bin/env python
"""Subprocess driver for Q5 runner crash-injection tests.

Builds the fixture Stage2Runner on an already-prepared work dir
(package + frozen fixture receipt) and runs it with the given crash
points. Runs in a SUBPROCESS because crash injection kills the process
(``os._exit`` in adapter crash windows; ``qa._Crash`` at phase-level
hooks) -- in-process crashes would kill the test runner itself.

Usage: q5_crash_driver.py <repo_root> <receipt_path> <stage2_dir> <crash_points_json>
On success prints a JSON result line and exits 0; on an injected crash
the process dies with a non-zero exit and no result line.
"""

import json
import os
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
EXP_DIR = TESTS_DIR.parent
Q3_DIR = EXP_DIR.parent / "rsi-006-q3-substrate-qualification"
for _p in (str(TESTS_DIR), str(EXP_DIR), str(Q3_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from q5_fixture_support import make_runner, repo_cfg, REPO_NAME  # noqa: E402


def _fixture_nonce_source():
    """Test-only confirmation-nonce injection for the crash driver.

    Reads ``Q5_FIXTURE_CONFIRMATION_NONCE`` (a fixed 64-hex fixture
    nonce), ``Q5_FIXTURE_NONCE_COUNT_PATH`` (a file receiving one line
    per source call, tagged), and ``Q5_FIXTURE_NONCE_TAG``. Returns None
    (production OS-entropy source) when the env vars are absent. There
    is no CLI flag: this is internal to the fixture harness.
    """
    value = os.environ.get("Q5_FIXTURE_CONFIRMATION_NONCE")
    if not value:
        return None
    count_path = os.environ.get("Q5_FIXTURE_NONCE_COUNT_PATH")
    tag = os.environ.get("Q5_FIXTURE_NONCE_TAG", "doomed")

    def source() -> str:
        if count_path:
            with open(count_path, "a") as fh:
                fh.write(tag + "\n")
        return value

    return source


def main() -> None:
    repo_root = Path(sys.argv[1])
    receipt_path = Path(sys.argv[2])
    stage2 = Path(sys.argv[3])
    crash_points = json.loads(sys.argv[4])
    cfg = repo_cfg(repo_root)
    runner = make_runner(stage2, receipt_path, {REPO_NAME: cfg},
                         workers=1,
                         confirmation_nonce_source=_fixture_nonce_source())
    result = runner.run(crash_points=crash_points)
    sys.stdout.write(json.dumps({
        "status": result["status"],
        "terminal": result.get("terminal"),
        "report_path": result.get("report_path"),
    }) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
