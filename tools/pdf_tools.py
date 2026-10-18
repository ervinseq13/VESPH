"""PDF generation utilities for VESPH Care record downloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from fpdf import FPDF


def _safe(value: Any) -> str:
    """Return a string safe for PDF rendering, stripping None values."""
    if value is None:
        return ""
    return str(value)


def generate_record_pdf(
    record: dict[str, Any],
    record_type: str,
    patient_name: str = "Patient",
) -> bytes:
    """Generate a professionally formatted PDF for a care record.

    Returns raw bytes suitable for ``st.download_button(data=...)``.
    """

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- Header ---
    pdf.set_fill_color(11, 110, 105)  # Teal brand colour
    pdf.rect(0, 0, 210, 28, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_y(6)
    pdf.cell(0, 10, "VESPH Care", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "Virtual Engagement System for Patient Health", new_x="LMARGIN", new_y="NEXT", align="C")

    # --- Patient & date bar ---
    pdf.set_text_color(23, 53, 50)
    pdf.set_y(34)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, f"Patient: {patient_name}    |    Generated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}", new_x="LMARGIN", new_y="NEXT")
    pdf.line(10, 42, 200, 42)
    pdf.set_y(45)

    if record_type == "appointment":
        _appointment_pdf(pdf, record)
    elif record_type == "diagnostic_result":
        _diagnostic_pdf(pdf, record)
    elif record_type == "diagnostic_booking":
        _diagnostic_booking_pdf(pdf, record)
    elif record_type == "medication":
        _medication_pdf(pdf, record)
    elif record_type in ("discharge", "discharge_upload"):
        _discharge_pdf(pdf, record)
    else:
        _generic_pdf(pdf, record)

    # --- Footer ---
    pdf.set_y(-25)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(120, 140, 137)
    pdf.cell(0, 4, "This document is generated from a synthetic demonstration record.", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 4, "It does not replace your doctor or an official hospital record.", new_x="LMARGIN", new_y="NEXT", align="C")

    return pdf.output()


def _section(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(11, 110, 105)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(23, 53, 50)
    pdf.set_font("Helvetica", "", 10)


def _row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(52, 6, label)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _safe(value), new_x="LMARGIN", new_y="NEXT")


def _appointment_pdf(pdf: FPDF, record: dict) -> None:
    _section(pdf, "Appointment Record")
    pdf.ln(2)
    _row(pdf, "Type:", _safe(record.get("type")))
    _row(pdf, "Date:", _safe(record.get("date")))
    _row(pdf, "Time:", _safe(record.get("time")))
    _row(pdf, "Doctor:", _safe(record.get("doctor")))
    _row(pdf, "Department:", _safe(record.get("department")))
    _row(pdf, "Location:", _safe(record.get("location")))
    _row(pdf, "Status:", _safe(record.get("status")))
    if record.get("preparation"):
        pdf.ln(3)
        _section(pdf, "Preparation Instructions")
        pdf.multi_cell(0, 5, _safe(record.get("preparation")))


def _diagnostic_pdf(pdf: FPDF, record: dict) -> None:
    _section(pdf, "Diagnostic Result")
    pdf.ln(2)
    _row(pdf, "Test Name:", _safe(record.get("name")))
    _row(pdf, "Date:", _safe(record.get("date")))
    _row(pdf, "Category:", _safe(record.get("category")))
    _row(pdf, "Ordered By:", _safe(record.get("ordered_by")))
    _row(pdf, "Status:", _safe(record.get("status")))
    _row(pdf, "Result:", _safe(record.get("result_value", record.get("summary", ""))))
    _row(pdf, "Reference Range:", _safe(record.get("reference_range", "")))
    _row(pdf, "Flag:", _safe(record.get("flag")))
    if record.get("summary"):
        pdf.ln(3)
        _section(pdf, "Summary")
        pdf.multi_cell(0, 5, _safe(record.get("summary")))


def _diagnostic_booking_pdf(pdf: FPDF, record: dict) -> None:
    _section(pdf, "Diagnostic Booking")
    pdf.ln(2)
    _row(pdf, "Test:", _safe(record.get("test")))
    _row(pdf, "Date:", _safe(record.get("date")))
    _row(pdf, "Time:", _safe(record.get("time")))
    _row(pdf, "Location:", _safe(record.get("location")))
    _row(pdf, "Status:", _safe(record.get("status")))
    if record.get("preparation"):
        pdf.ln(3)
        _section(pdf, "Preparation")
        pdf.multi_cell(0, 5, _safe(record.get("preparation")))


def _medication_pdf(pdf: FPDF, record: dict) -> None:
    _section(pdf, "Medication Record")
    pdf.ln(2)
    _row(pdf, "Medication:", _safe(record.get("name")))
    _row(pdf, "Instructions:", _safe(record.get("instruction")))
    _row(pdf, "Duration:", _safe(record.get("duration")))
    _row(pdf, "Meal Timing:", _safe(record.get("meal_timing", "General")).capitalize())
    _row(pdf, "Next Dose:", _safe(record.get("next_dose")))
    _row(pdf, "Status:", _safe(record.get("status")))


def _discharge_pdf(pdf: FPDF, record: dict) -> None:
    _section(pdf, "Discharge Summary")
    pdf.ln(2)
    _row(pdf, "Discharge Date:", _safe(record.get("discharge_date", record.get("date", ""))))
    _row(pdf, "Consultant:", _safe(record.get("consultant", "")))
    _row(pdf, "Department:", _safe(record.get("department", "")))
    _row(pdf, "Diagnosis:", _safe(record.get("diagnosis", "")))
    _row(pdf, "Procedure:", _safe(record.get("procedure", "")))
    if record.get("condition_at_discharge"):
        pdf.ln(3)
        _section(pdf, "Condition at Discharge")
        pdf.multi_cell(0, 5, _safe(record.get("condition_at_discharge")))
    if record.get("instructions"):
        pdf.ln(3)
        _section(pdf, "Post-Discharge Instructions")
        for instruction in record.get("instructions", []):
            pdf.cell(8, 5, chr(8226))  # bullet
            pdf.multi_cell(0, 5, _safe(instruction))
    if record.get("follow_up"):
        pdf.ln(2)
        _row(pdf, "Follow-up:", _safe(record.get("follow_up")))


def _generic_pdf(pdf: FPDF, record: dict) -> None:
    _section(pdf, "Care Record")
    pdf.ln(2)
    for key, value in record.items():
        if key.startswith("_") or key == "id":
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        _row(pdf, f"{label}:", _safe(value))
