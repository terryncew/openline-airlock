from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from airlock.cascade import CascadeGate, CascadeLauncher


def request(request_id, parent, operation, child, root="ROOT"):
    return {
        "request_id": request_id,
        "root_id": root,
        "parent_work_id": parent,
        "operation": operation,
        "requested_child_work_id": child,
    }


class CascadeGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gate = CascadeGate(
            self.root,
            root_id="ROOT",
            max_admitted_descendants_total=4,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_frozen_sequence(self):
        rows = [
            ("01", "ROOT", "SPAWN_DESCENDANT", "A", "ALLOW", None),
            ("02", "ROOT", "SPAWN_DESCENDANT", "B", "ALLOW", None),
            ("03", "A", "SPAWN_DESCENDANT", "C", "ALLOW", None),
            ("04", "B", "SPAWN_DESCENDANT", "D", "ALLOW", None),
            ("05", "C", "SPAWN_DESCENDANT", "E", "DENY", "DESCENDANT_LIMIT_REACHED"),
            ("06", "D", "SPAWN_NEW_ROOT", "R2", "DENY", "NEW_ROOT_FORBIDDEN"),
            ("07", "A", "EXPAND_ALLOWANCE", "+4", "DENY", "ALLOWANCE_CHANGE_FORBIDDEN"),
            ("08", "A", "SPAWN_DESCENDANT", "F", "DENY", "DESCENDANT_LIMIT_REACHED"),
        ]
        for rid, parent, op, child, decision, reason in rows:
            got = self.gate.decide(request(rid, parent, op, child))
            self.assertEqual((got["decision"], got["reason"]), (decision, reason))

        state = self.gate.snapshot()
        self.assertEqual(state["admitted_descendant_count_total"], 4)
        self.assertEqual(state["root_task_count"], 1)
        self.assertEqual(set(state["known_work"]), {"ROOT", "A", "B", "C", "D"})

    def test_replay_preserves_original_allow_receipt(self):
        allowed = self.gate.decide(
            request("01", "ROOT", "SPAWN_DESCENDANT", "A")
        )
        replay = self.gate.decide(
            request("01", "ROOT", "SPAWN_DESCENDANT", "A")
        )
        self.assertEqual((replay["decision"], replay["reason"]), ("DENY", "REPLAYED_REQUEST"))
        self.assertNotEqual(allowed["receipt_file"], replay["receipt_file"])
        self.assertTrue(
            self.gate.verify_allow_receipt(
                allowed,
                requested_child_work_id="A",
            )
        )
        receipts = [
            json.loads(path.read_text())
            for path in self.gate.receipts_dir.glob("*.json")
        ]
        self.assertEqual(len([r for r in receipts if r["decision"] == "ALLOW"]), 1)

    def test_unknown_parent_and_root_swap(self):
        self.gate.decide(request("01", "ROOT", "SPAWN_DESCENDANT", "A"))
        unknown = self.gate.decide(
            request("x2", "GHOST", "SPAWN_DESCENDANT", "X")
        )
        self.assertEqual((unknown["decision"], unknown["reason"]), ("DENY", "UNKNOWN_PARENT"))
        wrong = self.gate.decide(
            request("x3", "A", "SPAWN_DESCENDANT", "Y", root="ROOT-OTHER")
        )
        self.assertEqual((wrong["decision"], wrong["reason"]), ("DENY", "ROOT_MISMATCH"))

    def test_launcher_requires_durable_allow(self):
        launcher = CascadeLauncher(self.gate)
        launched = []
        result = launcher.request_and_launch(
            request("01", "ROOT", "SPAWN_DESCENDANT", "A"),
            lambda: launched.append("A"),
        )
        self.assertTrue(result["launched"])
        forged = {
            "schema": "airlock.cascade.receipt.v1",
            "decision": "ALLOW",
            "request": request("forged", "ROOT", "SPAWN_DESCENDANT", "B"),
        }
        self.assertFalse(
            launcher.launch_with_receipt(
                forged,
                "B",
                lambda: launched.append("B"),
            )
        )
        self.assertEqual(launched, ["A"])

    def test_gate_unavailable_fails_closed(self):
        launched = []
        result = CascadeLauncher(None).request_and_launch(
            request("01", "ROOT", "SPAWN_DESCENDANT", "A"),
            lambda: launched.append("A"),
        )
        self.assertFalse(result["launched"])
        self.assertEqual(result["failure"], "GATE_UNAVAILABLE")
        self.assertEqual(launched, [])

    def test_state_survives_reload(self):
        self.gate.decide(request("01", "ROOT", "SPAWN_DESCENDANT", "A"))
        reloaded = CascadeGate(
            self.root,
            root_id="ROOT",
            max_admitted_descendants_total=4,
        )
        self.assertEqual(reloaded.snapshot()["admitted_descendant_count_total"], 1)
        replay = reloaded.decide(
            request("01", "ROOT", "SPAWN_DESCENDANT", "A")
        )
        self.assertEqual((replay["decision"], replay["reason"]), ("DENY", "REPLAYED_REQUEST"))


if __name__ == "__main__":
    unittest.main()
