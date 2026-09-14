from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
RUNNER = HERE / "run_ril_rank_live_001.py"
spec = importlib.util.spec_from_file_location("ril_rank_live_001_runner", RUNNER)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class ContractTests(unittest.TestCase):
    def test_parse_json_object_accepts_plain_and_fenced(self):
        self.assertEqual(mod.parse_json_object('{"evaluation_order":["a","b","c","d"]}') ["evaluation_order"], ["a","b","c","d"])
        self.assertEqual(mod.parse_json_object('```json\n{"evaluation_order":["a","b","c","d"]}\n```')["evaluation_order"], ["a","b","c","d"])

    def test_validate_live_order_requires_exact_shortlist_permutation(self):
        shortlist = ["a", "b", "c", "d"]
        self.assertEqual(mod.validate_live_order({"evaluation_order": ["d", "b", "a", "c"]}, shortlist), (True, ["d", "b", "a", "c"]))
        self.assertEqual(mod.validate_live_order({"evaluation_order": ["a", "b", "c", "x"]}, shortlist), (False, []))
        self.assertEqual(mod.validate_live_order({"evaluation_order": ["a", "a", "b", "c"]}, shortlist), (False, []))

    def test_classification_requires_rate_eval_and_cost_efficiency(self):
        base = {
            "confirmed_improvement_rate": 0.25,
            "receiver_evaluations_used_total": 60,
            "confirmed_improvements_per_live_model_usd": 4.0,
        }
        evidence = {
            "confirmed_improvement_rate": 0.50,
            "receiver_evaluations_used_total": 48,
            "confirmed_improvements_per_live_model_usd": 5.0,
        }
        self.assertEqual(mod.classify(evidence, base, True, True), "PASS_RIL_RANK_LIVE_001_OBSERVED_LIVE_TRANSFER")
        evidence["confirmed_improvements_per_live_model_usd"] = 3.0
        self.assertEqual(mod.classify(evidence, base, True, True), "LIVE_TRANSFER_WITH_MODEL_COST_PENALTY")
        self.assertEqual(mod.classify(evidence, base, False, True), "INCONCLUSIVE_RIL_RANK_LIVE_001_LIVE_EXECUTION")
        self.assertEqual(mod.classify(evidence, base, True, False), "INCONCLUSIVE_RIL_RANK_LIVE_001_ECONOMICS")

    def test_prompt_exposes_full_pool_and_exact_budget(self):
        cands = [
            {"candidate_id": f"c{i}", "features": {"strategy":"cache", "scope":"broad", "evidence":"derived", "complexity":"medium"}}
            for i in range(12)
        ]
        prompt = mod.build_prompt(arm="evidence", task_id="x", public_context={"family":"dedupe-stream"}, ordered_candidates=cands)
        for i in range(12):
            self.assertIn(f"c{i}", prompt)
        self.assertIn("first 4 positions", prompt)
        self.assertIn(mod.HISTORY_TEXT, prompt)


if __name__ == "__main__":
    unittest.main()
