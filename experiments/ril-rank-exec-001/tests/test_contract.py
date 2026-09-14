import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runner", ROOT / "run_ril_rank_exec_001.py")
M = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(M)


class ContractTests(unittest.TestCase):
    def test_family_boundary(self):
        prior = {"parsing", "state-transition", "aggregation", "validation", "caching", "pagination", "retry", "schema-migration"}
        self.assertTrue(set(M.FAMILIES).isdisjoint(prior))

    def test_budget_and_claim_boundary(self):
        p = json.loads((ROOT / "RIL_RANK_EXEC_001_PREREGISTRATION.json").read_text())
        self.assertEqual(p["primary_metric"]["evaluation_budget"], 4)
        self.assertTrue(p["claim_boundary"][0].startswith("A pass establishes only executable transfer"))
        self.assertEqual(p["level4_standing"], "NOT_EARNED")

    def test_exact_policy_hash(self):
        self.assertEqual(M.sha256_file(ROOT / "frozen" / "RIL_RANK_001_POLICY_SEAL.json"), M.POLICY_SEAL_SHA256)

    def test_smoke_executes_all_families(self):
        nonce = "11" * 32
        data = "22" * 32
        for family in M.FAMILIES:
            task = M.make_task(family, 0, data)
            cands = M.generate_candidates(nonce, family, 0)
            outs = [M.evaluate_candidate(family, task, c) for c in cands]
            self.assertEqual(len(outs), 12)
            self.assertTrue(all(o["baseline_operations"] > 0 for o in outs))


if __name__ == "__main__":
    unittest.main()
