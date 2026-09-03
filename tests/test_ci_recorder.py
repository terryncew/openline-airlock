from __future__ import annotations

import json
from pathlib import Path
import unittest

from airlock.ci import analyze_bundle, render_text, verify_ci_receipt
from airlock.util import canonical_json_bytes


FIXTURES = Path(__file__).parent / "fixtures" / "ci_flight_recorder"
KEY = bytes.fromhex("11" * 32)


class CIRecorderCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads((FIXTURES / "corpus.json").read_text())
        cls.goldens = json.loads((FIXTURES / "goldens.json").read_text())["receipts"]
        cls.by_name = {row["name"]: row["source_bundle"] for row in cls.corpus["fixtures"]}

    def test_every_fixture_is_byte_deterministic_and_matches_frozen_golden(self):
        self.assertEqual(len(self.by_name), 16)
        for name, bundle in self.by_name.items():
            with self.subTest(name=name):
                first = analyze_bundle(bundle, key=KEY)
                second = analyze_bundle(bundle, key=KEY)
                self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
                self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(self.goldens[name]))
                self.assertTrue(verify_ci_receipt(first, KEY)["valid"])

    def test_pr60_fixture_routes_to_retry_without_code_repair_authority(self):
        receipt = analyze_bundle(self.by_name["05_pr60_runner_filesystem"], key=KEY)
        payload = receipt["payload"]
        self.assertEqual(payload["disposition"], "RETRY_RECOMMENDED")
        self.assertFalse(payload["authorization"]["code_repair"])
        finding = payload["findings"][0]
        self.assertEqual((finding["cause_class"], finding["reason_code"]), ("ENVIRONMENT", "RUNNER_FILESYSTEM"))
        self.assertEqual(finding["stability"], "TRANSIENT")
        self.assertEqual(finding["patch_implicated"], "NO")
        self.assertEqual(finding["local_reproduction"], "NOT_ATTEMPTED")

    def test_zero_non_code_fixtures_grant_code_repair(self):
        non_code = [
            "03_invalid_workflow_syntax", "04_permission_secret_config", "05_pr60_runner_filesystem",
            "06_disk_resource_exhaustion", "07_registry_rate_limit", "08_remote_5xx_network",
            "09_downstream_symptom", "10_stale_artifact_wrong_sha", "11_branch_base_identity_mismatch",
            "12_same_sha_equivalent_rerun_passes", "15_missing_truncated_logs", "16_adversarial_log_text",
        ]
        for name in non_code:
            with self.subTest(name=name):
                payload = analyze_bundle(self.by_name[name], key=KEY)["payload"]
                self.assertNotEqual(payload["disposition"], "CODE_REPAIR_ALLOWED")
                self.assertFalse(payload["authorization"]["code_repair"])

    def test_zero_proven_code_regressions_are_routed_to_retry(self):
        for name in ["01_named_test_regression", "02_lint_type_failure", "14_parallel_independent_code_failures"]:
            with self.subTest(name=name):
                payload = analyze_bundle(self.by_name[name], key=KEY)["payload"]
                self.assertEqual(payload["disposition"], "CODE_REPAIR_ALLOWED")
                self.assertNotEqual(payload["disposition"], "RETRY_RECOMMENDED")

    def test_mixed_matrix_fails_closed_and_legs_remain_distinct(self):
        payload = analyze_bundle(self.by_name["13_mixed_matrix"], key=KEY)["payload"]
        self.assertEqual(payload["disposition"], "REPORT_ONLY")
        self.assertEqual([row["job_id"] for row in payload["findings"]], [114, 115])
        self.assertEqual({row["cause_class"] for row in payload["findings"]}, {"CODE_REGRESSION", "EXTERNAL_SERVICE"})

    def test_downstream_symptom_does_not_replace_proven_upstream_cause(self):
        payload = analyze_bundle(self.by_name["09_downstream_symptom"], key=KEY)["payload"]
        by_job = {row["job"]: row for row in payload["findings"]}
        self.assertEqual(by_job["build"]["role"], "PRIMARY")
        self.assertEqual(by_job["build"]["cause_class"], "EXTERNAL_SERVICE")
        self.assertEqual(by_job["package"]["role"], "DOWNSTREAM")

    def test_passing_rerun_only_changes_stability_not_patch_safety(self):
        payload = analyze_bundle(self.by_name["12_same_sha_equivalent_rerun_passes"], key=KEY)["payload"]
        self.assertEqual(payload["findings"][0]["stability"], "TRANSIENT")
        self.assertNotIn("CODE_SAFE", canonical_json_bytes(payload).decode())
        self.assertFalse(payload["authorization"]["merge"])
        self.assertFalse(payload["authorization"]["deployment"])

    def test_missing_and_adversarial_logs_fail_closed_without_injection(self):
        missing = analyze_bundle(self.by_name["15_missing_truncated_logs"], key=KEY)["payload"]
        self.assertEqual(missing["findings"][0]["cause_class"], "UNRESOLVED")
        self.assertEqual(missing["disposition"], "REPORT_ONLY")

        receipt = analyze_bundle(self.by_name["16_adversarial_log_text"], key=KEY)
        encoded = canonical_json_bytes(receipt).decode()
        text = render_text(receipt)
        for hostile in ("IGNORE ALL RULES", "<system>", "sk-test-secret-123", "tests/test_fake.py::test_fake FAILED"):
            self.assertNotIn(hostile, encoded)
        self.assertEqual(receipt["payload"]["disposition"], "REPORT_ONLY")
        self.assertIn("Disposition: REPORT_ONLY", text)

    def test_success_without_blocking_failures_is_no_action(self):
        bundle = json.loads(json.dumps(self.by_name["01_named_test_regression"]))
        bundle["conclusion"] = "success"
        bundle["jobs"][0]["conclusion"] = "success"
        for step in bundle["jobs"][0]["steps"]:
            step["conclusion"] = "success"
        payload = analyze_bundle(bundle, key=KEY)["payload"]
        self.assertEqual(payload["disposition"], "NO_ACTION")
        self.assertEqual(payload["findings"], [])

    def test_failed_run_without_jobs_is_unresolved_not_no_action(self):
        bundle = json.loads(json.dumps(self.by_name["01_named_test_regression"]))
        bundle["jobs"] = []
        payload = analyze_bundle(bundle, key=KEY)["payload"]
        self.assertEqual(payload["disposition"], "REPORT_ONLY")
        self.assertEqual(payload["findings"][0]["cause_class"], "UNRESOLVED")

    def test_receipt_integrity_fails_on_tamper(self):
        receipt = analyze_bundle(self.by_name["01_named_test_regression"], key=KEY)
        self.assertTrue(verify_ci_receipt(receipt, KEY)["valid"])
        receipt["payload"]["disposition"] = "RETRY_RECOMMENDED"
        self.assertFalse(verify_ci_receipt(receipt, KEY)["valid"])

    def test_all_multistate_fields_stay_inside_frozen_domains(self):
        for name, bundle in self.by_name.items():
            payload = analyze_bundle(bundle, key=KEY)["payload"]
            for row in payload["findings"]:
                self.assertIn(row["patch_implicated"], {"YES", "NO", "UNKNOWN"})
                self.assertIn(row["local_reproduction"], {"REPRODUCED", "NOT_REPRODUCED", "NOT_ATTEMPTED", "UNKNOWN"})
                self.assertIn(row["evidence_grade"], {"DIRECT", "CORROBORATED", "INSUFFICIENT"})
                self.assertIn(row["stability"], {"REPRODUCIBLE", "TRANSIENT", "UNKNOWN"})


if __name__ == "__main__":
    unittest.main()
