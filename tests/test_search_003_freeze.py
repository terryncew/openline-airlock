from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_search_003_freeze.py"
SPEC = importlib.util.spec_from_file_location("verify_search_003_freeze", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class Search003FreezeTests(unittest.TestCase):
    def test_committed_primary_result_verifies(self) -> None:
        report = VERIFY.verify_freeze(ROOT)
        self.assertTrue(report["valid"])
        self.assertEqual(report["verdict"], "MARGINAL_VALUE_GAIN")
        self.assertEqual(
            report["accepted_order"],
            ["slug_empty_fallback", "retry_zero_attempts", "git_snapshot_single_query"],
        )
        self.assertFalse(report["economic_efficiency_earned"])
        self.assertFalse(report["rerun_required"])

    def test_result_byte_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / VERIFY.RESULT_REL
            freeze = root / VERIFY.FREEZE_REL
            result.parent.mkdir(parents=True)
            shutil.copy2(ROOT / VERIFY.RESULT_REL, result)
            shutil.copy2(ROOT / VERIFY.FREEZE_REL, freeze)
            payload = json.loads(result.read_text())
            payload["reported_autonomous_cost"] = 1.0
            result.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            with self.assertRaisesRegex(VERIFY.FreezeError, "result bytes changed"):
                VERIFY.verify_freeze(root)

    def test_freeze_cannot_promote_zero_reported_cost_into_economics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = root / VERIFY.RESULT_REL
            freeze = root / VERIFY.FREEZE_REL
            result.parent.mkdir(parents=True)
            shutil.copy2(ROOT / VERIFY.RESULT_REL, result)
            payload = json.loads((ROOT / VERIFY.FREEZE_REL).read_text())
            payload["boundaries"]["economic_efficiency_earned"] = True
            freeze.write_text(json.dumps(payload, indent=2) + "\n")
            with self.assertRaisesRegex(VERIFY.FreezeError, "economics claim"):
                VERIFY.verify_freeze(root)


if __name__ == "__main__":
    unittest.main()
