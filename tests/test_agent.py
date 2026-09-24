import unittest

from agent import respond
from data_store import load_demo_data


class AgentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load_demo_data()

    def test_appointment_question_is_grounded_in_record(self) -> None:
        reply = respond("When is my next appointment?", self.data)
        self.assertIn("22 Sep 2026", reply.message)
        self.assertIn("Dr. Rhea Mehta", reply.message)
        self.assertIn("Reminder Agent", reply.agent)

    def test_emergency_language_escalates(self) -> None:
        reply = respond("I have severe pain, is this an emergency?", self.data)
        self.assertTrue(reply.escalated)
        self.assertIn("emergency", reply.agent.lower())
        self.assertIn("call", reply.message.lower())

    def test_wrong_report_does_not_expose_report_contents(self) -> None:
        reply = respond("This is someone else's report", self.data)
        self.assertTrue(reply.escalated)
        self.assertIn("do not use or share", reply.message.lower())

    def test_unknown_question_falls_back_to_supported_scope(self) -> None:
        reply = respond("What can you do?", self.data)
        self.assertIn("appointments", reply.message.lower())
        self.assertIn("Router", reply.agent)


if __name__ == "__main__":
    unittest.main()

