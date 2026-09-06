from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
REACHABILITY = ROOT / "scripts/verify_unattended_reachability.py"


def load_reachability():
    spec = importlib.util.spec_from_file_location(
        "verify_unattended_reachability",
        REACHABILITY,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load reachability verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CIDownstreamTraceTests(unittest.TestCase):
    def test_actions_runtime_continues_independent_downstream_checks_after_reachability_failure(self):
        text = WORKFLOW.read_text()
        continuation = "if: ${{ always() && steps.reachability.outcome != 'skipped' }}"

        docker_at = text.index("- run: docker version")
        selftest_at = text.index("- id: actions_selftest")
        upload_at = text.index("- uses: actions/upload-artifact@v4", selftest_at)

        self.assertIn(
            continuation,
            text[docker_at:selftest_at],
        )
        self.assertIn(
            continuation,
            text[selftest_at:upload_at],
        )
        self.assertIn(
            "if: ${{ always() && steps.actions_selftest.outcome != 'skipped' }}",
            text[upload_at:],
        )

    def test_reachability_artifact_preserves_exact_failed_command_evidence(self):
        module = load_reachability()
        rows = [
            {
                "candidate_id": "01",
                "disposition": "BLOCKED",
                "reason": "TESTS_FAILED",
                "checks": [
                    {
                        "rule": "regression",
                        "status": "FAIL",
                        "commands": [
                            {
                                "argv": ["python", "-m", "unittest"],
                                "exit_code": 1,
                                "timed_out": False,
                                "side_effect": False,
                                "stdout_sha256": "a" * 64,
                                "stderr_sha256": "b" * 64,
                                "stdout_tail": "partial stdout",
                                "stderr_tail": "exact failure evidence",
                            }
                        ],
                    }
                ],
            }
        ]

        diagnostics = module.candidate_diagnostics(rows)
        command = diagnostics[0]["failed_checks"][0]["commands"][0]

        self.assertEqual(command["argv"], ["python", "-m", "unittest"])
        self.assertEqual(command["exit_code"], 1)
        self.assertEqual(command["stdout_sha256"], "a" * 64)
        self.assertEqual(command["stderr_sha256"], "b" * 64)
        self.assertEqual(command["stdout_tail"], "partial stdout")
        self.assertEqual(command["stderr_tail"], "exact failure evidence")


if __name__ == "__main__":
    unittest.main()
