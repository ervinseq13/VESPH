"""Unit tests for VESPH Care agents and natural language routing."""

import unittest
from orchestrator.graph import build_orchestrator, run
from orchestrator.state import OrchestratorState


class TestAgentWorkflows(unittest.TestCase):
    def setUp(self):
        self.orchestrator = build_orchestrator()
        self.sample_care_data = {
            "patient": {
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "Ananya Iyer",
                "first_name": "Ananya",
                "health_summary": "Recovering well from laparoscopic appendectomy.",
                "diagnostic_summary": "CBC normal range.",
                "medication_summary": "Pantocid 40 active.",
                "appointment_summary": "Follow-up on 22 Oct 2026.",
            },
            "appointments": [
                {
                    "id": "33333333-3333-3333-3333-333333333331",
                    "date": "22 Oct 2026",
                    "time": "11:30 AM",
                    "doctor": "Dr. Rhea Mehta",
                    "type": "FollowUp",
                    "status": "Confirmed",
                    "location": "OPD Wing B, Room 304",
                    "preparation": "Bring previous lab reports.",
                }
            ],
            "medications": [
                {
                    "name": "Pantocid 40",
                    "dosage": "40 mg",
                    "meal_timing": "breakfast",
                    "instruction": "Take 1 tablet every morning on empty stomach 30 mins before breakfast.",
                    "is_taken": True,
                    "next_dose": "Daily schedule",
                },
                {
                    "name": "Dolo 650",
                    "dosage": "650 mg",
                    "meal_timing": "lunch",
                    "instruction": "Take 1 tablet after lunch SOS if pain occurs.",
                    "is_taken": False,
                    "next_dose": "As needed (SOS)",
                },
            ],
            "diagnostics": [
                {
                    "name": "Complete Blood Count (CBC)",
                    "category": "Blood Work",
                    "date": "16 Oct 2026",
                    "status": "Reviewed",
                    "summary": "WBC count 10.4 x10^3/uL, within normal recovery range.",
                }
            ],
            "diagnostic_schedule": [
                {
                    "test": "Complete Blood Count (CBC)",
                    "date": "20 Oct 2026",
                    "time": "09:00 AM",
                    "location": "Pathology Lab · 1st Floor",
                    "preparation": "No fasting required",
                }
            ],
            "discharge": {
                "procedure": "Laparoscopic appendectomy",
                "discharge_date": "10 Oct 2026",
                "instructions": ["Keep incision sites clean and dry."],
            },
            "escalations": [],
        }

    def test_reminder_agent_diagnostic_pre_visit(self):
        query = "My doctor told me to get a blood test before the next visit"
        res = run(self.orchestrator, query, self.sample_care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Reminder Agent", res.agent)
        self.assertIn("Diagnostic Tests", res.agent)
        self.assertIn("Complete Blood Count", res.message)

    def test_reminder_agent_medication_timing(self):
        query = "Did I take my morning pills?"
        res = run(self.orchestrator, query, self.sample_care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Reminder Agent", res.agent)
        self.assertIn("Medication Timing", res.agent)
        self.assertIn("Pantocid 40", res.message)

    def test_reminder_agent_hospital_visit(self):
        query = "When do I have to go to the hospital?"
        res = run(self.orchestrator, query, self.sample_care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Reminder Agent", res.agent)
        self.assertIn("Appointment Attendance", res.agent)
        self.assertIn("Dr. Rhea Mehta", res.message)
        self.assertIn("22 Oct 2026", res.message)

    def test_summary_agent_lab_results(self):
        query = "What did the test show?"
        res = run(self.orchestrator, query, self.sample_care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Summary Agent", res.agent)
        self.assertIn("Complete Blood Count", res.message)

    def test_escalation_agent_emergency(self):
        query = "I am having severe chest pain"
        res = run(self.orchestrator, query, self.sample_care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Escalation Agent", res.agent)
        self.assertTrue(res.escalated)
        self.assertIn("+91 22 4000 1122", res.message)

    def test_escalation_agent_wrong_report(self):
        query = "This report belongs to someone else, not my report"
        res = run(self.orchestrator, query, self.sample_care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Escalation Agent", res.agent)
        self.assertTrue(res.escalated)
        self.assertIsNotNone(res.escalation)


if __name__ == "__main__":
    unittest.main()
