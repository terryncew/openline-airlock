"""F1 fixture scientific child: proves physical execution count.

Signals READY via a file, blocks until the release file appears, then
exits 0. Writes one fsync'd line per physical execution to the marker
file (append mode): the parent test asserts exactly one line, proving
exactly one physical scientific child execution -- not inferred from
ledger filename counts.

Usage: f1_child.py <ready_file> <release_file> <marker_file>
Fixture-only. Never scientific contact, never the real Q3 workload.
"""

import os
import sys
import time
from pathlib import Path


def main(argv):
    ready_file, release_file, marker_file = argv[1], argv[2], argv[3]
    # Fsync'd execution marker FIRST: one append per physical execution.
    # If the child ever ran twice, the marker holds two lines.
    with open(marker_file, "ab") as f:
        f.write(f"executed pid={os.getpid()}\n".encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    # Signal READY to the parent test.
    Path(ready_file).write_text(f"ready pid={os.getpid()}\n",
                                encoding="utf-8")
    # Block until the parent releases us.
    deadline = time.monotonic() + 300
    while not Path(release_file).exists():
        if time.monotonic() > deadline:
            sys.exit("f1_child: release timeout")
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
