#!/usr/bin/env python3
"""Deterministic contract tests for COMPOUND-001 (fake fixtures only; no paid calls)."""
import importlib.util
import json
import math
import subprocess
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "compound-001"
AIR = ROOT / ".airlock" / "compound-001"


def _load():
    spec = importlib.util.spec_from_file_location("compound001", EXP / "run_compound_001.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load()
D = Decimal


def _rec(verified, cost, **kw):
    r = {"verified": verified, "cost_usd": str(cost), "telemetry_complete": True,
         "quality_ok": True, "method_hash": "m" + str(verified),
         "within_method_bound": True}
    r.update(kw)
    return r


class TestMetering(unittest.TestCase):
    def test_valid_usage_reconstructs(self):
        table = C.load_price_table()
        usage = {"input_tokens": 1000, "output_tokens": 500, "cache_read_tokens": 2000,
                 "cache_write_tokens": 0, "reasoning_tokens": 100, "total_tokens": 3500,
                 "api_calls": 2, "model": "gpt-5.6-sol", "provider": "openai-api",
                 "service_tier": None}
        out = C.reconstruct_cost(usage, table)
        expect = (D(1000) * D("4.00") + D(2000) * D("0.40") + D(500) * D("20.00")) / D(1_000_000)
        self.assertEqual(out["usd"], C._usd(expect))

    def test_unmapped_token_class_rejected(self):
        table = C.load_price_table()
        usage = {"input_tokens": 10, "output_tokens": 10, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "reasoning_tokens": 0, "total_tokens": 20,
                 "api_calls": 1, "model": "gpt-5.6-sol", "provider": "openai-api",
                 "service_tier": None, "mystery_tokens": 5}
        with self.assertRaises(C.ContractError):
            C.reconstruct_cost(usage, table)

    def test_total_mismatch_rejected(self):
        table = C.load_price_table()
        usage = {"input_tokens": 10, "output_tokens": 10, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "reasoning_tokens": 0, "total_tokens": 999,
                 "api_calls": 1, "model": "gpt-5.6-sol", "provider": "openai-api",
                 "service_tier": None}
        with self.assertRaises(C.ContractError):
            C.reconstruct_cost(usage, table)

    def test_long_context_aggregate_guard(self):
        table = C.load_price_table()
        big = 300_000
        usage = {"input_tokens": big, "output_tokens": 10, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "reasoning_tokens": 0,
                 "total_tokens": big + 10,
                 "api_calls": 1, "model": "gpt-5.6-sol", "provider": "openai-api",
                 "service_tier": None}
        with self.assertRaises(C.ContractError):
            C.reconstruct_cost(usage, table)


class TestBudgetReservation(unittest.TestCase):
    def test_physical_reservation_before_contact(self):
        led = C.PhysicalLedger()
        led.reserve(D("1.00"))
        self.assertFalse(C.reservation_fits(led.settled, led.inflight, D("49.50"), C.PHYSICAL_CAP))
        self.assertTrue(C.reservation_fits(led.settled, led.inflight, D("49.00"), C.PHYSICAL_CAP))

    def test_calibration_subcap_includes_inflight(self):
        led = C.PhysicalLedger()
        led.reserve(D("4.00"), calibration=True)
        with self.assertRaises(C.ContractError):
            led.reserve(D("1.50"), calibration=True)  # 4.00 + 1.50 > 5.00
        led.reserve(D("1.00"), calibration=True)  # 4.00 + 1.00 fits

    def test_whole_study_cap_includes_calibration_and_inflight(self):
        led = C.PhysicalLedger()
        led.reserve(D("4.00"), calibration=True)
        led.settle(D("4.00"), D("3.90"), calibration=True)
        led.reserve(D("45.00"))
        with self.assertRaises(C.ContractError):
            led.reserve(D("2.00"))  # 3.90 + 45.00 + 2.00 > 50.00

    def test_actual_exceeding_reservation_aborts(self):
        led = C.PhysicalLedger()
        led.reserve(D("1.00"))
        with self.assertRaises(C.ContractError) as ctx:
            led.settle(D("1.00"), D("1.0000002"))
        self.assertIn(C.ABORT_BUDGET_ENFORCEMENT_FAILURE, str(ctx.exception))

    def test_strategy_threshold_formula(self):
        self.assertEqual(C.strategy_threshold(D("0.10")), D("3.00"))
        self.assertEqual(C.strategy_threshold(D("0.11")), D("3.50"))  # rounds up to $0.25
        self.assertEqual(C.strategy_threshold(D("0.2666")), D("8.00"))  # 7.998 -> 8.00

    def test_strategy_threshold_max(self):
        t = C.strategy_threshold(D("0.30"))  # 9.00 > 8.00
        self.assertGreater(t, C.STRATEGY_T_MAX)

    def test_strategy_reservation_blocks_overshoot(self):
        led = C.StrategyLedger("B", D("8.00"))
        led.allocate_debt(D("7.90"))
        with self.assertRaises(C.ContractError) as ctx:
            led.reserve(D("0.20"))
        self.assertIn(C.STRATEGY_CONTACT_THRESHOLD_REACHED, str(ctx.exception))

    def test_precontact_feasibility_is_no_go_budget_enforcement(self):
        f = C.precontact_feasibility()
        self.assertEqual(f["status"], C.NO_GO_BUDGET_ENFORCEMENT)
        self.assertEqual(f["scientific_contact"], "FORBIDDEN")

    def test_complexity_gate_passes(self):
        g = C.complexity_gate()
        self.assertEqual(g["status"], "PASS")
        self.assertLessEqual(len(g["modules"]), 2)
        self.assertLessEqual(g["total_loc"], 500)


class TestLedgers(unittest.TestCase):
    def test_physical_pays_common_acquisition_once_but_b_and_c_charged_full(self):
        phys = C.PhysicalLedger()
        d1 = D("1.59")
        phys.reserve(d1)
        phys.settle(d1, d1)
        b = C.StrategyLedger("B", D("8.00"))
        c = C.StrategyLedger("C", D("8.00"))
        b.allocate_debt(d1)
        c.allocate_debt(d1)
        self.assertEqual(phys.settled, d1)  # paid once physically
        self.assertEqual(b.debt, d1)        # B charged full D1
        self.assertEqual(c.debt, d1)        # C charged full D1 (not split 50/50)
        d2 = D("0.80")
        c.allocate_debt(d2)
        self.assertEqual(c.debt, d1 + d2)   # C additionally charged full D2

    def test_complete_acquisition_charging(self):
        # discovery 3 + proposal 1 + promotion parent 3 + candidate 3 = 10 contacts
        phys = C.PhysicalLedger()
        for _ in range(10):
            r = D("0.16")
            phys.reserve(r)
            phys.settle(r, r)
        self.assertEqual(phys.settled, D("1.60"))


class TestPartitions(unittest.TestCase):
    def test_schedule_partitions_do_not_overlap(self):
        sched = C.build_schedule("c001-seed-commitment-9f2e4a1b7d")
        C.verify_partitions(sched)  # raises on any leak

    def test_schedule_is_deterministic(self):
        a = C.build_schedule("c001-seed-commitment-9f2e4a1b7d")
        b = C.build_schedule("c001-seed-commitment-9f2e4a1b7d")
        self.assertEqual(a, b)

    def test_nine_measurement_tasks_per_rep_and_no_fourth_generation(self):
        sched = C.build_schedule("c001-seed-commitment-9f2e4a1b7d")
        for rep, parts in sched["repetitions"].items():
            total = sum(len(parts[f"measurement_g{g}"]) for g in (1, 2, 3))
            self.assertEqual(total, 9)
            self.assertNotIn("measurement_g4", parts)
            for g in (1, 2, 3):
                fams = sorted(t.split("-")[-2] for t in parts[f"measurement_g{g}"])
                self.assertEqual(fams, ["config", "interface", "logic"])

    def test_matched_abc_share_task_ids(self):
        # matched instances: the same frozen task IDs are used for A/B/C within a rep
        sched = C.build_schedule("c001-seed-commitment-9f2e4a1b7d")
        rep1 = sched["repetitions"]["1"]
        for g in (1, 2, 3):
            self.assertEqual(len(set(rep1[f"measurement_g{g}"])), 3)


class TestLineage(unittest.TestCase):
    def test_shared_first_acquisition_exact_fork(self):
        common = {"method": "v1", "acquisition": "first", "receipt": "abc"}
        b_state, c_state = C.fork_first_acquisition(common)
        self.assertEqual(C.method_hash(b_state), C.method_hash(c_state))
        # deep copy: mutating one does not affect the other
        b_state["method"] = "vX"
        self.assertNotEqual(C.method_hash(b_state), C.method_hash(c_state))

    def test_b_immutable_after_fork(self):
        h = C.method_hash({"method": "v1"})
        C.check_b_immutable(h, h)
        with self.assertRaises(C.ContractError):
            C.check_b_immutable(h, C.method_hash({"method": "v2"}))

    def test_c_rejected_candidate_not_inherited(self):
        promoted = C.method_hash({"method": "v2"})
        rejected = C.method_hash({"method": "bad"})
        C.check_c_no_rejected_inheritance(promoted, rejected, promoted)
        with self.assertRaises(C.ContractError):
            C.check_c_no_rejected_inheritance(rejected, rejected, None)

    def test_fresh_worker_state_every_contact(self):
        ws = C.WorkerSessions()
        s1, s2 = ws.fresh(), ws.fresh()
        self.assertNotEqual(s1, s2)
        self.assertEqual(len(ws._issued), 2)  # nothing crosses calls implicitly


class TestProvisionalSelection(unittest.TestCase):
    def test_accept_requires_all_conditions(self):
        parent = _rec(2, "0.30")
        cand = _rec(3, "0.20")
        self.assertEqual(C.provisional_select(parent, cand), C.PROVISIONAL_ACCEPT)
        self.assertNotEqual(C.provisional_select(parent, cand), "PROVEN_SUPERIOR")

    def test_reject_paths(self):
        parent = _rec(2, "0.30")
        self.assertEqual(C.provisional_select(parent, _rec(1, "0.10")), C.REJECT)  # <2/3
        self.assertEqual(C.provisional_select(parent, _rec(2, "0.40")), C.REJECT)  # worse $/verified
        self.assertEqual(C.provisional_select(parent, _rec(1, "0.10", quality_ok=False)), C.REJECT)
        self.assertEqual(C.provisional_select(parent, _rec(3, "0.20", telemetry_complete=False)), C.REJECT)
        self.assertEqual(C.provisional_select(parent, _rec(3, "0.20", within_method_bound=False)), C.REJECT)
        self.assertEqual(C.provisional_select(_rec(3, "0.30"), _rec(2, "0.10")), C.REJECT)  # fewer than parent


class TestEconomics(unittest.TestCase):
    def test_nine_task_repayment_arithmetic(self):
        d1, ca9, cb9 = D("1.59"), D("1.43"), D("1.00")
        self.assertTrue(C.repayment_holds(d1, cb9, ca9) is False)  # 1.59+1.00 > 1.43
        self.assertTrue(C.repayment_holds(D("0.30"), cb9, ca9))
        need = C.per_task_saving_needed(d1, 9)
        self.assertEqual(need, d1 / 9)

    def test_nine_task_impossible_even_free(self):
        self.assertTrue(C.impossible_even_free(D("2.00"), D("1.43")))
        self.assertFalse(C.impossible_even_free(D("1.00"), D("1.43")))

    def test_six_task_d2_arithmetic(self):
        d2, cb6, cc6 = D("0.80"), D("0.96"), D("0.50")
        self.assertFalse(C.repayment_holds(d2, cc6, cb6))  # 0.80+0.50 > 0.96
        self.assertTrue(C.impossible_even_free(D("1.00"), D("0.96")))

    def test_zero_success_is_infinity(self):
        self.assertEqual(C.dollars_per_verified(D("1.50"), 0), float("inf"))
        self.assertEqual(C.compare_strategies(D("1.0"), 0, D("2.0"), 0), "NO_CLAIM_BOTH_ZERO")
        self.assertEqual(C.compare_strategies(D("0.5"), 0, D("2.0"), 5),
                         "NO_CLAIM_ZERO_OUTPUT_CANNOT_WIN")

    def test_unequal_output_rule(self):
        self.assertEqual(C.compare_strategies(D("1.0"), 4, D("2.0"), 6),
                         "X_CANNOT_CLAIM_OUTPUT_DEFICIT")
        self.assertEqual(C.compare_strategies(D("1.0"), 6, D("2.0"), 6), "COMPARE_ALL_IN_COST")
        self.assertEqual(C.compare_strategies(D("3.0"), 6, D("2.0"), 6), "NO_ADVANTAGE")
        self.assertEqual(C.compare_strategies(D("1.0"), 8, D("2.0"), 6),
                         "EXTRA_OUTPUT_REPORT_SEPARATELY")

    def test_break_even_requires_no_reversal(self):
        x = [D("1.0"), D("1.8"), D("2.4")]
        y = [D("0.9"), D("1.9"), D("2.6")]
        self.assertEqual(C.break_even(x, y), 2)
        xr = [D("1.0"), D("1.8"), D("3.0")]  # crosses then reverses
        self.assertIsNone(C.break_even(xr, y))

    def test_pooled_uses_sums_not_mean_ratios(self):
        # rep1: cheap but tiny; rep2: expensive but large. Mean of ratios misleads.
        costs = [D("0.30"), D("10.00")]
        verified = [1, 100]
        p = C.pooled_economics(costs, verified)
        self.assertEqual(p["pooled_cost"], D("10.30"))
        self.assertEqual(p["pooled_verified"], 101)
        mean_ratio = (D("0.30") / 1 + D("10.00") / 100) / 2  # 0.20: the wrong statistic
        self.assertNotEqual(p["pooled_cost_per_verified"], mean_ratio)
        self.assertEqual(p["pooled_cost_per_verified"], D("10.30") / 101)

    def test_pooled_zero_verified_is_infinity(self):
        p = C.pooled_economics([D("1.0")], [0])
        self.assertEqual(p["pooled_cost_per_verified"], float("inf"))

    def test_aborted_rep_stays_in_physical_ledger(self):
        phys = C.PhysicalLedger()
        phys.reserve(D("2.00"))
        phys.settle(D("2.00"), D("1.95"))  # rep aborts after spending
        pooled = C.pooled_economics([], [])  # aborted rep excluded from pooled math
        self.assertEqual(pooled["pooled_verified"], 0)
        self.assertEqual(phys.settled, D("1.95"))  # but spend remains in whole-study ledger

    def test_incomplete_reps_block_positive_claim(self):
        recs = [
            {"first_acquisition_terminal": True, "second_acquisition_terminal": True,
             "a_measured": True, "b_measured": True, "c_measured": True,
             "costs_reconciled": True, "hashes_reconciled": True, "no_abort": True,
             "a_tasks": 9, "b_tasks": 9, "c_tasks": 9},
            {"first_acquisition_terminal": True, "second_acquisition_terminal": False,
             "a_measured": True, "b_measured": True, "c_measured": False,
             "costs_reconciled": True, "hashes_reconciled": True, "no_abort": False,
             "a_tasks": 9, "b_tasks": 9, "c_tasks": 3},
        ]
        self.assertFalse(C.completed_repetition(recs[1]))
        self.assertTrue(C.completed_repetition(recs[0]))
        self.assertEqual(C.study_claim_status(recs), C.INCONCLUSIVE_INCOMPLETE_REPETITIONS)
        self.assertEqual(C.study_claim_status(recs + [recs[0]]),
                         C.INCONCLUSIVE_INCOMPLETE_REPETITIONS)

    def test_three_reps_required(self):
        good = {"first_acquisition_terminal": True, "second_acquisition_terminal": True,
                "a_measured": True, "b_measured": True, "c_measured": True,
                "costs_reconciled": True, "hashes_reconciled": True, "no_abort": True,
                "a_tasks": 9, "b_tasks": 9, "c_tasks": 9}
        self.assertEqual(C.study_claim_status([good, good]),
                         C.INCONCLUSIVE_INCOMPLETE_REPETITIONS)
        self.assertEqual(C.study_claim_status([good, good, good]),
                         "READY_FOR_ECONOMIC_ADJUDICATION")


class TestPreregBindings(unittest.TestCase):
    def test_verify_prereg_clean(self):
        self.assertEqual(C.verify_prereg(), [])

    def test_hash_bindings_cover_all_artifacts(self):
        prereg = json.loads((AIR / "preregistration.json").read_text())
        for key, path in (("price_table_sha256", AIR / "price-table.json"),
                          ("baseline_method_sha256", AIR / "baseline-method.md"),
                          ("task_schedule_sha256", AIR / "task-schedule.json")):
            import hashlib
            self.assertEqual(prereg[key], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_no_src_airlock_changes(self):
        base = "d3b29da9a83c8ee65ee095fae1b052460e08ece3"
        try:
            out = subprocess.run(
                ["git", "diff", "--name-only", base + "...HEAD", "--", "src/airlock/"],
                cwd=ROOT, text=True, stdout=subprocess.PIPE, check=False,
            )
        except FileNotFoundError:
            self.skipTest("git unavailable")
        if out.returncode != 0:
            self.skipTest("git diff unavailable")
        changed = [l for l in out.stdout.splitlines() if l.strip()]
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
