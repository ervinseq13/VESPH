"""Unit tests for Consultation Ingestion and RAG parsing pipeline."""

import unittest
from tools.consultation_ingestion import (
    generate_sample_consultation_pdf,
    extract_text_from_pdf,
    parse_consultation_text,
)


class TestConsultationRAG(unittest.TestCase):
    def test_sample_pdf_generation_and_text_extraction(self):
        pdf_bytes = generate_sample_consultation_pdf()
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)

        extracted_text = extract_text_from_pdf(pdf_bytes)
        self.assertIn("VESPH Care", extracted_text)
        self.assertIn("Dr. Rhea Mehta", extracted_text)
        self.assertIn("Ananya Iyer", extracted_text)
        self.assertIn("appendectomy", extracted_text.lower())

    def test_clinical_entity_parsing(self):
        pdf_bytes = generate_sample_consultation_pdf()
        text = extract_text_from_pdf(pdf_bytes)
        parsed = parse_consultation_text(text)

        self.assertEqual(parsed["patient_name"], "Ananya Iyer")
        self.assertIn("appendectomy", parsed["diagnosis"].lower())
        self.assertGreaterEqual(len(parsed["medications"]), 2)
        self.assertGreaterEqual(len(parsed["appointments"]), 1)

        # Validate meal timings
        meal_timings = [m.get("meal_timing") for m in parsed["medications"]]
        self.assertIn("breakfast", meal_timings)

    def test_appointment_summary_and_supabase_sync(self):
        from unittest.mock import MagicMock
        from tools.consultation_ingestion import ingest_consultation_to_supabase

        pdf_bytes = generate_sample_consultation_pdf()
        text = extract_text_from_pdf(pdf_bytes)
        parsed = parse_consultation_text(text)

        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[{"id": "dummy-id"}])

        res = ingest_consultation_to_supabase(
            mock_client,
            parsed,
            doctor_id="doc-1",
            default_patient_id="pat-1",
            appointment_id="APT-TEST-001",
        )

        self.assertEqual(res.get("appointment_id"), "APT-TEST-001")
        self.assertIn("key_summary", res)
        self.assertTrue(len(res["key_summary"]) > 0)
        self.assertIn("diagnosis", res)
        self.assertIn("vitals", res)
        self.assertIn("treatment_plan", res)


if __name__ == "__main__":
    unittest.main()
