import unittest

from data_store import load_demo_data
from orchestrator.graph import build_orchestrator, resolve, run


class OrchestratorEscalationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load_demo_data()
        self.patient_id = self.data["patient"]["id"]
        self.graph = build_orchestrator()
        self.thread_id = f"test-{self._testMethodName}"

    def test_wrong_report_asks_for_resolution_confirmation(self) -> None:
        reply = run(
            self.graph,
            "This report belongs to someone else",
            self.data,
            self.patient_id,
            thread_id=self.thread_id,
        )

        self.assertTrue(reply.escalated)
        self.assertEqual(reply.escalation["status"], "pending_confirmation")
        self.assertIn("confirm", reply.escalation["prompt"].lower())
        self.assertEqual(len(reply.escalation["options"]), 3)
        self.assertEqual(len(self.data["escalations"]), 1)

    def test_patient_resolution_is_recorded_and_acknowledged(self) -> None:
        opened = run(
            self.graph,
            "The doctor is unavailable for my appointment",
            self.data,
            self.patient_id,
            thread_id=self.thread_id,
        )
        choice = opened.escalation["options"][0]

        closed = resolve(
            self.graph,
            opened.escalation["id"],
            choice,
            self.data,
            self.patient_id,
            thread_id=self.thread_id,
        )

        self.assertFalse(closed.escalated)
        self.assertEqual(closed.escalation["status"], "confirmed")
        self.assertEqual(closed.escalation["resolution"], choice)
        self.assertIn("Confirmed", closed.message)
        self.assertEqual(self.data["escalations"][0]["resolution"], choice)
        checkpoint = self.graph.get_state(
            {"configurable": {"thread_id": self.thread_id}}
        )
        self.assertEqual(
            [message["role"] for message in checkpoint.values["messages"]],
            ["user", "assistant", "user", "assistant"],
        )

    def test_emergency_reply_does_not_wait_for_confirmation(self) -> None:
        reply = run(
            self.graph,
            "I have chest pain and cannot breathe",
            self.data,
            self.patient_id,
            thread_id=self.thread_id,
        )

        self.assertTrue(reply.escalated)
        self.assertIn("Do not wait for chat", reply.message)
        self.assertIn("calling emergency services", reply.escalation["options"][0])


if __name__ == "__main__":
    unittest.main()
