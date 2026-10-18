"""Unit tests for Doctor Multi-Agent Orchestrator, parsing, and specialized agents."""

import unittest
from orchestrator.doctor_orchestrator import parse_date_safe, classify_doctor_intent, run_doctor_orchestrator
from tools.seed_data import DR_RHEA_WEEKLY_APPTS, DOC_RHEA_ID


class TestDoctorOrchestrator(unittest.TestCase):

    def test_word_boundary_date_parsing(self):
        """Ensure 22nd resolves to 22 and never matches 2nd."""
        # Date queries with month
        self.assertEqual(parse_date_safe("what's me schedule on 21st oct"), "2026-10-21")
        self.assertEqual(parse_date_safe("whats my schedule on 22nd oct?"), "2026-10-22")
        self.assertEqual(parse_date_safe("schedule on 2nd oct"), "2026-10-02")
        self.assertEqual(parse_date_safe("block 23rd october"), "2026-10-23")
        self.assertEqual(parse_date_safe("leave on 3rd oct"), "2026-10-03")

        # Date queries with omitted month (should default to October 2026)
        self.assertEqual(parse_date_safe("what's my schedule on the 21st"), "2026-10-21")
        self.assertEqual(parse_date_safe("appointments on 22nd"), "2026-10-22")
        self.assertEqual(parse_date_safe("schedule on 19th"), "2026-10-19")
        self.assertEqual(parse_date_safe("on 1st"), "2026-10-01")

    def test_intent_classification(self):
        """Verify intent classification accurately detects intent categories."""
        # Schedule queries (including typos like 'what's me schedule')
        self.assertEqual(classify_doctor_intent("what's me schedule on 21st oct"), "CHECK_SCHEDULE")
        self.assertEqual(classify_doctor_intent("how many appointments do I have on 22nd?"), "CHECK_SCHEDULE")
        self.assertEqual(classify_doctor_intent("show my agenda for today"), "CHECK_SCHEDULE")

        # Unavailability / Leave blocking
        self.assertEqual(
            classify_doctor_intent("I'm not available on 22nd oct, block this day in Supabase"),
            "BLOCK_UNAVAILABILITY",
        )
        self.assertEqual(classify_doctor_intent("take off on 23rd oct"), "BLOCK_UNAVAILABILITY")

        # Patient inquiry by name and medications
        sample_patients = [
            {"name": "Ananya Iyer", "first_name": "Ananya", "last_name": "Iyer", "patient_id": "22222222-2222-2222-2222-222222222222"},
            {"name": "Neha Kapoor", "first_name": "Neha", "last_name": "Kapoor", "patient_id": "22222222-2222-2222-2222-222222222002"},
        ]
        self.assertEqual(classify_doctor_intent("Tell me about Neha Kapoor", all_patients=sample_patients), "PATIENT_QUERY")
        self.assertEqual(classify_doctor_intent("Tell me about Neha Kapoor's medications", all_patients=sample_patients), "PATIENT_QUERY")
        self.assertEqual(classify_doctor_intent("what medication is Ananya Iyer taking?", all_patients=sample_patients), "PATIENT_QUERY")
        self.assertEqual(classify_doctor_intent("what is Ananya taking?", all_patients=sample_patients), "PATIENT_QUERY")
        self.assertEqual(classify_doctor_intent("who is Vikram Malhotra"), "PATIENT_QUERY")
        self.assertEqual(classify_doctor_intent("patient info / summary"), "PATIENT_QUERY")

        # Chit-chat deflection (without pending action)
        self.assertEqual(classify_doctor_intent("hello"), "CHIT_CHAT")
        self.assertEqual(classify_doctor_intent("ok"), "CHIT_CHAT")
        self.assertEqual(classify_doctor_intent("thanks"), "CHIT_CHAT")
        self.assertEqual(classify_doctor_intent("what can you do"), "CHIT_CHAT")

        # Confirmations
        self.assertEqual(classify_doctor_intent("yes"), "CONFIRM_ACTION")
        self.assertEqual(classify_doctor_intent("confirm"), "CONFIRM_ACTION")

        # Confirmation with pending action (e.g. Doctor replying 'ok', 'okay', 'sure', 'proceed' to leave proposal)
        dummy_pending = {"type": "block_unavailability", "date": "2026-10-22"}
        self.assertEqual(classify_doctor_intent("ok", pending_action=dummy_pending), "CONFIRM_ACTION")
        self.assertEqual(classify_doctor_intent("okay", pending_action=dummy_pending), "CONFIRM_ACTION")
        self.assertEqual(classify_doctor_intent("sure", pending_action=dummy_pending), "CONFIRM_ACTION")
        self.assertEqual(classify_doctor_intent("proceed", pending_action=dummy_pending), "CONFIRM_ACTION")
        self.assertEqual(classify_doctor_intent("yes please", pending_action=dummy_pending), "CONFIRM_ACTION")

    def test_seed_data_has_22_weekly_and_16_next_week_appointments(self):
        """Verify the baseline for Dr. Rhea Mehta contains exactly 22 appointments this week and 16 next week."""
        from tools.seed_data import DR_RHEA_NEXT_WEEK_APPTS

        rhea_weekly = [a for a in DR_RHEA_WEEKLY_APPTS if a.get("doctor_id") == DOC_RHEA_ID]
        self.assertEqual(len(rhea_weekly), 22)

        expected_weekly_counts = {
            "2026-10-18": 3,
            "2026-10-19": 4,
            "2026-10-20": 3,
            "2026-10-21": 4,
            "2026-10-22": 3,
            "2026-10-23": 3,
            "2026-10-24": 2,
        }
        for date_str, exp_cnt in expected_weekly_counts.items():
            cnt = len([a for a in rhea_weekly if date_str in a.get("appointment_datetime", "")])
            self.assertEqual(cnt, exp_cnt, f"Failed on date {date_str}: expected {exp_cnt}, got {cnt}")

        rhea_next_week = [a for a in DR_RHEA_NEXT_WEEK_APPTS if a.get("doctor_id") == DOC_RHEA_ID]
        self.assertEqual(len(rhea_next_week), 16)

        expected_next_week_counts = {
            "2026-10-25": 2,
            "2026-10-26": 3,
            "2026-10-27": 3,
            "2026-10-28": 3,
            "2026-10-29": 2,
            "2026-10-30": 2,
            "2026-10-31": 1,
        }
        for date_str, exp_cnt in expected_next_week_counts.items():
            cnt = len([a for a in rhea_next_week if date_str in a.get("appointment_datetime", "")])
            self.assertEqual(cnt, exp_cnt, f"Failed on next week date {date_str}: expected {exp_cnt}, got {cnt}")

        # Verify Ananya Iyer's appointment on 22 Oct 2026 at 11:00 AM is Pending (not-confirmed)
        ananya_appt = next(a for a in rhea_weekly if a.get("appointment_id") == "33333333-3333-3333-3333-333333331001")
        self.assertEqual(ananya_appt["status"], "Pending")

    def test_orchestrator_schedule_query_execution(self):
        """Verify running the orchestrator with a schedule query returns counts and formatted table."""
        snapshot = {
            "doctor": {"name": "Dr. Rhea Mehta", "doctor_id": DOC_RHEA_ID},
            "all_appointments": [
                {"patient_name": "Vikram Malhotra", "raw_datetime": "2026-10-19 09:30:00", "time": "09:30 AM", "type": "Consultation", "status": "Confirmed"},
                {"patient_name": "Neha Kapoor", "raw_datetime": "2026-10-19 11:30:00", "time": "11:30 AM", "type": "Consultation", "status": "Confirmed"},
            ],
            "patients_overview": [],
        }
        res = run_doctor_orchestrator("what's me schedule on 19th oct", snapshot, client=None)
        self.assertEqual(res["agent"], "Doctor Schedule Agent")
        self.assertIn("2 appointments", res["message"])
        self.assertIn("Vikram Malhotra", res["message"])
        self.assertIn("Neha Kapoor", res["message"])


if __name__ == "__main__":
    unittest.main()
