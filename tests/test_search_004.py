from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments/airlock-search-004/run_search_004.py"
SPEC = importlib.util.spec_from_file_location("search004_test_runner", RUNNER)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Search004Tests(unittest.TestCase):
    def setUp(self):
        self.table = M.load_price_table()

    def _usage(self, **updates):
        row = {
            "estimated_cost_usd": 999.0,
            "cost_status": "estimated",
            "cost_source": "ignored",
            "input_tokens": 1000,
            "output_tokens": 100,
            "cache_read_tokens": 100,
            "cache_write_tokens": 20,
            "reasoning_tokens": 50,
            "total_tokens": 1220,
            "api_calls": 2,
            "model": "gpt-5.6-sol",
            "provider": "openai-api",
            "service_tier": None,
            "completed": True,
            "failed": False,
        }
        row.update(updates)
        return row

    def _meter(self, row, require_output=False):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "usage.json"
            path.write_text(json.dumps(row))
            return M.meter_usage(path, self.table, require_output=require_output)

    def test_metered_cost_uses_frozen_token_classes_not_hermes_estimate(self):
        result = self._meter(self._usage())
        self.assertEqual(result["metered_cost_usd"], "0.00614")
        self.assertEqual(result["provider_estimated_cost_usd_untrusted"], 999.0)

    def test_reasoning_tokens_are_not_double_charged(self):
        low = self._meter(self._usage(reasoning_tokens=0))
        high = self._meter(self._usage(reasoning_tokens=100))
        self.assertEqual(low["metered_cost_usd"], high["metered_cost_usd"])

    def test_unknown_nonzero_token_class_fails_closed(self):
        with self.assertRaisesRegex(M.TelemetryError, "UNMAPPED_TOKEN_CLASS"):
            self._meter(self._usage(magic_tokens=1))

    def test_zero_or_inconsistent_usage_fails_closed(self):
        with self.assertRaises(M.TelemetryError):
            self._meter(self._usage(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0, total_tokens=0))
        with self.assertRaisesRegex(M.TelemetryError, "TOKEN_TOTAL_MISMATCH"):
            self._meter(self._usage(total_tokens=999))

    def test_preflight_requires_positive_input_and_output(self):
        with self.assertRaisesRegex(M.TelemetryError, "PREFLIGHT_INPUT_OR_OUTPUT_ZERO"):
            self._meter(self._usage(output_tokens=0, reasoning_tokens=0, total_tokens=1120), require_output=True)

    def test_worker_usage_receipt_is_loaded_from_airlock_owned_raw_report(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            report_path = repo / ".airlock/runs/run-1/agent-reports/candidate-01.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps({
                "provider": "hermes",
                "authority_audit": {
                    "schema": "airlock.search-004.worker-boundary.v1",
                    "forbidden_environment_names_present": [],
                    "github_credential_present": False,
                    "release_authority": "ABSENT",
                    "usage_path_outside_candidate_repo": True,
                    "usage_path_outside_hermes_home": True,
                },
                "usage_receipt": {"sha256": "a" * 64},
            }))
            path, audit, usage = M._worker_evidence(
                repo,
                {"run_id": "run-1"},
                {"candidate_id": "candidate-01", "agent_report": {"provider": "hermes"}},
            )
        self.assertEqual(path, report_path)
        self.assertEqual(audit["release_authority"], "ABSENT")
        self.assertEqual(usage["sha256"], "a" * 64)

    def test_worker_authority_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            report_path = repo / ".airlock/runs/run-1/agent-reports/candidate-01.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(json.dumps({
                "authority_audit": {
                    "schema": "airlock.search-004.worker-boundary.v1",
                    "forbidden_environment_names_present": ["GITHUB_TOKEN"],
                    "github_credential_present": True,
                    "release_authority": "ABSENT",
                    "usage_path_outside_candidate_repo": True,
                    "usage_path_outside_hermes_home": True,
                },
                "usage_receipt": {"sha256": "a" * 64},
            }))
            with self.assertRaisesRegex(M.TelemetryError, "WORKER_AUTHORITY_AUDIT_FAILED"):
                M._worker_evidence(repo, {"run_id": "run-1"}, {"candidate_id": "candidate-01"})

    def test_long_context_ambiguity_fails_closed(self):
        with self.assertRaisesRegex(M.TelemetryError, "LONG_CONTEXT_TIER_AMBIGUOUS"):
            self._meter(self._usage(input_tokens=272001, output_tokens=1, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0, total_tokens=272002))

    def test_verdict_boundaries_are_numeric_and_frozen(self):
        self.assertEqual(M.verdict_for(Decimal("1.15"), Decimal("1"), 0, 4), "UNATTENDED_YIELD_GAIN")
        self.assertEqual(M.verdict_for(Decimal("1.149999"), Decimal("1"), 0, 4), "UNATTENDED_YIELD_PARITY")
        self.assertEqual(M.verdict_for(Decimal("0.85"), Decimal("1"), 0, 4), "UNATTENDED_YIELD_PARITY")
        self.assertEqual(M.verdict_for(Decimal("0.849999"), Decimal("1"), 0, 4), "GUIDANCE_YIELD_ADVANTAGE")

    def test_zero_guided_yield_edge_and_null_yield(self):
        self.assertEqual(M.verdict_for(Decimal("1"), Decimal("0"), 0, 1), "UNATTENDED_YIELD_GAIN")
        self.assertEqual(M.verdict_for(Decimal("0"), Decimal("0"), 0, 0), "NULL_YIELD")

    def test_opportunity_pool_and_guided_schedule_are_arm_local_and_complete(self):
        prereg = json.loads((ROOT / ".airlock/search-004/preregistration.json").read_text())
        tasks = json.loads((ROOT / ".airlock/search-004/guided-tasks.json").read_text())["tasks"]
        score = json.loads((ROOT / ".airlock/search-002/scorecard.json").read_text())["dimensions"]
        self.assertEqual(prereg["opportunity_pool"]["scope"], "INTRA_ARM_ONLY")
        self.assertFalse(prereg["opportunity_pool"]["cross_arm_depletion"])
        self.assertEqual(len(tasks), 9)
        self.assertEqual({t["dimension"] for t in tasks}, {d["id"] for d in score})
        self.assertEqual(prereg["arms"]["A"]["maintainer_task_assignments_expected"], 0)

    def test_frozen_file_hashes_still_match(self):
        prereg = json.loads((ROOT / ".airlock/search-004/preregistration.json").read_text())
        for rel, expected in prereg["frozen_files"].items():
            self.assertEqual(M.sha256_file(ROOT / rel), expected, rel)


if __name__ == "__main__":
    unittest.main()
