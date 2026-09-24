import unittest

from data_store import load_demo_data
from orchestrator.graph import build_orchestrator, run


class AgentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load_demo_data()
        self.patient_id = self.data["patient"]["id"]
        self.graph = build_orchestrator()

    def respond(self, query: str):
        return run(
            self.graph,
            query,
            self.data,
            self.patient_id,
            thread_id=f"router-{self._testMethodName}",
        )

    def test_appointment_question_is_grounded_in_record(self) -> None:
        reply = self.respond("When is my next appointment?")
        self.assertIn("22 Sep 2026", reply.message)
        self.assertIn("Dr. Rhea Mehta", reply.message)
        self.assertIn("Reminder Agent", reply.agent)

    def test_emergency_language_escalates(self) -> None:
        reply = self.respond("I have severe pain, is this an emergency?")
        self.assertTrue(reply.escalated)
        self.assertIn("emergency", reply.agent.lower())
        self.assertIn("call", reply.message.lower())

    def test_wrong_report_does_not_expose_report_contents(self) -> None:
        reply = self.respond("This is someone else's report")
        self.assertTrue(reply.escalated)
        self.assertIn("do not use or share", reply.message.lower())

    def test_unknown_question_falls_back_to_supported_scope(self) -> None:
        reply = self.respond("What can you do?")
        self.assertIn("appointments", reply.message.lower())
        self.assertIn("Router", reply.agent)


if __name__ == "__main__":
    unittest.main()

