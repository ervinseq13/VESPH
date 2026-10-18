"""Unit tests verifying Patient Multi-Agent enhancements: doctor summaries, health trends, adherence, fasting, and reschedule convergence."""

import unittest
from orchestrator.memory import build_memory
from orchestrator.graph import build_orchestrator, run


class TestPatientOrchestrator(unittest.TestCase):

    def setUp(self):
        self.orchestrator = build_orchestrator(build_memory())
        self.care_data = {
            "patient": {
                "id": "22222222-2222-2222-2222-222222222222",
                "first_name": "Ananya",
                "doctor": "Dr. Rhea Mehta",
                "health_summary": "Recovering well after laparoscopic appendectomy.",
            },
            "appointments": [
                {
                    "id": "33333333-3333-3333-3333-333333331001",
                    "type": "Follow-up",
                    "doctor": "Dr. Rhea Mehta",
                    "date": "26 Oct 2026",
                    "time": "10:00 AM",
                    "location": "OPD Wing B, Room 304",
                    "status": "Reschedule Pending",
                    "preparation": "Bring previous discharge summary and CBC report",
                }
            ],
            "medications": [
                {"name": "Pantocid 40", "dosage": "40mg", "instruction": "Take before breakfast", "meal_timing": "breakfast", "is_taken": True},
                {"name": "Dolo 650", "dosage": "650mg", "instruction": "Take after lunch if needed", "meal_timing": "lunch", "is_taken": False},
                {"name": "Shelcal 500", "dosage": "500mg", "instruction": "Take after dinner", "meal_timing": "dinner", "is_taken": False},
            ],
            "diagnostics": [
                {"name": "Complete Blood Count (CBC)", "date": "16 Oct 2026", "summary": "WBC is 10.4 x10^3/uL, within normal range."}
            ],
            "diagnostic_schedule": [
                {"test": "Fasting Lipid Profile", "date": "20 Oct 2026", "time": "08:30 AM", "location": "Pathology Lab", "preparation": "10-12 hours overnight fasting required"}
            ],
            "discharge": {
                "discharge_date": "10 Oct 2026",
                "procedure": "Laparoscopic appendectomy",
                "condition_at_discharge": "Clean incisions, stable ambulation",
                "follow_up": "Surgical review in 2 weeks",
            },
        }

    def test_summary_agent_doctor_inquiry(self):
        """Verify patient can ask about their doctor and get credentials/department."""
        res = run(self.orchestrator, "Tell me about Dr. Rhea Mehta", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("MBBS, MS", res.message)
        self.assertIn("General Surgery", res.message)
        self.assertIn("Room 304", res.message)

    def test_summary_agent_health_trends(self):
        """Verify patient can check health and biomarker trends."""
        res = run(self.orchestrator, "What is my recovery trend?", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Clinical Recovery Trend", res.message)
        self.assertIn("CBC", res.message)

    def test_summary_agent_medication_adherence(self):
        """Verify patient can ask about adherence (prescribed vs taken)."""
        res = run(self.orchestrator, "What is my medication adherence?", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("1 of 3", res.message)
        self.assertIn("33% adherence", res.message)

    def test_reminder_agent_reschedule_alert(self):
        """Verify reminder agent alerts about rescheduled appointment and asks to confirm or rebook."""
        res = run(self.orchestrator, "When is my upcoming appointment?", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Appointment Rescheduled", res.message)
        self.assertIn("26 Oct 2026", res.message)
        self.assertIn("confirm", res.message.lower())


if __name__ == "__main__":
    unittest.main()
