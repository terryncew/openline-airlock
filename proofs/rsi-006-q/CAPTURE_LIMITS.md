# RSI-006-Q capture limits (stated, not reconstructed)

The single `--qualify` invocation was launched as:

    python run_rsi_006_q.py --qualify --work-dir /tmp/rsi-006-q --workers 2 2>&1 | tail -40

with no `pipefail`. Consequences, frozen honestly:

1. Full stdout/stderr were never written to a file. Only the final 40
   lines of the merged stream survive, preserved byte-for-byte in
   `primary-stdout-tail.txt`. The complete stream is unrecoverable.
2. The Python process's own exit status was not recorded. The shell
   pipeline reported exit 0, which is the exit status of `tail`, not of
   the runner. Normal completion of the run is evidenced by the printed
   verdict block and by the written report (`rsi-006-q-report.json`),
   not by a captured exit code.
3. The work directory `/tmp/rsi-006-q` (repository pools, per-mutant
   overlays, run dirs) no longer exists; it was ephemeral scratch and
   has been removed. The report, the stdout tail, and this note are the
   surviving evidence.

Nothing in this directory reconstructs the uncaptured bytes.
