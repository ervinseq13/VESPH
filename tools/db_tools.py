"""Live Supabase database tools for the VESPH care workflow."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

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

    # Sort upcoming appointments chronologically ascending (next nearest first)
    upcoming_appts = [a for a in all_appts if a.get("status") not in ("Completed", "Cancelled")]
    upcoming_appts.sort(key=lambda x: str(x.get("datetime_raw") or ""))

    # Sort past appointments chronologically descending (most recent first)
    past_appts = [a for a in all_appts if a.get("status") in ("Completed", "Cancelled")]
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

        medications.append(
            {
                "id": str(p["prescription_item_id"]),
                "name": f"{brand} {dosage}".strip(),
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
    appt_summary_text = (
        f"Next appointment: {appointments[0]['type']} with {appointments[0]['doctor']} on {appointments[0]['date']} at {appointments[0]['time']} ({appointments[0]['status']})."
        if appointments
        else "No upcoming appointments scheduled."
    )

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

    payload: dict[str, Any] = {"status": status}
    if new_date and new_time:
        try:
            dt_obj = datetime.strptime(f"{new_date} {new_time}", "%d %b %Y %I:%M %p")
            payload["appointment_datetime"] = dt_obj.isoformat()
        except Exception:
            pass

    client.table("appointments").update(payload).eq("appointment_id", appointment_id).execute()


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
    doc_resp = client.table("doctors").select("*").eq("doctor_id", doctor_id).execute()
    doc = doc_resp.data[0] if doc_resp.data else {}

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
    blocked_slot: str | None,
    reason: str,
) -> list[dict[str, Any]]:
    """Mark doctor unavailable, identify conflicting patient appointments, and auto-rebook them."""
    is_full_day = not blocked_slot or blocked_slot.lower().strip() in ("all day", "full day")
    block_type = "full_day" if is_full_day else "timeslot"

    client.table("doctor_unavailability").insert(
        {
            "doctor_id": doctor_id,
            "block_type": block_type,
            "blocked_date": blocked_date,
            "blocked_slot": blocked_slot if not is_full_day else None,
            "reason": reason or "Doctor unavailable",
        }
    ).execute()

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

    fallback_schedule = [
        ("2026-10-23", "11:00 AM"),
        ("2026-10-23", "03:00 PM"),
        ("2026-10-24", "10:00 AM"),
        ("2026-10-24", "11:30 AM"),
        ("2026-10-26", "10:00 AM"),
        ("2026-10-26", "02:00 PM"),
    ]

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
                next_date, next_slot = fallback_schedule[min(fallback_idx, len(fallback_schedule) - 1)]
                fallback_idx += 1
                try:
                    new_dt = datetime.strptime(f"{next_date} {next_slot}", "%Y-%m-%d %I:%M %p").isoformat()
                except Exception:
                    new_dt = f"{next_date}T10:00:00"

                notice = f"Doctor was unavailable on {blocked_date} ({reason}). Automatically rebooked to {next_date} at {next_slot}."
                current_summary = a.get("appointment_summary") or ""
                updated_summary = f"{current_summary}\n[Notice]: {notice}".strip()

                client.table("appointments").update(
                    {
                        "appointment_datetime": new_dt,
                        "status": "Confirmed",
                        "appointment_summary": updated_summary,
                    }
                ).eq("appointment_id", a["appointment_id"]).execute()

                rebooked.append(
                    {
                        "appointment_id": str(a["appointment_id"]),
                        "patient_id": a.get("patient_id"),
                        "old_datetime": appt_dt,
                        "new_date": next_date,
                        "new_slot": next_slot,
                        "reason": reason,
                        "message": f"{doc_name} is unavailable on {blocked_date} due to {reason}. Your appointment has been automatically rebooked to {next_date} at {next_slot}.",
                    }
                )

    return rebooked


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

    patient_ids = [
        "22222222-2222-2222-2222-222222222222",  # Ananya Sharma
        "22222222-2222-2222-2222-222222222223",  # Rahul Verma
        "22222222-2222-2222-2222-222222222224",  # Priya Patel
        "22222222-2222-2222-2222-222222222225",  # Vikram Malhotra
        "22222222-2222-2222-2222-222222222226",  # Sunita Deshmukh
        "22222222-2222-2222-2222-222222222227",  # Rohan Gupta
        "22222222-2222-2222-2222-222222222228",  # Kavita Nair
    ]

    try:
        client.table("doctor_unavailability").delete().neq("unavailability_id", "00000000-0000-0000-0000-000000000000").execute()
    except Exception:
        pass

    for p_id_to_del in patient_ids:
        try:
            client.table("escalation_agent_data").delete().eq("patient_id", p_id_to_del).execute()
        except Exception:
            pass

        try:
            orders = client.table("diagnostics").select("order_id").eq("patient_id", p_id_to_del).execute().data or []
            for o in orders:
                client.table("diagnostics_results").delete().eq("order_id", o["order_id"]).execute()
        except Exception:
            pass

        for table_name in [
            "diagnostics",
            "prescription_details",
            "consultations",
            "operation",
            "payment_details",
            "appointments",
        ]:
            try:
                client.table(table_name).delete().eq("patient_id", p_id_to_del).execute()
            except Exception:
                pass

    pid = "22222222-2222-2222-2222-222222222222"
    pid2 = "22222222-2222-2222-2222-222222222223"
    pid3 = "22222222-2222-2222-2222-222222222224"
    pid4 = "22222222-2222-2222-2222-222222222225"
    pid5 = "22222222-2222-2222-2222-222222222226"
    pid6 = "22222222-2222-2222-2222-222222222227"
    pid7 = "22222222-2222-2222-2222-222222222228"

    # 2. Re-insert Doctors (Upsert)
    client.table("doctors").upsert([
        {
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "doctor_name": "Dr. Rhea Mehta",
            "qualifications": "MBBS, MS (General Surgery)",
            "department": "General Surgery",
            "room_no": "Room 304",
            "contact_phone": "+91 22 4000 1100",
            "contact_email": "dr.mehta@vesphcare.com",
            "is_active": True,
        },
        {
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "doctor_name": "Dr. Rajesh Kulkarni",
            "qualifications": "MBBS, MD (Pulmonary Medicine), FCCP",
            "department": "Pulmonology",
            "room_no": "Room 210",
            "contact_phone": "+91 22 4000 1210",
            "contact_email": "dr.kulkarni@vesphcare.com",
            "is_active": True,
        },
        {
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "doctor_name": "Dr. Sunita Rao",
            "qualifications": "MBBS, MD (Internal Medicine)",
            "department": "Internal Medicine",
            "room_no": "Room 105",
            "contact_phone": "+91 22 4000 1105",
            "contact_email": "dr.sunita.rao@vesphcare.com",
            "is_active": True,
        },
    ]).execute()

    # 3. Patients
    client.table("patients").upsert([
        {
            "patient_id": pid,
            "first_name": "Ananya",
            "last_name": "Iyer",
            "date_of_birth": "1994-06-15",
            "gender": "Female",
            "blood_type": "B+",
            "contact_phone": "+91 98765 43210",
            "contact_email": "ananya.iyer@example.com",
            "address": "Flat 402, Sea Breeze Apts, Bandra West, Mumbai 400050",
            "emergency_contact_name": "Karthik Iyer (Spouse)",
            "emergency_contact_phone": "+91 98765 43219",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Recovering well after laparoscopic appendectomy. Clean incisions, normal healing trajectory. Known mild asthma.",
            "created_at": "2026-10-08 10:00:00",
        },
        {
            "patient_id": pid2,
            "first_name": "Rahul",
            "last_name": "Verma",
            "date_of_birth": "1984-03-20",
            "gender": "Male",
            "blood_type": "O+",
            "contact_phone": "+91 98111 22334",
            "contact_email": "rahul.verma@example.com",
            "address": "12, Silver Oaks, Khar West, Mumbai 400052",
            "emergency_contact_name": "Kavita Verma (Spouse)",
            "emergency_contact_phone": "+91 98111 22330",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Moderate persistent asthma with seasonal trigger. Pre-operative workup for elective laparoscopic inguinal hernia repair.",
            "created_at": "2024-04-10 10:00:00",
        },
        {
            "patient_id": pid3,
            "first_name": "Priya",
            "last_name": "Patel",
            "date_of_birth": "1997-09-12",
            "gender": "Female",
            "blood_type": "A+",
            "contact_phone": "+91 98222 33445",
            "contact_email": "priya.patel@example.com",
            "address": "Penthouse 7B, Horizon Heights, Andheri West, Mumbai 400058",
            "emergency_contact_name": "Dev Patel (Brother)",
            "emergency_contact_phone": "+91 98222 33440",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Post-laparoscopic cholecystectomy Day 10. Digestive symptoms improving on low-fat nutrition and digestive enzymes.",
            "created_at": "2024-08-14 10:00:00",
        },
        {
            "patient_id": pid4,
            "first_name": "Vikram",
            "last_name": "Malhotra",
            "date_of_birth": "1978-05-18",
            "gender": "Male",
            "blood_type": "O+",
            "contact_phone": "+91 98333 44556",
            "contact_email": "vikram.malhotra@example.com",
            "address": "B-301, Palm Court, Juhu, Mumbai 400049",
            "emergency_contact_name": "Pooja Malhotra (Spouse)",
            "emergency_contact_phone": "+91 98333 44550",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Bilateral direct inguinal hernia. Elective laparoscopic repair planned. Pre-op bloods and cardiology clearance completed.",
            "created_at": "2026-09-15 10:00:00",
        },
        {
            "patient_id": pid5,
            "first_name": "Sunita",
            "last_name": "Deshmukh",
            "date_of_birth": "1970-11-24",
            "gender": "Female",
            "blood_type": "B+",
            "contact_phone": "+91 98444 55667",
            "contact_email": "sunita.deshmukh@example.com",
            "address": "Flat 15, Green Acres, Powai, Mumbai 400076",
            "emergency_contact_name": "Ajit Deshmukh (Spouse)",
            "emergency_contact_phone": "+91 98444 55660",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Post-laparoscopic cholecystectomy Day 5. Mild abdominal distension, surgical incisions clean and dry. Advancing to soft diet.",
            "created_at": "2026-10-02 11:30:00",
        },
        {
            "patient_id": pid6,
            "first_name": "Rohan",
            "last_name": "Gupta",
            "date_of_birth": "1991-08-05",
            "gender": "Male",
            "blood_type": "A-",
            "contact_phone": "+91 98555 66778",
            "contact_email": "rohan.gupta@example.com",
            "address": "402, Skyline Towers, Lower Parel, Mumbai 400013",
            "emergency_contact_name": "Meera Gupta (Mother)",
            "emergency_contact_phone": "+91 98555 66770",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Post-excision of back lipoma (5cm). Sutures intact, wound dressing clean. Healing without seroma or infection.",
            "created_at": "2026-10-05 09:00:00",
        },
        {
            "patient_id": pid7,
            "first_name": "Kavita",
            "last_name": "Nair",
            "date_of_birth": "1984-12-30",
            "gender": "Female",
            "blood_type": "AB+",
            "contact_phone": "+91 98666 77889",
            "contact_email": "kavita.nair@example.com",
            "address": "701, Marine Vista, Worli, Mumbai 400018",
            "emergency_contact_name": "Suresh Nair (Spouse)",
            "emergency_contact_phone": "+91 98666 77880",
            "primary_doctor_id": "11111111-1111-1111-1111-111111111111",
            "patient_summary": "Chronic right iliac fossa pain under investigation. Diagnostic laparoscopy advised after pelvic ultrasound evaluation.",
            "created_at": "2026-09-28 14:00:00",
        },
    ]).execute()

    # 4. Medicines
    client.table("medicines").upsert([
        {"medicine_id": "66666666-6666-6666-6666-666666666661", "brand_name": "Pantocid 40", "generic_name": "Pantoprazole Sodium", "dosage_form": "Tablet"},
        {"medicine_id": "66666666-6666-6666-6666-666666666662", "brand_name": "Dolo 650", "generic_name": "Paracetamol", "dosage_form": "Tablet"},
        {"medicine_id": "66666666-6666-6666-6666-666666666663", "brand_name": "Budecort 200 Inhaler", "generic_name": "Budesonide", "dosage_form": "Inhaler"},
        {"medicine_id": "66666666-6666-6666-6666-666666666664", "brand_name": "Montair 10", "generic_name": "Montelukast", "dosage_form": "Tablet"},
        {"medicine_id": "66666666-6666-6666-6666-666666666665", "brand_name": "Orofer XT", "generic_name": "Ferrous Ascorbate + Folic Acid", "dosage_form": "Tablet"},
        {"medicine_id": "66666666-6666-6666-6666-666666666666", "brand_name": "Shelcal 500", "generic_name": "Calcium + Vitamin D3", "dosage_form": "Tablet"},
    ]).execute()

    pid2 = "22222222-2222-2222-2222-222222222223"
    pid3 = "22222222-2222-2222-2222-222222222224"
    pid4 = "22222222-2222-2222-2222-222222222225"
    pid5 = "22222222-2222-2222-2222-222222222226"
    pid6 = "22222222-2222-2222-2222-222222222227"
    pid7 = "22222222-2222-2222-2222-222222222228"

    # 5. Appointments (Dr. Rhea Mehta full weekly schedule 18-24 Oct 2026 & history)
    client.table("appointments").insert([
        # Sunday 18 Oct 2026
        {
            "appointment_id": "33333333-3333-3333-3333-333333333333",
            "patient_id": pid2,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Consultation",
            "appointment_datetime": "2026-10-18 10:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Pre-operative hernia repair assessment and pre-anesthetic check.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333333335",
            "patient_id": pid3,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-18 15:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Post-cholecystectomy Day 10 progress check and suture review.",
        },
        # Monday 19 Oct 2026
        {
            "appointment_id": "33333333-3333-3333-3333-333333334001",
            "patient_id": pid4,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Consultation",
            "appointment_datetime": "2026-10-19 09:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Bilateral inguinal hernia pre-operative surgical assessment and ultrasound review.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334002",
            "patient_id": pid5,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-19 14:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Post-laparoscopic cholecystectomy Day 5 wound check and digestive tolerance review.",
        },
        # Tuesday 20 Oct 2026
        {
            "appointment_id": "33333333-3333-3333-3333-333333333332",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Diagnostic",
            "appointment_datetime": "2026-10-20 09:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Pending Confirmation",
            "location": "Pathology Lab, 1st Floor",
            "reminders_sent_count": 1,
            "appointment_summary": "Repeat Complete Blood Count (CBC) prior to surgical follow-up.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334003",
            "patient_id": pid6,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-20 11:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Post-lipoma excision wound inspection and dressing change.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334004",
            "patient_id": pid7,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Consultation",
            "appointment_datetime": "2026-10-20 16:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Diagnostic laparoscopy surgical evaluation for chronic right iliac fossa pain.",
        },
        # Wednesday 21 Oct 2026
        {
            "appointment_id": "33333333-3333-3333-3333-333333333334",
            "patient_id": pid2,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Diagnostic",
            "appointment_datetime": "2026-10-21 10:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "Radiology Ultrasound Room 2",
            "reminders_sent_count": 1,
            "appointment_summary": "Abdominal Ultrasound and lab follow-up for inguinal hernia evaluation.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334005",
            "patient_id": pid4,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Consultation",
            "appointment_datetime": "2026-10-21 14:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Pre-anesthesia review and laparoscopic mesh repair counseling.",
        },
        # Thursday 22 Oct 2026 (Explicitly 22nd October 2026)
        {
            "appointment_id": "33333333-3333-3333-3333-333333333331",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-22 11:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Pending Confirmation",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Post-op Day 14 surgical wound review and stitch removal assessment.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334006",
            "patient_id": pid5,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-22 15:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Post-op Day 8 suture removal and digestive enzyme plan review.",
        },
        # Friday 23 Oct 2026
        {
            "appointment_id": "33333333-3333-3333-3333-333333333336",
            "patient_id": pid3,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-23 10:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Diet advancement and digestive enzyme review.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334007",
            "patient_id": pid6,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2026-10-23 14:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Suture removal and silicon gel scar treatment guidance.",
        },
        # Saturday 24 Oct 2026
        {
            "appointment_id": "33333333-3333-3333-3333-333333334008",
            "patient_id": pid7,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Consultation",
            "appointment_datetime": "2026-10-24 10:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Pelvic ultrasound review and pre-admission workup for diagnostic laparoscopy.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333334009",
            "patient_id": pid4,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "appointment_type": "Consultation",
            "appointment_datetime": "2026-10-24 13:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Confirmed",
            "location": "OPD Wing B, Room 304",
            "reminders_sent_count": 1,
            "appointment_summary": "Pre-admission surgical briefing & bed allocation confirmation.",
        },
        # Past history for Ananya Sharma
        {
            "appointment_id": "33333333-3333-3333-3333-333333332502",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2025-12-08 16:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Completed",
            "location": "Chest & Allergy Clinic, Room 210",
            "reminders_sent_count": 1,
            "appointment_summary": "Pre-winter respiratory check. Peak flow review and cold season precautions.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333332501",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "appointment_type": "Consultation",
            "appointment_datetime": "2025-05-14 09:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Completed",
            "location": "Wellness Clinic, Room 105",
            "reminders_sent_count": 1,
            "appointment_summary": "Annual physical and follow-up post iron supplementation. Ferritin repeat.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333332402",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "appointment_type": "Consultation",
            "appointment_datetime": "2024-11-15 14:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Completed",
            "location": "Wellness Clinic, Room 105",
            "reminders_sent_count": 1,
            "appointment_summary": "Routine health checkup. Investigation of mild fatigue; iron panel ordered.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333332401",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "appointment_type": "FollowUp",
            "appointment_datetime": "2024-03-22 11:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Completed",
            "location": "Chest & Allergy Clinic, Room 210",
            "reminders_sent_count": 1,
            "appointment_summary": "Asthma maintenance checkup. Assessment of Budecort inhaler compliance.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333332302",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "appointment_type": "Consultation",
            "appointment_datetime": "2023-10-18 15:30:00",
            "scheduled_by_role": "Doctor",
            "status": "Completed",
            "location": "Chest & Allergy Clinic, Room 210",
            "reminders_sent_count": 2,
            "appointment_summary": "Evaluation of post-monsoon dry cough and nocturnal wheezing. Spirometry evaluation.",
        },
        {
            "appointment_id": "33333333-3333-3333-3333-333333332301",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "appointment_type": "Consultation",
            "appointment_datetime": "2023-04-12 10:00:00",
            "scheduled_by_role": "Doctor",
            "status": "Completed",
            "location": "Wellness Clinic, Room 105",
            "reminders_sent_count": 2,
            "appointment_summary": "Annual executive health checkup and comprehensive metabolic screening.",
        },
    ]).execute()

    # 6. Consultations
    client.table("consultations").insert([
        {
            "consultation_id": "55555555-5555-5555-5555-555555555555",
            "appointment_id": "33333333-3333-3333-3333-333333333331",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Mild post-op twinge at trocar site, dry cough occasionally.",
            "diagnosis": "Post-laparoscopic appendectomy recovery - uneventful course.",
            "treatment_plan": "Keep wound dry, light ambulation, maintain hydration, asthma inhaler continued.",
            "bp_systolic": 118,
            "bp_diastolic": 76,
            "sugar_reading": 96,
            "height_cm": 165,
            "weight_kg": 58.5,
            "consultation_summary": "Patient is ambulatory and tolerating normal soft diet. Wound sites dry with no erythema or discharge.",
            "recommended_consultation": "Surgical Follow-up in OPD",
            "recommended_consultation_date": "2026-10-22",
            "recommended_diagnostics": "Repeat CBC",
            "recommended_test_category": "Blood Work",
            "recommended_diagnostics_date": "2026-10-20",
            "recommended_prescription": "Pantoprazole 40mg and Paracetamol 650mg SOS",
            "recommended_prescription_date": "2026-10-10",
            "created_at": "2026-10-10 11:00:00",
        },
        # Consultation for Rahul Verma
        {
            "consultation_id": "55555555-5555-5555-5555-555555555556",
            "appointment_id": "33333333-3333-3333-3333-333333333333",
            "patient_id": pid2,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Intermittent right groin bulge and mild discomfort upon lifting.",
            "diagnosis": "Right reducible indirect inguinal hernia.",
            "treatment_plan": "Scheduled elective laparoscopic inguinal hernia repair (TEP). Pre-op bloods and USG ordered.",
            "bp_systolic": 124,
            "bp_diastolic": 80,
            "sugar_reading": 104,
            "height_cm": 172,
            "weight_kg": 74.0,
            "consultation_summary": "Right groin mass reducible without tenderness. Ultrasound confirms hernia sac. Pre-op clearance granted.",
            "created_at": "2026-10-18 11:00:00",
        },
        # Consultation for Priya Patel
        {
            "consultation_id": "55555555-5555-5555-5555-555555555557",
            "appointment_id": "33333333-3333-3333-3333-333333333335",
            "patient_id": pid3,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Recovering well from gallbladder surgery, mild abdominal bloating after oily foods.",
            "diagnosis": "Post-laparoscopic cholecystectomy recovery - stable.",
            "treatment_plan": "Low fat diet, digestive enzymes with heavy meals, gradual walking.",
            "bp_systolic": 120,
            "bp_diastolic": 78,
            "sugar_reading": 98,
            "height_cm": 160,
            "weight_kg": 62.0,
            "consultation_summary": "Surgical ports healing cleanly. No jaundice or RUQ tenderness. Advised continuing low-fat nutrition.",
            "created_at": "2026-10-18 15:30:00",
        },
        # Consultation for Vikram Malhotra
        {
            "consultation_id": "55555555-5555-5555-5555-555555555558",
            "appointment_id": "33333333-3333-3333-3333-333333334001",
            "patient_id": pid4,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Bilateral groin bulge with standing, ache in lower abdomen after lifting.",
            "diagnosis": "Bilateral direct inguinal hernia without obstruction.",
            "treatment_plan": "Pre-op clearance obtained. Elective laparoscopic totally extraperitoneal (TEP) mesh repair scheduled.",
            "bp_systolic": 126,
            "bp_diastolic": 82,
            "sugar_reading": 108,
            "height_cm": 175,
            "weight_kg": 78.0,
            "consultation_summary": "Bilateral direct defects palpable on coughing. Cardio clearance normal. Advised pre-admission on 24 Oct.",
            "created_at": "2026-10-14 11:30:00",
        },
        # Consultation for Sunita Deshmukh
        {
            "consultation_id": "55555555-5555-5555-5555-555555555559",
            "appointment_id": "33333333-3333-3333-3333-333333334002",
            "patient_id": pid5,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Post-cholecystectomy Day 5, mild dyspepsia and bloating, port sites dry.",
            "diagnosis": "Post-laparoscopic cholecystectomy - normal recovery trajectory.",
            "treatment_plan": "Low-fat, high-fiber meals in small portions. Continue PPI and antacid. Suture removal on 22 Oct.",
            "bp_systolic": 130,
            "bp_diastolic": 84,
            "sugar_reading": 112,
            "height_cm": 158,
            "weight_kg": 65.0,
            "consultation_summary": "Abdomen soft with mild periumbilical tenderness. Subcuticular stitches clean. Recovery on track.",
            "created_at": "2026-10-15 14:00:00",
        },
        # Consultation for Rohan Gupta
        {
            "consultation_id": "55555555-5555-5555-5555-555555555560",
            "appointment_id": "33333333-3333-3333-3333-333333334003",
            "patient_id": pid6,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Post-excision dorsal lipoma, surgical wound dry, no fever.",
            "diagnosis": "Post-surgical excision benign lipoma - primary healing.",
            "treatment_plan": "Keep waterproof dressing dry. Suture removal scheduled for 23 Oct. Avoid intense upper body gym work.",
            "bp_systolic": 120,
            "bp_diastolic": 78,
            "sugar_reading": 95,
            "height_cm": 180,
            "weight_kg": 72.0,
            "consultation_summary": "Excision margin 5cm clean. No hematoma or seroma accumulation. Healing by primary intention.",
            "created_at": "2026-10-16 10:30:00",
        },
        # Consultation for Kavita Nair
        {
            "consultation_id": "55555555-5555-5555-5555-555555555561",
            "appointment_id": "33333333-3333-3333-3333-333333334004",
            "patient_id": pid7,
            "doctor_id": "11111111-1111-1111-1111-111111111111",
            "symptoms": "Recurrent dull aching right iliac fossa discomfort for 6 months, worsened with activity.",
            "diagnosis": "Chronic right lower quadrant pain, rule out subacute appendiceal or adnexal pathology.",
            "treatment_plan": "High-resolution pelvic & abdominal ultrasound. Scheduled diagnostic laparoscopy workup.",
            "bp_systolic": 115,
            "bp_diastolic": 74,
            "sugar_reading": 92,
            "height_cm": 162,
            "weight_kg": 56.0,
            "consultation_summary": "Localized tenderness over right iliac fossa without guarding or rebound. Recommended diagnostic laparoscopy.",
            "created_at": "2026-10-16 16:30:00",
        },
        {
            "consultation_id": "55555555-5555-5555-5555-555555552502",
            "appointment_id": "33333333-3333-3333-3333-333333332502",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "symptoms": "Routine check before winter weather. Occasional mild cough outdoors.",
            "diagnosis": "Mild asthma, stable on maintenance.",
            "treatment_plan": "Reinforce inhaler use 15 mins before cold air exposure. Avoid air pollution hotspots.",
            "bp_systolic": 118,
            "bp_diastolic": 75,
            "sugar_reading": 95,
            "height_cm": 165,
            "weight_kg": 58.5,
            "consultation_summary": "Lungs clear bilaterally. Peak flow rate steady at 430 L/min. Patient well educated on asthma triggers.",
            "created_at": "2025-12-08 16:30:00",
        },
        {
            "consultation_id": "55555555-5555-5555-5555-555555552501",
            "appointment_id": "33333333-3333-3333-3333-333333332501",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "symptoms": "Feeling energetic and well. Fatigue fully resolved.",
            "diagnosis": "Iron deficiency resolved. Good health status.",
            "treatment_plan": "Discontinue daily iron; maintain balanced dietary intake. Continue asthma maintenance.",
            "bp_systolic": 116,
            "bp_diastolic": 74,
            "sugar_reading": 91,
            "height_cm": 165,
            "weight_kg": 58.2,
            "consultation_summary": "Pallor absent. Repeat hemoglobin 13.2 g/dL, Ferritin 46 ng/mL (normalized).",
            "created_at": "2025-05-14 10:00:00",
        },
        {
            "consultation_id": "55555555-5555-5555-5555-555555552402",
            "appointment_id": "33333333-3333-3333-3333-333333332402",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "symptoms": "Generalized mild fatigue, no fever or respiratory symptoms.",
            "diagnosis": "Mild iron deficiency anemia (latent stage).",
            "treatment_plan": "Oral ferrous ascorbate 100mg with Vitamin C once daily for 60 days. Dietary iron counseling provided.",
            "bp_systolic": 114,
            "bp_diastolic": 72,
            "sugar_reading": 93,
            "height_cm": 165,
            "weight_kg": 58.0,
            "consultation_summary": "Mild conjunctival pallor noted. Systemic exam unremarkable. Serum ferritin level low at 18 ng/mL.",
            "created_at": "2024-11-15 14:30:00",
        },
        {
            "consultation_id": "55555555-5555-5555-5555-555555552401",
            "appointment_id": "33333333-3333-3333-3333-333333332401",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "symptoms": "Much improved on Budecort. No daytime breathlessness or night waking.",
            "diagnosis": "Mild allergic asthma - well controlled.",
            "treatment_plan": "Continue Budesonide 200mcg 1-2 puffs daily as maintenance. Ensure mouth rinsing after inhalation.",
            "bp_systolic": 118,
            "bp_diastolic": 75,
            "sugar_reading": 94,
            "height_cm": 165,
            "weight_kg": 58.0,
            "consultation_summary": "Chest clear. Peak expiratory flow rate 420 L/min (>85% predicted). Excellent compliance with inhaler.",
            "created_at": "2024-03-22 11:30:00",
        },
        {
            "consultation_id": "55555555-5555-5555-5555-555555552302",
            "appointment_id": "33333333-3333-3333-3333-333333332302",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111112",
            "symptoms": "Occasional dry cough, mild wheezing at night triggered by dust and dampness.",
            "diagnosis": "Mild persistent allergic asthma.",
            "treatment_plan": "Prescribed Budesonide 200mcg inhaler (2 puffs twice daily). Advised allergen avoidance.",
            "bp_systolic": 118,
            "bp_diastolic": 76,
            "sugar_reading": 90,
            "height_cm": 165,
            "weight_kg": 57.5,
            "consultation_summary": "Bilateral expiratory wheezing heard on forced expiration. Spirometry confirms reversible airflow obstruction.",
            "created_at": "2023-10-18 16:00:00",
        },
        {
            "consultation_id": "55555555-5555-5555-5555-555555552301",
            "appointment_id": "33333333-3333-3333-3333-333333332301",
            "patient_id": pid,
            "doctor_id": "11111111-1111-1111-1111-111111111113",
            "symptoms": "No acute complaints. Annual physical examination requested.",
            "diagnosis": "Routine preventive health check - healthy adult female.",
            "treatment_plan": "Maintain balanced diet, regular aerobic exercise 150 mins/week, adequate hydration.",
            "bp_systolic": 116,
            "bp_diastolic": 74,
            "sugar_reading": 92,
            "height_cm": 165,
            "weight_kg": 57.0,
            "consultation_summary": "Vitals optimal. Heart sounds normal (S1, S2), lungs clear bilaterally. Routine metabolic profile ordered.",
            "created_at": "2023-04-12 10:30:00",
        },
    ]).execute()

    # 7. Prescriptions with meal_timing
    client.table("prescription_details").insert([
        # Ananya Sharma's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666671",
            "consultation_id": "55555555-5555-5555-5555-555555555555",
            "patient_id": pid,
            "medicine_id": "66666666-6666-6666-6666-666666666661",
            "dosage": "40 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 7,
            "start_date": "2026-10-10",
            "is_taken": True,
            "refill_needed": False,
            "meal_timing": "breakfast",
            "instructions": "Take 1 tablet every morning on empty stomach 30 mins before breakfast.",
        },
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666672",
            "consultation_id": "55555555-5555-5555-5555-555555555555",
            "patient_id": pid,
            "medicine_id": "66666666-6666-6666-6666-666666666662",
            "dosage": "650 mg",
            "frequency_per_day": "As needed (SOS)",
            "duration_days": 5,
            "start_date": "2026-10-10",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "lunch",
            "instructions": "Take only after lunch if having pain or discomfort. Do not exceed 3 tablets in 24 hours.",
        },
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666673",
            "consultation_id": "55555555-5555-5555-5555-555555555555",
            "patient_id": pid,
            "medicine_id": "66666666-6666-6666-6666-666666666663",
            "dosage": "200 mcg",
            "frequency_per_day": "2 times daily",
            "duration_days": 30,
            "start_date": "2026-10-10",
            "is_taken": True,
            "refill_needed": False,
            "meal_timing": "dinner",
            "instructions": "Rinse mouth thoroughly with water after inhalation. Take after dinner.",
        },
        # Rahul Verma's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666674",
            "consultation_id": "55555555-5555-5555-5555-555555555556",
            "patient_id": pid2,
            "medicine_id": "66666666-6666-6666-6666-666666666661",
            "dosage": "40 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 14,
            "start_date": "2026-10-18",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "breakfast",
            "instructions": "Take 1 tablet in the morning before breakfast for gastric protection.",
        },
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666675",
            "consultation_id": "55555555-5555-5555-5555-555555555556",
            "patient_id": pid2,
            "medicine_id": "66666666-6666-6666-6666-666666666662",
            "dosage": "650 mg",
            "frequency_per_day": "As needed (SOS)",
            "duration_days": 7,
            "start_date": "2026-10-18",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "dinner",
            "instructions": "Take after dinner only if required for pain.",
        },
        # Priya Patel's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666676",
            "consultation_id": "55555555-5555-5555-5555-555555555557",
            "patient_id": pid3,
            "medicine_id": "66666666-6666-6666-6666-666666666666",
            "dosage": "500 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 30,
            "start_date": "2026-10-18",
            "is_taken": True,
            "refill_needed": False,
            "meal_timing": "breakfast",
            "instructions": "Take with breakfast.",
        },
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666677",
            "consultation_id": "55555555-5555-5555-5555-555555555557",
            "patient_id": pid3,
            "medicine_id": "66666666-6666-6666-6666-666666666661",
            "dosage": "40 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 10,
            "start_date": "2026-10-18",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "lunch",
            "instructions": "Take before lunch.",
        },
        # Vikram Malhotra's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666678",
            "consultation_id": "55555555-5555-5555-5555-555555555558",
            "patient_id": pid4,
            "medicine_id": "66666666-6666-6666-6666-666666666661",
            "dosage": "40 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 14,
            "start_date": "2026-10-18",
            "is_taken": True,
            "refill_needed": False,
            "meal_timing": "breakfast",
            "instructions": "Take before breakfast.",
        },
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666679",
            "consultation_id": "55555555-5555-5555-5555-555555555558",
            "patient_id": pid4,
            "medicine_id": "66666666-6666-6666-6666-666666666662",
            "dosage": "650 mg",
            "frequency_per_day": "As needed (SOS)",
            "duration_days": 7,
            "start_date": "2026-10-18",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "dinner",
            "instructions": "Take after dinner for groin ache if needed.",
        },
        # Sunita Deshmukh's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666680",
            "consultation_id": "55555555-5555-5555-5555-555555555559",
            "patient_id": pid5,
            "medicine_id": "66666666-6666-6666-6666-666666666661",
            "dosage": "40 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 10,
            "start_date": "2026-10-18",
            "is_taken": True,
            "refill_needed": False,
            "meal_timing": "breakfast",
            "instructions": "Take 30 mins before breakfast.",
        },
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666681",
            "consultation_id": "55555555-5555-5555-5555-555555555559",
            "patient_id": pid5,
            "medicine_id": "66666666-6666-6666-6666-666666666666",
            "dosage": "500 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 30,
            "start_date": "2026-10-18",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "lunch",
            "instructions": "Take with lunch.",
        },
        # Rohan Gupta's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666682",
            "consultation_id": "55555555-5555-5555-5555-555555555560",
            "patient_id": pid6,
            "medicine_id": "66666666-6666-6666-6666-666666666662",
            "dosage": "650 mg",
            "frequency_per_day": "SOS",
            "duration_days": 5,
            "start_date": "2026-10-18",
            "is_taken": False,
            "refill_needed": False,
            "meal_timing": "dinner",
            "instructions": "Take after dinner if wound discomfort arises.",
        },
        # Kavita Nair's medications
        {
            "prescription_item_id": "66666666-6666-6666-6666-666666666683",
            "consultation_id": "55555555-5555-5555-5555-555555555561",
            "patient_id": pid7,
            "medicine_id": "66666666-6666-6666-6666-666666666661",
            "dosage": "40 mg",
            "frequency_per_day": "1 time daily",
            "duration_days": 14,
            "start_date": "2026-10-18",
            "is_taken": True,
            "refill_needed": False,
            "meal_timing": "breakfast",
            "instructions": "Take before breakfast.",
        },
    ]).execute()

    # 8. Diagnostics & Results
    client.table("diagnostics").insert([
        {"order_id": "77777777-7777-7777-7777-777777777771", "appointment_id": "33333333-3333-3333-3333-333333333331", "consultation_id": "55555555-5555-5555-5555-555555555555", "patient_id": pid, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-16 08:30:00"},
        {"order_id": "77777777-7777-7777-7777-777777772401", "appointment_id": "33333333-3333-3333-3333-333333332402", "consultation_id": "55555555-5555-5555-5555-555555552402", "patient_id": pid, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111113", "order_status": "Ready", "order_datetime": "2024-11-15 15:00:00"},
        {"order_id": "77777777-7777-7777-7777-777777772302", "appointment_id": "33333333-3333-3333-3333-333333332302", "consultation_id": "55555555-5555-5555-5555-555555552302", "patient_id": pid, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111112", "order_status": "Ready", "order_datetime": "2023-10-18 16:30:00"},
        {"order_id": "77777777-7777-7777-7777-777777772301", "appointment_id": "33333333-3333-3333-3333-333333332301", "consultation_id": "55555555-5555-5555-5555-555555552301", "patient_id": pid, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111113", "order_status": "Ready", "order_datetime": "2023-04-12 11:00:00"},
        {"order_id": "77777777-7777-7777-7777-777777772602", "appointment_id": "33333333-3333-3333-3333-333333333333", "consultation_id": "55555555-5555-5555-5555-555555555556", "patient_id": pid2, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-18 11:30:00"},
        {"order_id": "77777777-7777-7777-7777-777777772603", "appointment_id": "33333333-3333-3333-3333-333333333335", "consultation_id": "55555555-5555-5555-5555-555555555557", "patient_id": pid3, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-18 16:00:00"},
        {"order_id": "77777777-7777-7777-7777-777777772604", "appointment_id": "33333333-3333-3333-3333-333333334001", "consultation_id": "55555555-5555-5555-5555-555555555558", "patient_id": pid4, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-14 12:00:00"},
        {"order_id": "77777777-7777-7777-7777-777777772605", "appointment_id": "33333333-3333-3333-3333-333333334002", "consultation_id": "55555555-5555-5555-5555-555555555559", "patient_id": pid5, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-15 15:00:00"},
        {"order_id": "77777777-7777-7777-7777-777777772606", "appointment_id": "33333333-3333-3333-3333-333333334003", "consultation_id": "55555555-5555-5555-5555-555555555560", "patient_id": pid6, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-16 11:00:00"},
        {"order_id": "77777777-7777-7777-7777-777777772607", "appointment_id": "33333333-3333-3333-3333-333333334004", "consultation_id": "55555555-5555-5555-5555-555555555561", "patient_id": pid7, "ordered_by_doctor_id": "11111111-1111-1111-1111-111111111111", "order_status": "Ready", "order_datetime": "2026-10-16 17:00:00"},
    ]).execute()

    client.table("diagnostics_results").insert([
        {"result_id": "77777777-7777-7777-7777-777777777781", "order_id": "77777777-7777-7777-7777-777777777771", "test_category": "Blood Work", "test_name": "Complete Blood Count (CBC)", "result_value": "10.4 x10^3/uL", "reference_range": "4.5 - 11.0 x10^3/uL", "result_summary": "White blood count is 10.4 x10^3/uL, within normal recovery range. Trending down from post-op day 1 (14.2).", "report_file_url": "https://reports.vesphcare.com/lab/cbc-16oct.pdf", "result_datetime": "2026-10-16 12:00:00"},
        {"result_id": "77777777-7777-7777-7777-777777777782", "order_id": "77777777-7777-7777-7777-777777777771", "test_category": "Specialized", "test_name": "Appendix Histopathology", "result_value": "Acute appendicitis confirmed", "reference_range": "Normal lymphoid appendix", "result_summary": "Specimen shows acute transmural inflammation consistent with uncomplicated acute appendicitis. Margins clear.", "report_file_url": "https://reports.vesphcare.com/lab/histo-10oct.pdf", "result_datetime": "2026-10-10 16:00:00"},
        {"result_id": "77777777-7777-7777-7777-777777772481", "order_id": "77777777-7777-7777-7777-777777772401", "test_category": "Blood Work", "test_name": "Serum Ferritin & Iron Panel", "result_value": "Ferritin 18 ng/mL", "reference_range": "20 - 200 ng/mL", "result_summary": "Serum Ferritin is 18 ng/mL, indicating mild iron depletion. Serum Iron: 54 ug/dL, Total Iron Binding Capacity: 380 ug/dL.", "report_file_url": "https://reports.vesphcare.com/lab/iron-nov2024.pdf", "result_datetime": "2024-11-15 17:30:00"},
        {"result_id": "77777777-7777-7777-7777-777777772382", "order_id": "77777777-7777-7777-7777-777777772302", "test_category": "Specialized", "test_name": "Spirometry Pulmonary Function", "result_value": "FEV1/FVC 78% (Pre) -> 86% (Post)", "reference_range": "> 80%", "result_summary": "Pre-bronchodilator FEV1 was 78%. Improved by 14% post-albuterol inhalation, confirming reversible airway hyper-responsiveness.", "report_file_url": "https://reports.vesphcare.com/lab/spiro-oct2023.pdf", "result_datetime": "2023-10-18 17:00:00"},
        {"result_id": "77777777-7777-7777-7777-777777772381", "order_id": "77777777-7777-7777-7777-777777772301", "test_category": "Blood Work", "test_name": "Lipid & Metabolic Profile", "result_value": "Cholesterol 174 mg/dL", "reference_range": "< 200 mg/dL", "result_summary": "Total Cholesterol: 174 mg/dL, HDL: 52 mg/dL, Triglycerides: 110 mg/dL. All lipid fractions within optimal cardiovascular range.", "report_file_url": "https://reports.vesphcare.com/lab/lipid-apr2023.pdf", "result_datetime": "2023-04-12 14:00:00"},
        {"result_id": "77777777-7777-7777-7777-777777772681", "order_id": "77777777-7777-7777-7777-777777772602", "test_category": "Imaging", "test_name": "Right Groin Ultrasound", "result_value": "Direct/Indirect Inguinal Defect 14mm", "reference_range": "Intact inguinal floor", "result_summary": "Defect in deep inguinal ring measuring 14mm with herniation of mesenteric fat. No bowel strangulation.", "report_file_url": "https://reports.vesphcare.com/lab/usg-groin.pdf", "result_datetime": "2026-10-18 12:15:00"},
        {"result_id": "77777777-7777-7777-7777-777777772682", "order_id": "77777777-7777-7777-7777-777777772603", "test_category": "Blood Work", "test_name": "Liver Function Tests (LFT)", "result_value": "Bilirubin 0.8 mg/dL, ALT 24 U/L", "reference_range": "Bilirubin < 1.2 mg/dL, ALT < 35 U/L", "result_summary": "Normal post-cholecystectomy hepatic enzymes. Total Bilirubin 0.8 mg/dL, Alkaline Phosphatase 82 U/L.", "report_file_url": "https://reports.vesphcare.com/lab/lft-priya.pdf", "result_datetime": "2026-10-18 16:45:00"},
        {"result_id": "77777777-7777-7777-7777-777777772683", "order_id": "77777777-7777-7777-7777-777777772604", "test_category": "Imaging", "test_name": "Bilateral Inguinal Ultrasound", "result_value": "Bilateral Direct Inguinal Defect (R: 16mm, L: 14mm)", "reference_range": "Normal intact inguinal rings", "result_summary": "Bilateral direct inguinal hernia defects with omental content. No strangulation.", "report_file_url": "https://reports.vesphcare.com/lab/usg-vikram.pdf", "result_datetime": "2026-10-14 14:00:00"},
        {"result_id": "77777777-7777-7777-7777-777777772684", "order_id": "77777777-7777-7777-7777-777777772605", "test_category": "Blood Work", "test_name": "Serum Amylase & Lipase", "result_value": "Amylase 58 U/L, Lipase 32 U/L", "reference_range": "Amylase < 100 U/L, Lipase < 60 U/L", "result_summary": "Pancreatic and hepatobiliary enzymes within normal physiological limits.", "report_file_url": "https://reports.vesphcare.com/lab/enzymes-sunita.pdf", "result_datetime": "2026-10-15 17:00:00"},
        {"result_id": "77777777-7777-7777-7777-777777772685", "order_id": "77777777-7777-7777-7777-777777772606", "test_category": "Specialized", "test_name": "Lipoma Histopathology Report", "result_value": "Mature fibrolipoma, completely excised", "reference_range": "Benign adipose tissue", "result_summary": "Lobules of mature adipocytes with fibrous septa. Resection margins completely clear.", "report_file_url": "https://reports.vesphcare.com/lab/histo-rohan.pdf", "result_datetime": "2026-10-16 13:30:00"},
        {"result_id": "77777777-7777-7777-7777-777777772686", "order_id": "77777777-7777-7777-7777-777777772607", "test_category": "Imaging", "test_name": "Pelvic & Lower Abdomen Ultrasound", "result_value": "Minimal free fluid in POD, thickened appendiceal tip 6.5mm", "reference_range": "Normal pelvic viscera", "result_summary": "Trace fluid in pouch of Douglas. Mildly non-compressible tip of appendix. Diagnostic laparoscopy recommended.", "report_file_url": "https://reports.vesphcare.com/lab/usg-kavita.pdf", "result_datetime": "2026-10-16 18:30:00"},
    ]).execute()

    # 9. Operation
    client.table("operation").insert({
        "operation_id": "44444444-4444-4444-4444-444444444444",
        "patient_id": pid,
        "lead_surgeon_id": "11111111-1111-1111-1111-111111111111",
        "operation_name": "Laparoscopic Appendectomy (3-port)",
        "operation_status": "Completed",
        "pre_op_summary": "Acute right lower quadrant pain with ultrasound showing inflamed appendix measuring 9mm. Anesthesia clearance obtained.",
        "post_op_summary": "Successful 3-port laparoscopic appendectomy. Appendix inflamed but unperforated. Minimal blood loss (<20ml). Trocar sites closed with absorbable sutures.",
        "discharge_summary": "Discharged in stable condition. Vital signs stable. Advised soft diet for 48h, avoid heavy lifting (>5kg) for 3 weeks. Follow up on 22 Oct for surgical review.",
        "scheduled_start_time": "2026-10-08 14:00:00",
        "actual_end_time": "2026-10-08 15:45:00",
    }).execute()

    # 10. Payment
    client.table("payment_details").insert({
        "payment_id": "88888888-8888-8888-8888-888888888881",
        "patient_id": pid,
        "billing_amount": 48500.00,
        "billing_status": "Paid",
        "payment_method": "Cashless Insurance TPA",
        "transaction_reference": "TPA-HDFC-VESPH-2026-1008",
        "billing_datetime": "2026-10-09 11:30:00",
    }).execute()
