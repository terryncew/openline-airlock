import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ril_rank_001", HERE / "run_ril_rank_001.py")
M = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(M)


class RILRank001Tests(unittest.TestCase):
    def test_candidate_generation_is_unique_and_fixed_size(self):
        rows = M.generate_candidates("01" * 32, "x", 0)
        self.assertEqual(len(rows), M.CANDIDATES_PER_TASK)
        self.assertEqual(len({r["candidate_id"] for r in rows}), M.CANDIDATES_PER_TASK)

    def test_shuffled_history_preserves_each_task_outcome_multiset(self):
        rows = M.evaluate_family_tasks(
            families=("f",),
            tasks_per_family=3,
            candidate_nonce="01" * 32,
            world_nonce="02" * 32,
            outcome_nonce="03" * 32,
        )
        shuffled = M.shuffled_history(rows, "04" * 32)
        for task_id in {r["task_id"] for r in rows}:
            before = sorted((r["accepted"], r["reason"], r["gain"]) for r in rows if r["task_id"] == task_id)
            after = sorted((r["accepted"], r["reason"], r["gain"]) for r in shuffled if r["task_id"] == task_id)
            self.assertEqual(before, after)

    def test_learned_order_has_no_family_argument(self):
        rows = M.evaluate_family_tasks(
            families=("f",),
            tasks_per_family=2,
            candidate_nonce="01" * 32,
            world_nonce="02" * 32,
            outcome_nonce="03" * 32,
        )
        model = M.build_rank_model(rows)
        candidates = M.generate_candidates("04" * 32, "holdout-a", 1)
        order = M.learned_order(model, candidates)
        self.assertEqual(set(order), {c["candidate_id"] for c in candidates})

    def test_miss_consumes_full_budget_and_is_visible(self):
        candidates = [
            {"candidate_id": f"c{i}", "features": {"strategy": "guard", "scope": "narrow", "evidence": "direct", "complexity": "low"}}
            for i in range(6)
        ]
        outcomes = {
            c["candidate_id"]: {"candidate_id": c["candidate_id"], "gain": -1.0, "accepted": False}
            for c in candidates
        }
        scored = M.score_order([c["candidate_id"] for c in candidates], outcomes, 4)
        self.assertFalse(scored["found_acceptable"])
        self.assertIsNone(scored["evaluations_to_first_acceptable"])
        self.assertEqual(scored["evaluations_used"], 4)
        self.assertEqual(scored["censored_evaluations_to_first_acceptable"], 5)

    def test_positive_verdict_requires_both_controls(self):
        self.assertEqual(
            M.classify(0.70, 0.60, 0.60),
            "PASS_RIL_RANK_001_HISTORY_RANKING_SIGNAL",
        )
        self.assertEqual(
            M.classify(0.70, 0.60, 0.68),
            "RANKING_ADVANTAGE_HISTORY_SIGNAL_NOT_ESTABLISHED",
        )
        self.assertNotEqual(
            M.classify(0.62, 0.60, 0.60),
            "PASS_RIL_RANK_001_HISTORY_RANKING_SIGNAL",
        )

    def test_break_even_requires_positive_savings(self):
        self.assertIsNone(M.break_even(100, 0, 20))
        self.assertIsNone(M.break_even(100, -3, 20))
        self.assertEqual(M.break_even(100, 20, 20), 100)


if __name__ == "__main__":
    unittest.main()
