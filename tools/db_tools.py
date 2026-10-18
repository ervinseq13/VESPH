"""Live Supabase database tools for the VESPH care workflow."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any
from uuid import uuid4

from supabase import Client

from orchestrator.state import EscalationState


# --- Appointment Slot Generation ---
# 15-minute appointments with 5-minute buffer = 20-minute cadence
WORKING_HOURS = [
    ("09:00", "13:00"),  # Morning OPD
    ("14:00", "17:00"),  # Afternoon OPD
]
SLOT_DURATION_MINS = 15
BUFFER_MINS = 5
CADENCE_MINS = SLOT_DURATION_MINS + BUFFER_MINS  # 20 min


def short_patient_id(pid: str | None) -> str:
    """Format a clean, short, professional Patient ID for display (e.g. PID-8421 or PID-2222)."""
    if not pid:
        return "PID-8421"
    clean = str(pid).strip()
    if clean == "22222222-2222-2222-2222-222222222222" or clean.endswith("2222"):
        return "PID-8421"
    clean_no_hyphen = clean.replace("-", "").upper()
    return f"PID-{clean_no_hyphen[-4:]}"


def short_doctor_id(did: str | None) -> str:
    """Format a clean, short, professional Doctor ID for display (e.g. DOC-RHEA-01 or DOC-1111)."""
    if not did:
        return "DOC-RHEA-01"
    clean = str(did).strip()
    if clean == "11111111-1111-1111-1111-111111111111" or "1111" in clean:
        return "DOC-RHEA-01"
    clean_no_hyphen = clean.replace("-", "").upper()
    return f"DOC-{clean_no_hyphen[-4:]}"


def short_medicine_id(mid: str | None) -> str:
    """Format a clean, short, professional Medicine ID for display (e.g. MED-6661)."""
    if not mid:
        return "MED-6661"
    clean = str(mid).strip().replace("-", "").upper()
    return f"MED-{clean[-4:]}"


def short_appointment_id(aid: str | None) -> str:
    """Format a clean, short, professional Appointment ID for display (e.g. APT-1001)."""
    if not aid:
        return "APT-1001"
    clean = str(aid).strip().replace("-", "").upper()
    return f"APT-{clean[-4:]}"


def short_consultation_id(cid: str | None) -> str:
    """Format a clean, short, professional Consultation ID for display (e.g. CON-1001)."""
    if not cid:
        return "CON-1001"
    clean = str(cid).strip().replace("-", "").upper()
    return f"CON-{clean[-4:]}"


def short_diagnostic_id(did: str | None) -> str:
    """Format a clean, short, professional Diagnostic/Lab ID for display (e.g. LAB-1001)."""
    if not did:
        return "LAB-1001"
    clean = str(did).strip().replace("-", "").upper()
    return f"LAB-{clean[-4:]}"


VALID_APPOINTMENT_STATUSES = {
    "Confirmed",
    "Pending",
    "Completed",
    "Cancelled",
    "Rescheduled",
}

STATUS_NORMALIZATION_MAP = {
    "reschedule pending": "Pending",
    "rescheduled": "Rescheduled",
    "reschedule": "Pending",
    "pending confirmation": "Pending",
    "pending": "Pending",
    "confirmed": "Confirmed",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
    "completed": "Completed",
    "doctor unavailable (reschedule required)": "Cancelled",
    "doctor unavailable": "Cancelled",
    "unavailable": "Cancelled",
}


def normalize_appointment_status(status: str | None) -> str:
    """Normalize any status string to a valid PostgreSQL appointment_status_enum value."""
    if not status:
        return "Pending"
    clean = str(status).strip().lower()
    if clean in STATUS_NORMALIZATION_MAP:
        return STATUS_NORMALIZATION_MAP[clean]
    for valid in VALID_APPOINTMENT_STATUSES:
        if valid.lower() == clean:
            return valid
    return "Pending"


def generate_available_slots(
    client: Client,
    doctor_id: str,
    date: str,
) -> list[str]:
    """Return available 15-min timeslots for a doctor on a date.

    Args:
        client: Supabase client.
        doctor_id: UUID of the doctor.
        date: Date string in ``YYYY-MM-DD`` format.

    Returns:
        List of available time strings like ``["09:00 AM", "09:20 AM", ...]``.
    """

    # 1. Generate all candidate slots within working hours
    all_slots: list[datetime] = []
    base_date = datetime.strptime(date, "%Y-%m-%d")
    for start_str, end_str in WORKING_HOURS:
        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))
        cursor = base_date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end_time = base_date.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        while cursor + timedelta(minutes=SLOT_DURATION_MINS) <= end_time:
            all_slots.append(cursor)
            cursor += timedelta(minutes=CADENCE_MINS)

    # 2. Query existing appointments for doctor on date
    booked_times: set[str] = set()
    try:
        date_start = f"{date}T00:00:00"
        date_end = f"{date}T23:59:59"
        appt_resp = (
            client.table("appointments")
            .select("appointment_datetime")
            .eq("doctor_id", doctor_id)
            .gte("appointment_datetime", date_start)
            .lte("appointment_datetime", date_end)
            .not_.in_("status", ["Cancelled"])
            .execute()
        )
        for appt in appt_resp.data or []:
            dt_str = appt.get("appointment_datetime")
            if dt_str:
                try:
                    dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
                    booked_times.add(dt.strftime("%H:%M"))
                except Exception:
                    pass
    except Exception:
        pass

    # 3. Query doctor_unavailability for date
    blocked_slots: set[str] = set()
    full_day_blocked = False
    try:
        unavail_resp = (
            client.table("doctor_unavailability")
            .select("block_type, blocked_slot")
            .eq("doctor_id", doctor_id)
            .eq("blocked_date", date)
            .execute()
        )
        for unavail in unavail_resp.data or []:
            if unavail.get("block_type") == "full_day":
                full_day_blocked = True
                break
            slot = unavail.get("blocked_slot")
            if slot:
                try:
                    dt = datetime.strptime(slot.strip(), "%I:%M %p")
                    blocked_slots.add(dt.strftime("%H:%M"))
                except Exception:
                    blocked_slots.add(slot)
    except Exception:
        pass

    if full_day_blocked:
        return []

    # 4. Subtract booked and blocked slots
    available: list[str] = []
    for slot_dt in all_slots:
        slot_key = slot_dt.strftime("%H:%M")
        if slot_key not in booked_times and slot_key not in blocked_slots:
            available.append(slot_dt.strftime("%I:%M %p").lstrip("0"))

    return available


def _calculate_age(dob_str: str | None) -> int:
    if not dob_str:
        return 32
    try:
        dob = datetime.strptime(str(dob_str)[:10], "%Y-%m-%d")
        today = datetime.now()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except Exception:
        return 32


def _format_datetime(dt_str: Any) -> tuple[str, str]:
    if not dt_str:
        return ("Date to be confirmed", "Time to be confirmed")
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        date_formatted = dt.strftime("%d %b %Y")
        time_formatted = dt.strftime("%I:%M %p").lstrip("0")
        return (date_formatted, time_formatted)
    except Exception:
        return (str(dt_str), "")


def fetch_patient_snapshot(client: Client, patient_id: str | None = None) -> dict[str, Any]:
    """Retrieve full care record from Supabase for a given patient."""

    # 1. Patients
    patient_query = client.table("patients").select("*")
    if patient_id:
        patient_query = patient_query.eq("patient_id", patient_id)
    patients_resp = patient_query.limit(1).execute()

    if not patients_resp.data:
        raise ValueError(f"No patient found in Supabase (id={patient_id})")

    p_row = patients_resp.data[0]
    pid = p_row["patient_id"]

    # 2. Doctors
    doctors_resp = client.table("doctors").select("*").execute()
    doctors_by_id = {doc["doctor_id"]: doc for doc in (doctors_resp.data or [])}

    primary_doc = doctors_by_id.get(p_row.get("primary_doctor_id"), {})
    primary_doc_name = primary_doc.get("doctor_name", "Dr. Rhea Mehta")
    primary_doc_dept = primary_doc.get("department", "General Surgery")

    # 3. Appointments
    appt_resp = (
        client.table("appointments")
        .select("*")
        .eq("patient_id", pid)
        .order("appointment_datetime", desc=False)
        .execute()
    )
    all_appts = []
    for appt in appt_resp.data or []:
        doc = doctors_by_id.get(appt.get("doctor_id"), {})
        d_str, t_str = _format_datetime(appt.get("appointment_datetime"))
        all_appts.append(
            {
                "id": str(appt["appointment_id"]),
                "short_id": short_appointment_id(appt["appointment_id"]),
                "date": d_str,
                "time": t_str,
                "datetime_raw": appt.get("appointment_datetime"),
                "doctor": doc.get("doctor_name", primary_doc_name),
                "department": doc.get("department", primary_doc_dept),
                "location": appt.get("location") or "Hospital OPD",
                "status": appt.get("status", "Confirmed"),
                "type": appt.get("appointment_type", "FollowUp"),
                "preparation": appt.get("appointment_summary") or "Bring your latest reports.",
            }
        )

    def _is_past_appt(a: dict) -> bool:
        if a.get("status") in ("Completed", "Cancelled"):
            return True
        raw = str(a.get("datetime_raw") or "")
        if raw and raw[:10] < "2026-10-18":
            return True
        return False

    # Sort upcoming appointments chronologically ascending (next nearest first)
    upcoming_appts = [a for a in all_appts if not _is_past_appt(a)]
    upcoming_appts.sort(key=lambda x: str(x.get("datetime_raw") or ""))

    # Sort past appointments chronologically descending (most recent first)
    past_appts = [a for a in all_appts if _is_past_appt(a)]
    for a in past_appts:
        if a.get("status") not in ("Cancelled", "Completed"):
            a["status"] = "Completed"
    past_appts.sort(key=lambda x: str(x.get("datetime_raw") or ""), reverse=True)

    appointments = upcoming_appts + past_appts

    # 4. Consultations & Vitals History
    consult_resp = (
        client.table("consultations")
        .select("*")
        .eq("patient_id", pid)
        .order("created_at", desc=True)
        .execute()
    )
    consultations = []
    for c in consult_resp.data or []:
        doc = doctors_by_id.get(c.get("doctor_id"), {})
        c_date, _ = _format_datetime(c.get("created_at"))
        consultations.append(
            {
                "id": str(c["consultation_id"]),
                "short_id": short_consultation_id(c["consultation_id"]),
                "date": c_date,
                "created_at_raw": c.get("created_at"),
                "doctor": doc.get("doctor_name", primary_doc_name),
                "department": doc.get("department", primary_doc_dept),
                "diagnosis": c.get("diagnosis", ""),
                "symptoms": c.get("symptoms", ""),
                "treatment_plan": c.get("treatment_plan", ""),
                "summary": c.get("consultation_summary", ""),
                "vitals": {
                    "bp_systolic": c.get("bp_systolic"),
                    "bp_diastolic": c.get("bp_diastolic"),
                    "sugar": c.get("sugar_reading"),
                    "height_cm": c.get("height_cm"),
                    "weight_kg": c.get("weight_kg"),
                },
            }
        )
    latest_consult = consult_resp.data[0] if consult_resp.data else {}

    # 5. Medicines & Prescriptions
    meds_resp = client.table("medicines").select("*").execute()
    meds_by_id = {m["medicine_id"]: m for m in (meds_resp.data or [])}

    presc_resp = (
        client.table("prescription_details")
        .select("*")
        .eq("patient_id", pid)
        .order("start_date", desc=True)
        .execute()
    )
    medications = []
    for p in presc_resp.data or []:
        m_info = meds_by_id.get(p.get("medicine_id"), {})
        brand = m_info.get("brand_name") or m_info.get("generic_name") or "Medication"
        dosage = p.get("dosage", "")
        timing = p.get("meal_timing")
        if not timing:
            inst = (p.get("instructions") or "").lower()
            if "breakfast" in inst or "morning" in inst or "empty stomach" in inst:
                timing = "breakfast"
            elif "lunch" in inst or "afternoon" in inst:
                timing = "lunch"
            else:
                timing = "dinner"

        # Clean trailing numbers from brand name if dosage is present (e.g. "Dolo 650" + "650 mg" -> "Dolo 650 mg")
        clean_brand = re.sub(r"\s*\d+\s*$", "", brand).strip()
        disp_name = f"{clean_brand} {dosage}".strip() if (clean_brand and dosage) else (f"{brand} {dosage}".strip() if dosage else brand)

        medications.append(
            {
                "id": str(p["prescription_item_id"]),
                "medicine_id": str(p.get("medicine_id", "")),
                "short_id": short_medicine_id(p.get("medicine_id")),
                "rx_id": f"RX-{str(p['prescription_item_id'])[-4:].upper()}",
                "name": disp_name,
                "brand_name": brand,
                "generic_name": m_info.get("generic_name", ""),
                "dosage": dosage,
                "meal_timing": timing,
                "instruction": p.get("instructions") or f"{p.get('frequency_per_day', 'Daily')}",
                "duration": f"{p.get('duration_days', 7)} days",
                "next_dose": p.get("frequency_per_day", "Daily schedule"),
                "status": "Taken today" if p.get("is_taken") else "Scheduled",
                "is_taken": bool(p.get("is_taken", False)),
                "refill_needed": bool(p.get("refill_needed", False)),
            }
        )

    # 6. Diagnostics & Results
    diag_resp = (
        client.table("diagnostics")
        .select("*")
        .eq("patient_id", pid)
        .order("order_datetime", desc=True)
        .execute()
    )
    diagnostics = []
    order_ids = [d["order_id"] for d in (diag_resp.data or [])]
    results_by_order: dict[str, list[dict]] = {}
    if order_ids:
        results_resp = (
            client.table("diagnostics_results")
            .select("*")
            .in_("order_id", order_ids)
            .order("result_datetime", desc=True)
            .execute()
        )
        for r in results_resp.data or []:
            results_by_order.setdefault(r["order_id"], []).append(r)

    for d in diag_resp.data or []:
        r_list = results_by_order.get(d["order_id"], [])
        d_date, _ = _format_datetime(d.get("order_datetime"))
        doc = doctors_by_id.get(d.get("ordered_by_doctor_id"), {})
        if r_list:
            for r in r_list:
                diagnostics.append(
                    {
                        "id": str(r["result_id"]),
                        "order_id": str(d["order_id"]),
                        "short_id": short_diagnostic_id(d["order_id"]),
                        "date": d_date,
                        "name": r.get("test_name", "Diagnostic Test"),
                        "category": r.get("test_category", "Blood Work"),
                        "ordered_by": doc.get("doctor_name", primary_doc_name),
                        "status": "Reviewed" if d.get("order_status") == "Ready" else d.get("order_status", "Ready"),
                        "summary": r.get("result_summary") or f"Result: {r.get('result_value')} (Ref: {r.get('reference_range', 'Normal')})",
                        "result_value": r.get("result_value", ""),
                        "reference_range": r.get("reference_range", ""),
                        "flag": "Normal range" if "normal" in (r.get("result_summary") or "").lower() else "Review complete",
                        "report_url": r.get("report_file_url", ""),
                    }
                )
        else:
            diagnostics.append(
                {
                    "id": str(d["order_id"]),
                    "date": d_date,
                    "name": "Diagnostic order",
                    "category": "Diagnostics",
                    "ordered_by": doc.get("doctor_name", primary_doc_name),
                    "status": d.get("order_status", "Ordered"),
                    "summary": "Diagnostic test ordered by care team.",
                    "flag": "Pending",
                }
            )

    # 7. Operation / Discharge
    op_resp = (
        client.table("operation")
        .select("*")
        .eq("patient_id", pid)
        .order("scheduled_start_time", desc=True)
        .limit(1)
        .execute()
    )
    latest_op = op_resp.data[0] if op_resp.data else {}
    op_doctor = doctors_by_id.get(latest_op.get("lead_surgeon_id"), {})
    discharge_date, _ = _format_datetime(latest_op.get("actual_end_time") or latest_op.get("scheduled_start_time"))

    discharge = {
        "discharge_date": discharge_date or "10 Oct 2026",
        "consultant": op_doctor.get("doctor_name", primary_doc_name),
        "department": op_doctor.get("department", primary_doc_dept),
        "diagnosis": latest_consult.get("diagnosis") or "Post-laparoscopic appendectomy recovery",
        "procedure": latest_op.get("operation_name") or "Laparoscopic appendectomy",
        "condition_at_discharge": latest_op.get("discharge_summary") or "Discharged in stable condition. Incisions clean.",
        "instructions": [
            "Follow prescribed medication schedule diligently.",
            "Keep incision sites clean and dry; do not scrub surgical wounds.",
            "Avoid vigorous exercise or lifting objects heavier than 5 kg for 3 weeks.",
            "Attend scheduled surgical follow-up visit with your doctor.",
        ],
        "follow_up": latest_consult.get("recommended_consultation") or "Surgical follow-up in 2 weeks",
    }

    # 8. Escalations from DB
    esc_resp = (
        client.table("escalation_agent_data")
        .select("*")
        .eq("patient_id", pid)
        .order("created_at", desc=True)
        .execute()
    )
    escalations = []
    for esc in esc_resp.data or []:
        escalations.append(
            {
                "id": str(esc["ticket_id"]),
                "category": esc.get("category", "General"),
                "priority": esc.get("priority", "Medium"),
                "status": "confirmed" if esc.get("status") in ("Resolved", "Closed") else "pending_confirmation",
                "summary": esc.get("ai_detected_reason", ""),
                "resolution": esc.get("resolution_notes") or "",
                "created_at": esc.get("created_at"),
            }
        )

    # 9. Available Diagnostic Schedule & Doctor Slots
    diagnostic_schedule = []
    for appt in appointments:
        if appt.get("type") == "Diagnostic":
            diagnostic_schedule.append(
                {
                    "id": appt["id"],
                    "test": appt.get("preparation", "Complete Blood Count (CBC)"),
                    "date": appt["date"],
                    "time": appt["time"],
                    "location": appt.get("location", "Pathology Lab · 1st Floor"),
                    "status": "Booked" if appt.get("status") in ("Confirmed", "Pending") else appt.get("status"),
                    "preparation": "Bring previous reports. No fasting required unless specified.",
                }
            )
    if not diagnostic_schedule:
        diagnostic_schedule.append(
            {
                "id": "DS-CBC",
                "test": "Complete Blood Count (CBC)",
                "date": "20 Oct 2026",
                "time": "09:00 AM",
                "location": "Pathology Lab · 1st Floor",
                "status": "Booked",
                "preparation": "No fasting required",
            }
        )

    try:
        unavail_resp = client.table("doctor_unavailability").select("*").execute()
        unavail_blocks = unavail_resp.data or []
    except Exception:
        unavail_blocks = []

    appointment_schedule = []
    base_dates = [
        ("21 Oct 2026", "2026-10-21"),
        ("22 Oct 2026", "2026-10-22"),
        ("23 Oct 2026", "2026-10-23"),
        ("24 Oct 2026", "2026-10-24"),
    ]
    for d in doctors_resp.data or []:
        doc_id = d["doctor_id"]
        for dt_str, iso_d in base_dates:
            try:
                active_slots = generate_available_slots(client, doc_id, iso_d)
            except Exception:
                active_slots = ["10:00 AM", "11:20 AM", "02:20 PM", "04:00 PM"]

            if active_slots:
                appointment_schedule.append(
                    {
                        "doctor": d["doctor_name"],
                        "doctor_id": doc_id,
                        "department": d.get("department", "General Medicine"),
                        "date": dt_str,
                        "slots": active_slots,
                    }
                )

    first_name = p_row.get("first_name", "")
    last_name = p_row.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or "Ananya Sharma"
    initials = "".join(part[0].upper() for part in full_name.split()[:2]) or "PT"

    # Assemble summary text
    diag_summary_text = (
        f"Latest diagnostics from {diagnostics[0]['date']}: {diagnostics[0]['name']} is {diagnostics[0]['status'].lower()}. {diagnostics[0]['summary']}"
        if diagnostics
        else "No pending diagnostic reports."
    )
    med_summary_text = (
        f"{len(medications)} active prescriptions on file, including {medications[0]['name']} ({medications[0]['instruction']})."
        if medications
        else "No active prescriptions."
    )
    # Agentic appointment and diagnostic summary generated from the last 6 months + upcoming schedule
    up_diag_str = None
    if diagnostic_schedule:
        ds = diagnostic_schedule[0]
        up_diag_str = f"Upcoming diagnostic: {ds.get('test', 'CBC')} on {ds.get('date', '20 Oct')} ({ds.get('time', '09:00 AM')})"

    up_appt_str = None
    future_appts = [a for a in appointments if not _is_past_appt(a)]
    if future_appts:
        fa = future_appts[0]
        up_appt_str = f"Surgical follow-up: {fa.get('doctor', 'Dr. Rhea Mehta')} on {fa.get('date', '22 Oct')} ({fa.get('time', '11:00 AM')})"

    # 6-Month history highlights (April 2026 – Oct 2026)
    recent_events = []
    for c in consultations:
        raw_dt = str(c.get("created_at_raw") or c.get("date") or "")
        diag = str(c.get("diagnosis") or "").lower()
        doc = str(c.get("doctor") or "").lower()
        if "2026" in raw_dt:
            if "append" in diag or "appendectomy" in diag:
                recent_events.append("Emergency appendectomy (Oct 2026)")
            elif "pulmonary" in diag or "asthma" in diag or "kulkarni" in doc:
                recent_events.append("Pre-op pulmonary clearance (Sep 2026)")
            elif "iron" in diag or "ferritin" in diag or "rao" in doc:
                recent_events.append("Internal medicine review (Aug 2026)")

    seen_events = set()
    unique_recent = []
    for e in recent_events:
        if e not in seen_events:
            seen_events.add(e)
            unique_recent.append(e)

    history_highlights = ", ".join(unique_recent[:2]) if unique_recent else "emergency laparoscopic appendectomy with clean recovery"

    summary_parts = []
    if up_diag_str and up_appt_str:
        summary_parts.append(f"{up_diag_str}; {up_appt_str}.")
    elif up_diag_str:
        summary_parts.append(f"{up_diag_str}.")
    elif up_appt_str:
        summary_parts.append(f"{up_appt_str}.")
    else:
        summary_parts.append("No immediate visits scheduled.")

    summary_parts.append(f"Past 6 months: {history_highlights}.")
    appt_summary_text = " ".join(summary_parts)

    patient_dict = {
        "id": str(pid),
        "name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "initials": initials,
        "age": _calculate_age(p_row.get("date_of_birth")),
        "gender": p_row.get("gender", "Female"),
        "blood_group": p_row.get("blood_type", "B+"),
        "phone": p_row.get("contact_phone", ""),
        "email": p_row.get("contact_email", ""),
        "address": p_row.get("address", ""),
        "emergency_contact": f"{p_row.get('emergency_contact_name', '')} ({p_row.get('emergency_contact_phone', '')})",
        "primary_doctor": primary_doc_name,
        "care_team": primary_doc_dept,
        "allergies": ["Penicillin"],
        "conditions": ["Mild asthma", "Post-operative recovery"],
        "last_visit": "10 Oct 2026",
        "health_summary": p_row.get("patient_summary")
        or "Recovering well after laparoscopic appendectomy. Pain is controlled and incisions are dry.",
        "diagnostic_summary": diag_summary_text,
        "medication_summary": med_summary_text,
        "appointment_summary": appt_summary_text,
        "vitals": {
            "bp_systolic": latest_consult.get("bp_systolic", 118),
            "bp_diastolic": latest_consult.get("bp_diastolic", 76),
            "sugar": latest_consult.get("sugar_reading", 96),
            "height_cm": latest_consult.get("height_cm", 165),
            "weight_kg": latest_consult.get("weight_kg", 58.5),
        },
    }

    return {
        "patient": patient_dict,
        "appointments": appointments,
        "consultations": consultations,
        "diagnostics": diagnostics,
        "discharge": discharge,
        "medications": medications,
        "appointment_schedule": appointment_schedule,
        "diagnostic_schedule": diagnostic_schedule,
        "escalations": escalations,
    }


def create_escalation(
    care_data: dict[str, Any],
    escalation: EscalationState,
    client: Client | None = None,
) -> EscalationState:
    """Persist an escalation ticket in Supabase and the active session state."""

    escalations = care_data.setdefault("escalations", [])
    existing = next((item for item in escalations if item["id"] == escalation["id"]), None)
    if existing is not None:
        return deepcopy(existing)

    ticket_record = deepcopy(escalation)
    escalations.append(ticket_record)

    # Persist to live Supabase escalation_agent_data table if client provided
    if client is not None:
        try:
            patient_id = care_data.get("patient", {}).get("id")
            category_mapping = {
                "emergency": "Emergency",
                "records": "Reissue Report",
                "diagnostics": "New Test",
                "doctor": "Doctor Unavailable",
                "scheduling": "Missed Appointment",
            }
            supabase_cat = category_mapping.get(
                str(ticket_record.get("category")).lower(), "Emergency"
            )

            client.table("escalation_agent_data").insert(
                {
                    "patient_id": patient_id,
                    "category": supabase_cat,
                    "priority": "Critical" if supabase_cat == "Emergency" else "High",
                    "status": "Open",
                    "ai_detected_reason": ticket_record.get("summary") or "Patient escalation initiated via chat",
                    "assigned_staff_role": "Duty Clinical Coordinator",
                }
            ).execute()
        except Exception:
            # Non-blocking for offline or edge cases
            pass

    return deepcopy(ticket_record)


def confirm_escalation(
    care_data: dict[str, Any],
    escalation_id: str,
    resolution: str,
    client: Client | None = None,
) -> EscalationState:
    """Record patient's chosen resolution in memory and Supabase."""

    escalations = care_data.setdefault("escalations", [])
    escalation = next((item for item in escalations if item["id"] == escalation_id), None)
    if escalation is None:
        raise ValueError("The escalation is no longer available to confirm.")
    if escalation.get("status") == "confirmed":
        return deepcopy(escalation)
    if resolution not in escalation.get("options", []):
        raise ValueError("Choose one of the resolution options shown in chat.")

    escalation["status"] = "confirmed"
    escalation["resolution"] = resolution

    if client is not None:
        try:
            client.table("escalation_agent_data").update(
                {
                    "status": "Resolved",
                    "resolution_notes": f"Confirmed by patient: {resolution}",
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("patient_id", care_data.get("patient", {}).get("id")).execute()
        except Exception:
            pass

    return deepcopy(escalation)


def update_appointment_in_supabase(
    client: Client,
    appointment_id: str,
    status: str,
    new_date: str | None = None,
    new_time: str | None = None,
) -> None:
    """Update appointment status or reschedule datetime in Supabase."""

    # If the dates are changing or if status indicates reschedule pending, it should be Pending confirmation
    if (new_date and new_time) or status.strip().lower() in ("reschedule pending", "pending confirmation", "reschedule"):
        normalized_status = "Pending"
    else:
        normalized_status = normalize_appointment_status(status)

    payload: dict[str, Any] = {"status": normalized_status}
    if new_date and new_time:
        try:
            dt_obj = datetime.strptime(f"{new_date} {new_time}", "%d %b %Y %I:%M %p")
            payload["appointment_datetime"] = dt_obj.isoformat()
        except Exception:
            pass

    client.table("appointments").update(payload).eq("appointment_id", appointment_id).execute()


def cancel_appointment_and_escalate_in_supabase(
    client: Client,
    appointment_id: str,
    patient_id: str,
    reason: str = "Doctor unavailable",
    doctor_name: str = "Dr. Rhea Mehta",
) -> dict[str, Any]:
    """Cancel an appointment due to doctor unavailability and dispatch an escalation for patient rebooking."""
    try:
        client.table("appointments").update({
            "status": "Cancelled",
            "appointment_summary": f"Cancelled: {reason}. Priority escalation dispatched for patient rebooking.",
        }).eq("appointment_id", appointment_id).execute()
    except Exception:
        pass

    ticket_payload = {
        "patient_id": patient_id,
        "category": "Doctor Unavailable",
        "priority": "High",
        "status": "Open",
        "ai_detected_reason": f"{doctor_name} is unavailable ({reason}). Escalation dispatched for patient priority rebooking.",
        "assigned_staff_role": "Duty Clinical Coordinator",
    }
    try:
        res = client.table("escalation_agent_data").insert(ticket_payload).execute()
        return res.data[0] if (res and res.data) else ticket_payload
    except Exception:
        return ticket_payload


def reschedule_appointment_with_new_record_in_supabase(
    client: Client,
    old_appointment_id: str,
    new_date: str,
    new_time: str,
    reason: str = "Rescheduled to new slot",
) -> dict[str, Any]:
    """Reschedule by creating a new appointment: marks old as 'Rescheduled' and new as 'Pending'."""
    old_resp = client.table("appointments").select("*").eq("appointment_id", old_appointment_id).execute()
    if not old_resp.data:
        raise ValueError(f"Appointment {old_appointment_id} not found")
    old_appt = old_resp.data[0]

    # 1. Mark old appointment as Rescheduled
    notice = f"Rescheduled to {new_date} at {new_time} ({reason})."
    client.table("appointments").update({
        "status": "Rescheduled",
        "appointment_summary": f"{old_appt.get('appointment_summary', '')}\n[Notice]: {notice}".strip(),
    }).eq("appointment_id", old_appointment_id).execute()

    # 2. Create new appointment marked as Pending
    new_aid = str(uuid4())
    try:
        dt_obj = datetime.strptime(f"{new_date} {new_time}", "%d %b %Y %I:%M %p")
        iso_dt = dt_obj.isoformat()
    except Exception:
        try:
            dt_obj = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %I:%M %p")
            iso_dt = dt_obj.isoformat()
        except Exception:
            iso_dt = f"{new_date}T10:00:00"

    new_appt_data = {
        "appointment_id": new_aid,
        "patient_id": old_appt["patient_id"],
        "doctor_id": old_appt["doctor_id"],
        "appointment_type": old_appt.get("appointment_type", "Consultation"),
        "appointment_datetime": iso_dt,
        "status": "Pending",
        "scheduled_by_role": old_appt.get("scheduled_by_role", "Doctor"),
        "location": old_appt.get("location", "Room 304, OPD Wing B"),
        "appointment_summary": f"Rescheduled appointment (previous: {old_appt.get('appointment_datetime', '')}). Awaiting patient confirmation.",
        "reminders_sent_count": 0,
    }
    res = client.table("appointments").insert(new_appt_data).execute()
    return {
        "old_appointment_id": old_appointment_id,
        "new_appointment_id": new_aid,
        "old_status": "Rescheduled",
        "new_status": "Pending",
        "new_appointment": res.data[0] if res.data else new_appt_data,
    }


def toggle_prescription_taken_in_supabase(
    client: Client,
    prescription_item_id: str,
    is_taken: bool,
) -> None:
    """Update medication intake status in Supabase."""

    client.table("prescription_details").update({"is_taken": is_taken}).eq(
        "prescription_item_id", prescription_item_id
    ).execute()


def fetch_all_patients(client: Client) -> list[dict[str, Any]]:
    """Retrieve summary list of all registered patients for the patient switcher."""
    resp = client.table("patients").select("*").order("first_name").execute()
    patients = []
    for p in resp.data or []:
        first = p.get("first_name", "")
        last = p.get("last_name", "")
        full_name = f"{first} {last}".strip()
        patients.append(
            {
                "id": p["patient_id"],
                "patient_id": p["patient_id"],
                "name": full_name,
                "first_name": first,
                "last_name": last,
                "age": _calculate_age(p.get("date_of_birth")),
                "gender": p.get("gender", ""),
                "blood_type": p.get("blood_type", ""),
                "phone": p.get("contact_phone", ""),
                "email": p.get("contact_email", ""),
                "summary": p.get("patient_summary", ""),
                "primary_doctor_id": p.get("primary_doctor_id"),
            }
        )
    return patients


def fetch_all_doctors(client: Client) -> list[dict[str, Any]]:
    """Retrieve all active doctors for the doctor portal."""
    resp = client.table("doctors").select("*").order("doctor_name").execute()
    doctors = []
    for d in resp.data or []:
        doc_copy = dict(d)
        doc_copy["id"] = d["doctor_id"]
        doc_copy["name"] = d.get("doctor_name", "Doctor")
        doctors.append(doc_copy)
    return doctors


def fetch_doctor_snapshot(client: Client, doctor_id: str) -> dict[str, Any]:
    """Retrieve dashboard data for a doctor including agenda, patients, and blocked slots."""
    raw_doc: dict[str, Any] = {}
    try:
        doc_resp = client.table("doctors").select("*").eq("doctor_id", doctor_id).execute()
        if doc_resp and doc_resp.data:
            raw_doc = doc_resp.data[0]
    except Exception:
        raw_doc = {}

    if not raw_doc:
        try:
            fallback_resp = client.table("doctors").select("*").limit(1).execute()
            if fallback_resp and fallback_resp.data:
                raw_doc = fallback_resp.data[0]
        except Exception:
            raw_doc = {}

    doc_name = raw_doc.get("doctor_name") or raw_doc.get("name") or "Dr. Rhea Mehta"
    resolved_doc_id = raw_doc.get("doctor_id") or raw_doc.get("id") or doctor_id

    parts = [p for p in doc_name.replace("Dr.", "").strip().split() if p]
    computed_initials = "".join([p[0].upper() for p in parts[:2]]) if parts else "DR"

    doc = {
        **raw_doc,
        "id": resolved_doc_id,
        "doctor_id": resolved_doc_id,
        "name": doc_name,
        "doctor_name": doc_name,
        "initials": raw_doc.get("initials") or computed_initials,
        "specialization": raw_doc.get("specialization") or raw_doc.get("qualifications", "General Surgery Specialist"),
        "qualifications": raw_doc.get("qualifications", "MBBS, MS (General Surgery)"),
        "department": raw_doc.get("department", "General Surgery"),
        "location": raw_doc.get("location") or raw_doc.get("room_no", "OPD Wing B, Room 304"),
        "room_no": raw_doc.get("room_no", "Room 304"),
        "email": raw_doc.get("email") or raw_doc.get("contact_email", "dr.mehta@vesphcare.com"),
        "contact_email": raw_doc.get("contact_email", "dr.mehta@vesphcare.com"),
        "contact_phone": raw_doc.get("contact_phone", "+91 22 4000 1100"),
        "is_active": raw_doc.get("is_active", True),
    }

    all_patients = fetch_all_patients(client)
    patients_by_id = {p["patient_id"]: p for p in all_patients}

    appts_resp = (
        client.table("appointments")
        .select("*")
        .eq("doctor_id", doctor_id)
        .order("appointment_datetime", desc=False)
        .execute()
    )
    all_appts = []
    for a in appts_resp.data or []:
        dt_val = a.get("appointment_datetime")
        date_str, time_str = _format_datetime(dt_val)
        p_info = patients_by_id.get(a.get("patient_id"), {})
        all_appts.append(
            {
                "id": str(a["appointment_id"]),
                "patient_id": a.get("patient_id"),
                "patient_name": p_info.get("name", "Registered Patient"),
                "patient_age": p_info.get("age", 32),
                "patient_gender": p_info.get("gender", ""),
                "patient_phone": p_info.get("phone", ""),
                "patient_summary": p_info.get("summary", ""),
                "type": a.get("appointment_type", "Consultation"),
                "date": date_str,
                "time": time_str,
                "raw_datetime": dt_val,
                "status": a.get("status", "Confirmed"),
                "location": a.get("location", doc.get("room_no", "OPD")),
                "summary": a.get("appointment_summary", ""),
            }
        )

    try:
        unavail_resp = (
            client.table("doctor_unavailability")
            .select("*")
            .eq("doctor_id", doctor_id)
            .order("blocked_date", desc=False)
            .execute()
        )
        unavail_list = unavail_resp.data or []
    except Exception:
        unavail_list = []

    upcoming = [a for a in all_appts if a["status"] != "Completed"]
    upcoming.sort(key=lambda x: str(x.get("raw_datetime", "")))

    today_str = "18 Oct 2026"
    today_appts = [a for a in upcoming if today_str in a["date"]]
    week_days = ["18 Oct", "19 Oct", "20 Oct", "21 Oct", "22 Oct", "23 Oct", "24 Oct"]
    week_appts = [a for a in upcoming if any(d in a["date"] for d in week_days)]
    past_appts = [a for a in all_appts if a["status"] == "Completed"]
    past_appts.sort(key=lambda x: str(x.get("raw_datetime", "")), reverse=True)

    return {
        "doctor": doc,
        "appointments": all_appts,
        "all_appointments": all_appts,
        "upcoming_appointments": upcoming,
        "today_appointments": today_appts,
        "week_appointments": week_appts,
        "past_appointments": past_appts,
        "unavailability": unavail_list,
        "patients": all_patients,
        "stats": {
            "today_count": len(today_appts),
            "week_count": len(week_appts),
            "blocked_count": len(unavail_list),
        },
    }


def block_doctor_slot_in_supabase(
    client: Client,
    doctor_id: str,
    blocked_date: str,
    blocked_slot: str | None = None,
    reason: str = "Doctor unavailable",
) -> list[dict[str, Any]]:
    """Mark doctor unavailable, identify conflicting patient appointments, and auto-rebook them."""
    is_full_day = not blocked_slot or blocked_slot.lower().strip() in ("all day", "full day")
    block_type = "full_day" if is_full_day else "timeslot"

    # Check if this date is already recorded in doctor_unavailability
    try:
        existing_block = (
            client.table("doctor_unavailability")
            .select("unavailability_id")
            .eq("doctor_id", doctor_id)
            .eq("blocked_date", blocked_date)
            .execute()
        )
        if not existing_block.data:
            client.table("doctor_unavailability").insert(
                {
                    "doctor_id": doctor_id,
                    "block_type": block_type,
                    "blocked_date": blocked_date,
                    "blocked_slot": blocked_slot if not is_full_day else None,
                    "reason": reason or "Doctor unavailable",
                }
            ).execute()
    except Exception:
        # Fallback direct insert if select fails
        try:
            client.table("doctor_unavailability").insert(
                {
                    "doctor_id": doctor_id,
                    "block_type": block_type,
                    "blocked_date": blocked_date,
                    "blocked_slot": blocked_slot if not is_full_day else None,
                    "reason": reason or "Doctor unavailable",
                }
            ).execute()
        except Exception:
            pass

    doc_resp = client.table("doctors").select("doctor_name").eq("doctor_id", doctor_id).execute()
    doc_name = doc_resp.data[0]["doctor_name"] if doc_resp.data else "Your doctor"

    appts = (
        client.table("appointments")
        .select("*")
        .eq("doctor_id", doctor_id)
        .neq("status", "Completed")
        .execute()
        .data
        or []
    )

    # 5. Dynamically generate fallback slots strictly after blocked_date, never on blocked_date
    default_fallbacks = [
        ("2026-10-26", "10:00 AM"),
        ("2026-10-26", "02:00 PM"),
        ("2026-10-27", "11:00 AM"),
        ("2026-10-27", "03:30 PM"),
        ("2026-10-28", "10:30 AM"),
        ("2026-10-28", "02:30 PM"),
        ("2026-10-29", "11:00 AM"),
        ("2026-10-30", "10:00 AM"),
    ]
    # Filter out any slots that match the blocked date
    valid_fallbacks = [(d, s) for d, s in default_fallbacks if d != blocked_date]
    if not valid_fallbacks:
        valid_fallbacks = [("2026-10-27", "10:00 AM"), ("2026-10-28", "02:00 PM")]

    rebooked = []
    fallback_idx = 0

    for a in appts:
        appt_dt = str(a.get("appointment_datetime", ""))
        if blocked_date in appt_dt:
            is_conflict = False
            if is_full_day:
                is_conflict = True
            else:
                _, t_str = _format_datetime(appt_dt)
                if blocked_slot and (
                    blocked_slot.lower().strip() in t_str.lower().strip()
                    or t_str.lower().strip() in blocked_slot.lower().strip()
                ):
                    is_conflict = True

            if is_conflict:
                next_date, next_slot = valid_fallbacks[min(fallback_idx, len(valid_fallbacks) - 1)]
                fallback_idx += 1
                try:
                    new_dt = datetime.strptime(f"{next_date} {next_slot}", "%Y-%m-%d %I:%M %p").isoformat()
                except Exception:
                    new_dt = f"{next_date}T10:00:00"

                notice = f"Doctor was unavailable on {blocked_date} ({reason}). Reschedule suggested for {next_date} at {next_slot}. Please confirm or select an alternate slot."
                current_summary = a.get("appointment_summary") or ""
                updated_summary = f"{current_summary}\n[Notice]: {notice}".strip()

                # Since the dates are changing, the appointment status is marked as Pending
                client.table("appointments").update(
                    {
                        "appointment_datetime": new_dt,
                        "status": "Pending",
                        "appointment_summary": updated_summary,
                    }
                ).eq("appointment_id", a["appointment_id"]).execute()

                # Insert priority rebooking ticket into escalation_agent_data
                try:
                    client.table("escalation_agent_data").insert(
                        {
                            "patient_id": a.get("patient_id"),
                            "category": "Doctor Unavailable",
                            "priority": "High",
                            "status": "Open",
                            "ai_detected_reason": f"{doc_name} is unavailable on {blocked_date} ({reason}). Reschedule proposed for {next_date} at {next_slot}. Awaiting patient confirmation.",
                            "assigned_staff_role": "Duty Clinical Coordinator",
                        }
                    ).execute()
                except Exception:
                    pass

                rebooked.append(
                    {
                        "appointment_id": str(a["appointment_id"]),
                        "patient_id": a.get("patient_id"),
                        "old_datetime": appt_dt,
                        "new_date": next_date,
                        "new_slot": next_slot,
                        "reason": reason,
                        "message": f"{doc_name} is unavailable on {blocked_date} due to {reason}. Reschedule suggested to {next_date} at {next_slot}. Awaiting patient confirmation.",
                    }
                )

    return rebooked


def verify_doctor_unavailability_in_supabase(client: Client, doctor_id: str, blocked_date: str) -> bool:
    """Verify that unavailability has been recorded in Supabase."""
    try:
        resp = (
            client.table("doctor_unavailability")
            .select("unavailability_id")
            .eq("doctor_id", doctor_id)
            .eq("blocked_date", blocked_date)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False


def unblock_doctor_slot_in_supabase(client: Client, unavailability_id: str) -> None:
    """Remove a previously placed unavailability block."""
    client.table("doctor_unavailability").delete().eq("unavailability_id", unavailability_id).execute()


def book_appointment_by_doctor(
    client: Client,
    doctor_id: str,
    patient_id: str,
    appointment_type: str,
    date_str: str,
    time_str: str,
    location: str,
    summary: str,
) -> dict[str, Any]:
    """Create a new appointment scheduled directly by a doctor."""
    try:
        dt_obj = datetime.strptime(f"{date_str} {time_str}", "%d %b %Y %I:%M %p")
        iso_dt = dt_obj.isoformat()
    except Exception:
        try:
            dt_obj = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")
            iso_dt = dt_obj.isoformat()
        except Exception:
            iso_dt = f"{date_str}T10:00:00"

    res = client.table("appointments").insert(
        {
            "doctor_id": doctor_id,
            "patient_id": patient_id,
            "appointment_type": appointment_type,
            "appointment_datetime": iso_dt,
            "status": "Confirmed",
            "scheduled_by_role": "Doctor",
            "location": location or "Room 304, OPD Wing B",
            "appointment_summary": summary or "Scheduled by physician.",
            "reminders_sent_count": 0,
        }
    ).execute()
    return res.data[0] if res.data else {}


def register_patient_and_book(
    client: Client,
    first_name: str,
    last_name: str,
    dob: str,
    gender: str,
    blood_type: str,
    phone: str,
    email: str,
    doctor_id: str,
    appointment_type: str,
    date_str: str,
    time_str: str,
) -> dict[str, Any]:
    """Register a new patient and instantly schedule their initial appointment."""
    p_res = client.table("patients").insert(
        {
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": dob or "1995-01-01",
            "gender": gender or "Other",
            "blood_type": blood_type or "O+",
            "contact_phone": phone or "+91 90000 00000",
            "contact_email": email or f"{first_name.lower()}@example.com",
            "primary_doctor_id": doctor_id,
            "patient_summary": "New patient registered via Doctor Portal.",
        }
    ).execute()

    new_pid = p_res.data[0]["patient_id"] if p_res.data else None
    if not new_pid:
        raise ValueError("Failed to create new patient")

    appt = book_appointment_by_doctor(
        client,
        doctor_id=doctor_id,
        patient_id=new_pid,
        appointment_type=appointment_type,
        date_str=date_str,
        time_str=time_str,
        location="Outpatient Clinic",
        summary="Initial consultation with newly registered patient.",
    )
    return {"patient_id": new_pid, "appointment": appt}


def reset_supabase_database(client: Client) -> None:
    """Wipe session mutations and restore the canonical 3-year baseline data in Supabase for all patients."""
    from tools.seed_data import (
        ALL_BASELINE_PATIENT_IDS,
        DOCTORS_BASELINE,
        PATIENTS_BASELINE,
        MEDICINES_BASELINE,
        ALL_BASELINE_APPTS,
        CONSULTATIONS_BASELINE,
        PRESCRIPTIONS_BASELINE,
        DIAGNOSTICS_BASELINE,
        DIAGNOSTICS_RESULTS_BASELINE,
        OPERATION_BASELINE,
        PAYMENT_BASELINE,
    )

    # Cleanly remove all old/pending appointments, doctor blocks, and related records
    for tbl, pk in [
        ("doctor_unavailability", "unavailability_id"),
        ("escalation_agent_data", "ticket_id"),
        ("diagnostics_results", "result_id"),
        ("diagnostics", "order_id"),
        ("prescription_details", "prescription_item_id"),
        ("consultations", "consultation_id"),
        ("operation", "operation_id"),
        ("payment_details", "payment_id"),
        ("appointments", "appointment_id"),
    ]:
        try:
            client.table(tbl).delete().neq(pk, "00000000-0000-0000-0000-000000000000").execute()
        except Exception:
            pass

    # Batch upsert baseline entities
    for tbl, data in [
        ("doctors", DOCTORS_BASELINE),
        ("patients", PATIENTS_BASELINE),
        ("medicines", MEDICINES_BASELINE),
        ("appointments", ALL_BASELINE_APPTS),
        ("consultations", CONSULTATIONS_BASELINE),
        ("prescription_details", PRESCRIPTIONS_BASELINE),
        ("diagnostics", DIAGNOSTICS_BASELINE),
        ("diagnostics_results", DIAGNOSTICS_RESULTS_BASELINE),
        ("operation", OPERATION_BASELINE),
        ("payment_details", PAYMENT_BASELINE),
    ]:
        try:
            client.table(tbl).upsert(data).execute()
        except Exception as e:
            print(f"Error upserting {tbl}: {e}")
