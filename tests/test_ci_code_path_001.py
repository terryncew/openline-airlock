from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments/ci-code-path-001/run_ci_code_path_001.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("ci_code_path_001", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load CI-CODE-PATH-001 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CICodePath001Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = load_runner()

    def test_preregistered_inputs_match_exact_components_and_fixture(self):
        frozen = self.runner.verify_frozen_inputs()
        self.assertEqual(
            frozen["preregistration"]["product_base_commit"],
            "bd44b59a63dab69bb05aeed39ff83d5186b21288",
        )

    def test_real_failure_earns_complete_code_repair_path(self):
        with tempfile.TemporaryDirectory(prefix="airlock-ci-code-path-test-") as td:
            result = self.runner.run_dogfood(Path(td))
            payload = result["payload"]
            self.assertEqual(payload["verdict"], "END_TO_END_CODE_REPAIR_PATH_EARNED")
            self.assertEqual(payload["route"]["recorder_disposition"], "CODE_REPAIR_ALLOWED")
            self.assertEqual(payload["route"]["doctor_decision"], "READY_FOR_REVIEW")
            self.assertEqual(payload["route"]["ordinary_evaluation"]["status"], "SURVIVED")
            self.assertTrue(all(payload["invariants"].values()))
            self.assertTrue(self.runner.verify_result(
                Path(td) / self.runner.RESULT_NAME,
                Path(td) / self.runner.PATCH_NAME,
            )["valid"])

    def test_committed_result_and_nested_receipts_verify_offline(self):
        verified = self.runner.verify_result()
        self.assertTrue(verified["valid"], verified)

    def test_result_or_patch_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="airlock-ci-code-path-tamper-") as td:
            root = Path(td)
            result = root / self.runner.RESULT_NAME
            patch = root / self.runner.PATCH_NAME
            shutil.copy2(self.runner.HERE / self.runner.RESULT_NAME, result)
            shutil.copy2(self.runner.HERE / self.runner.PATCH_NAME, patch)

            patch.write_bytes(patch.read_bytes() + b"\n# tampered\n")
            self.assertFalse(self.runner.verify_result(result, patch)["valid"])

            shutil.copy2(self.runner.HERE / self.runner.PATCH_NAME, patch)
            record = json.loads(result.read_text())
            record["payload"]["verdict"] = "CONTROL_PATH_FAILED"
            result.write_text(json.dumps(record))
            self.assertFalse(self.runner.verify_result(result, patch)["valid"])


if __name__ == "__main__":
    unittest.main()
