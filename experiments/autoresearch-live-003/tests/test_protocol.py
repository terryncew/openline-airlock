import unittest

from experiments.autoresearch_live_003_import_shim import load_protocol

p = load_protocol()


class ProtocolTests(unittest.TestCase):
    def test_discovery_accept_never_promotes(self):
        s = p.ProtocolState()
        p.begin_researcher_call(s)
        action = p.record_discovery(s, "candidate-a", "ACCEPT")
        self.assertEqual(action, "CONFIRM")
        self.assertEqual(s.phase, "CONFIRMING")
        self.assertIsNone(s.terminal_verdict)

    def test_confirmation_accept_authorizes_then_exact_promotion(self):
        s = p.ProtocolState()
        p.begin_researcher_call(s)
        p.record_discovery(s, "candidate-a", "ACCEPT")
        action = p.record_confirmation(s, "candidate-a", "ACCEPT")
        self.assertEqual(action, "PROMOTE")
        self.assertEqual(s.phase, "PROMOTION_AUTHORIZED")
        p.record_promotion(s, "candidate-a")
        self.assertEqual(s.terminal_verdict, "CONFIRMED_LIVE_IMPROVEMENT_PROMOTED")

    def test_confirmation_reject_stops_search(self):
        s = p.ProtocolState()
        p.begin_researcher_call(s)
        p.record_discovery(s, "candidate-a", "ACCEPT")
        action = p.record_confirmation(s, "candidate-a", "REJECT")
        self.assertEqual(action, "STOP")
        self.assertEqual(s.terminal_verdict, "APPARENT_WIN_NOT_CONFIRMED")
        with self.assertRaises(RuntimeError):
            p.begin_researcher_call(s)

    def test_confirmation_must_bind_same_candidate(self):
        s = p.ProtocolState()
        p.begin_researcher_call(s)
        p.record_discovery(s, "candidate-a", "ACCEPT")
        with self.assertRaises(RuntimeError):
            p.record_confirmation(s, "candidate-b", "ACCEPT")

    def test_twelve_rejections_stop_without_confirmation(self):
        s = p.ProtocolState()
        for i in range(12):
            p.begin_researcher_call(s)
            action = p.record_discovery(s, f"c{i}", "REJECT")
        self.assertEqual(action, "STOP")
        self.assertEqual(s.researcher_calls, 12)
        self.assertEqual(s.discovery_evaluations, 12)
        self.assertEqual(s.confirmation_evaluations, 0)
        self.assertEqual(s.terminal_verdict, "GOVERNANCE_PASS_NO_CONFIRMED_IMPROVEMENT")

    def test_abandoned_calls_count_against_worker_budget(self):
        s = p.ProtocolState()
        for i in range(12):
            p.begin_researcher_call(s)
            action = p.abandon_researcher_call(s, f"transport-{i}")
        self.assertEqual(action, "STOP")
        self.assertEqual(s.researcher_calls, 12)
        self.assertEqual(s.discovery_evaluations, 0)
        self.assertEqual(s.terminal_verdict, "WORKER_BUDGET_EXHAUSTED_NO_CONFIRMED_IMPROVEMENT")

    def test_no_second_confirmation(self):
        s = p.ProtocolState()
        p.begin_researcher_call(s)
        p.record_discovery(s, "candidate-a", "ACCEPT")
        p.record_confirmation(s, "candidate-a", "ACCEPT")
        with self.assertRaises(RuntimeError):
            p.record_confirmation(s, "candidate-a", "ACCEPT")


if __name__ == "__main__":
    unittest.main()
