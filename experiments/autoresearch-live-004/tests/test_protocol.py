import unittest

import protocol


class ProtocolTests(unittest.TestCase):
    def inherited(self):
        state = protocol.ProtocolState()
        protocol.record_inheritance(state, "a")
        return state

    def test_search_cannot_start_before_inheritance(self):
        state = protocol.ProtocolState()
        with self.assertRaises(RuntimeError):
            protocol.begin_researcher_call(state)

    def test_reject_then_confirmed_b_promotes(self):
        state = self.inherited()
        protocol.begin_researcher_call(state)
        self.assertEqual(protocol.record_discovery(state, "b1", "REJECT"), "CONTINUE")
        protocol.begin_researcher_call(state)
        self.assertEqual(protocol.record_discovery(state, "b2", "ACCEPT"), "CONFIRM")
        self.assertEqual(protocol.record_confirmation(state, "b2", "ACCEPT"), "PROMOTE")
        protocol.record_promotion(state, "b2")
        self.assertEqual(state.terminal_verdict, "CUMULATIVE_GOVERNED_OPTIMIZATION_PROMOTED")

    def test_failed_confirmation_is_terminal(self):
        state = self.inherited()
        protocol.begin_researcher_call(state)
        self.assertEqual(protocol.record_discovery(state, "b1", "ACCEPT"), "CONFIRM")
        self.assertEqual(protocol.record_confirmation(state, "b1", "REJECT"), "STOP")
        self.assertEqual(state.terminal_verdict, "APPARENT_B_NOT_CONFIRMED")
        with self.assertRaises(RuntimeError):
            protocol.begin_researcher_call(state)

    def test_confirmation_must_bind_exact_b(self):
        state = self.inherited()
        protocol.begin_researcher_call(state)
        protocol.record_discovery(state, "b1", "ACCEPT")
        with self.assertRaises(RuntimeError):
            protocol.record_confirmation(state, "different", "ACCEPT")

    def test_b_cannot_equal_inherited_a(self):
        state = self.inherited()
        protocol.begin_researcher_call(state)
        with self.assertRaises(RuntimeError):
            protocol.record_discovery(state, "a", "REJECT")

    def test_twelve_rejections_end_search(self):
        state = self.inherited()
        action = None
        for i in range(12):
            protocol.begin_researcher_call(state)
            action = protocol.record_discovery(state, f"b{i}", "REJECT")
        self.assertEqual(action, "STOP")
        self.assertEqual(state.terminal_verdict, "INHERITED_A_NO_CONFIRMED_B")
        self.assertEqual(state.discovery_evaluations, 12)

    def test_abandoned_calls_count(self):
        state = self.inherited()
        for i in range(12):
            protocol.begin_researcher_call(state)
            action = protocol.abandon_researcher_call(state, f"failure-{i}")
        self.assertEqual(action, "STOP")
        self.assertEqual(state.researcher_calls, 12)
        self.assertEqual(state.terminal_verdict, "INHERITED_A_SEARCH_BUDGET_EXHAUSTED")


if __name__ == "__main__":
    unittest.main()
