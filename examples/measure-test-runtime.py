"""Example operator-owned metric: emit one JSON value on the final stdout line."""

from __future__ import annotations

import json
import subprocess
import sys
import time


started = time.perf_counter()
result = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=False,
)
elapsed = time.perf_counter() - started
if result.returncode:
    sys.stderr.buffer.write(result.stderr[-4000:])
    raise SystemExit(result.returncode)
print(json.dumps({"value": elapsed}))
