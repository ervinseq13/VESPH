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
                    "status": "Rescheduled",
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

    def test_reminder_agent_medication_intake_confirmed(self):
        """Verify reminder agent acknowledges taking medication and updates is_taken."""
        dolo_med = next(m for m in self.care_data["medications"] if "Dolo" in m["name"])
        self.assertFalse(dolo_med["is_taken"])
        res = run(self.orchestrator, "I took dolo", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("recorded that you took", res.message)
        self.assertTrue(dolo_med["is_taken"])

    def test_appointment_status_enum_normalization(self):
        """Verify all variants map strictly to PostgreSQL appointment_status_enum allowed values."""
        from tools.db_tools import normalize_appointment_status, VALID_APPOINTMENT_STATUSES

        self.assertEqual(normalize_appointment_status("Reschedule Pending"), "Pending")
        self.assertEqual(normalize_appointment_status("rescheduled"), "Rescheduled")
        self.assertEqual(normalize_appointment_status("Doctor Unavailable (Reschedule Required)"), "Cancelled")
        self.assertEqual(normalize_appointment_status("Pending Confirmation"), "Pending")
        self.assertEqual(normalize_appointment_status("confirmed"), "Confirmed")
        self.assertEqual(normalize_appointment_status("canceled"), "Cancelled")
        self.assertEqual(normalize_appointment_status("unknown status"), "Pending")

        # Verify all outputs are strictly in VALID_APPOINTMENT_STATUSES
        for raw in ["Reschedule Pending", "Doctor Unavailable", "Confirmed", "Pending", "Completed", "Cancelled", ""]:
            norm = normalize_appointment_status(raw)
            self.assertIn(norm, VALID_APPOINTMENT_STATUSES)

    def test_medication_schedule_suggestion_query(self):
        """Verify suggestion button query 'What meds do I take and when?' returns full organized medication schedule."""
        res = run(self.orchestrator, "What meds do I take and when?", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("medication schedule", res.message.lower())
        self.assertIn("Pantocid 40", res.message)
        self.assertIn("Dolo 650", res.message)
        self.assertIn("Shelcal 500", res.message)
        self.assertIn("Morning / Breakfast", res.message)
        self.assertIn("Afternoon / Lunch", res.message)

    def test_confirmation_inquiry_query(self):
        """Verify asking whether agent can confirm appointment returns informative instructions rather than mutating or erroring."""
        res = run(self.orchestrator, "Can I confirm appointment via agent?", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("confirm", res.message.lower())
        self.assertIn("Confirm appointment", res.message)
        self.assertIn("Dr. Rhea Mehta", res.message)

    def test_summary_agent_greeting(self):
        """Verify saying 'Hello' returns personal care assistant greeting."""
        res = run(self.orchestrator, "Hello", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Hello Ananya", res.message)
        self.assertIn("personal care assistant", res.message)

    def test_summary_agent_diagnosis(self):
        """Verify asking 'What is my diagnosis?' returns clinical diagnosis details."""
        res = run(self.orchestrator, "What is my diagnosis?", self.care_data, "22222222-2222-2222-2222-222222222222")
        self.assertIn("Clinical Diagnosis", res.message)
        self.assertIn("Appendicitis", res.message)


if __name__ == "__main__":
    unittest.main()

