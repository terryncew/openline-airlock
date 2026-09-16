"""F1 coordinator driver subprocess.

Runs the ordinary Q6Coordinator path in a dedicated process that the
parent test can SIGKILL, proving real coordinator-process failure
(not `del coord`).

Modes:
  fresh      - begin the fixture transaction, construct Q6Coordinator
               through the ordinary path (kit.make_coordinator), and
               call _worker_run with a blocking fixture child. Blocks
               inside the recorder's proc.wait().
  successor  - open the existing transaction, construct Q6Coordinator,
               call _worker_run (must classify recoverable), then the
               inherited _apply (must adopt via adopt_orphan_observation),
               and write the adoption result JSON.

Usage:
  f1_driver.py fresh <work_dir> <obs_id> <ready> <release> <marker>
                     <txid_file> <child_script>
  f1_driver.py successor <work_dir> <obs_id> <ready> <release> <marker>
                         <result_file> <child_script>

Fixture-only. Never scientific contact, never the real Q3 workload.
"""

import json
import os
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
Q6_DIR = TESTS_DIR.parent
Q5_DIR = Q6_DIR.parent / "rsi-006-q5-durable-substrate-qualification"
Q4_DIR = Q6_DIR.parent / "rsi-006-q4-durable-transaction"
Q3_DIR = Q6_DIR.parent / "rsi-006-q3-substrate-qualification"
for _d in (str(Q6_DIR), str(TESTS_DIR), str(Q5_DIR), str(Q4_DIR),
           str(Q3_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import q6_testkit as kit  # noqa: E402


def main(argv):
    mode = argv[1]
    work_dir, obs_id = argv[2], argv[3]
    ready_file, release_file, marker_file = argv[4], argv[5], argv[6]
    out_file, child_script = argv[7], argv[8]

    if mode == "fresh":
        tx = kit.make_tx(work_dir)
        # Durable txid BEFORE any work, so the parent can verify identity
        # even after this process is SIGKILLed.
        Path(out_file).write_text(tx.txid, encoding="utf-8")
    elif mode == "successor":
        tx = kit.open_tx(work_dir)
    else:
        sys.exit(f"f1_driver: unknown mode {mode!r}")

    coord = kit.make_coordinator(work_dir, tx=tx)
    spawn = kit.FixtureSpawn(
        obs_id,
        child_argv=[sys.executable, child_script,
                    ready_file, release_file, marker_file],
        run_dir=work_dir,
        timeout_s=120,
    )
    # Ordinary Q6 path: _worker_run (classify -> fresh/recoverable).
    result = coord._worker_run(
        observation_id=obs_id, phase=spawn.phase,
        spawn=spawn, argv=spawn.child_argv, barrier=None,
        _crash_hook=None, completion_builder=object(),
        spawn_failure_builder=object())

    if mode == "successor":
        # Ordinary recovery ordering (mirrors run_all): reconcile the
        # ContactGate winner into the resumed Q4 transaction BEFORE any
        # observation evidence is applied, so provenance never reads
        # observation-before-authorization.
        reconciled = coord.reconcile_contact()
        applied = coord._apply(result)
        Path(out_file).write_text(json.dumps({
            "worker_result": result.get("result"),
            "applied_status": applied.get("status"),
            "digest": applied.get("digest"),
            "txid": tx.txid,
            "contact_reconciled": reconciled is not None,
            "contact_child_pid": (reconciled["event"]["child_pid"]
                                  if reconciled else None),
        }, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
