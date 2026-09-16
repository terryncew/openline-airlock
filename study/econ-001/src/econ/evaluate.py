"""Local isolated evaluator.

Threat model (stated, not oversold): the candidate code is model-generated
and untrusted in the accidental sense (infinite loops, runaway memory,
stray file writes). The evaluator runs it in a fresh temp dir, as a
subprocess, with a wall-clock timeout and no network inheritance beyond
the loopback-disabled environment. This is NOT a hostile-worker sandbox;
constructor limits here are accident containment, and no containment
claim against an adversarial worker is made.

Verdict is 0/1: all hidden tests pass, or not. Anything else (timeout,
traceback, missing file) is 0 with a recorded reason.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap


def evaluate(target_filename: str, candidate_code: str,
             support_files: dict[str, str], hidden_tests: str,
             timeout_s: float = 30.0) -> tuple[int, str]:
    if not candidate_code or not candidate_code.strip():
        return 0, "empty_candidate"
    with tempfile.TemporaryDirectory(prefix="econ_eval_") as td:
        for name, content in (support_files or {}).items():
            p = os.path.join(td, name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(content)
        with open(os.path.join(td, target_filename), "w") as f:
            f.write(candidate_code)
        test_path = os.path.join(td, "test_hidden.py")
        with open(test_path, "w") as f:
            f.write(hidden_tests)
        runner = textwrap.dedent("""\
            import sys, traceback
            sys.path.insert(0, %r)
            try:
                import test_hidden
                test_hidden.run()
            except AssertionError as e:
                print("ASSERT_FAIL:" + str(e)[:300]); sys.exit(10)
            except Exception:
                traceback.print_exc(limit=3); sys.exit(11)
            print("ALL_PASS")
            """) % td
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # No network for the child: remove proxy vars; loopback stays local.
        try:
            proc = subprocess.run(
                [sys.executable, "-c", runner],
                cwd=td, env=env, timeout=timeout_s,
                capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            return 0, "timeout"
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and "ALL_PASS" in out:
            return 1, "all_pass"
        if "ASSERT_FAIL" in out:
            return 0, "assertion_failed"
        return 0, f"error_rc{proc.returncode}:" + out[-300:]
