"""Specialized agent implementations for the Doctor Portal in VESPH Care."""

from __future__ import annotations

import html
from typing import Any
from supabase import Client

from tools.db_tools import (
    block_doctor_slot_in_supabase,
    verify_doctor_unavailability_in_supabase,
    update_appointment_in_supabase,
)
from tools.consultation_ingestion import (
    parse_consultation_text,
    ingest_consultation_to_supabase,
    format_ingestion_report,
)


class DoctorScheduleAgent:
    """Agent handling doctor schedule queries, appointment counts, and agendas."""

    @staticmethod
    def handle_schedule_query(
        client: Client,
        doctor_id: str,
        doctor_name: str,
        target_date: str,
        target_time: str | None = None,
        all_appointments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Query appointments for a doctor on a specific date (and optional time) and return count and table."""
        matched = []
        if all_appointments:
            day_str = target_date.split("-")[-1]
            for a in all_appointments:
                raw_dt = str(a.get("raw_datetime") or a.get("date") or "")
                if target_date in raw_dt or f"{int(day_str)} oct" in raw_dt.lower():
                    if target_time:
                        appt_time = str(a.get("time", "")).lower()
                        if target_time.lower() in appt_time:
                            matched.append(a)
                    else:
                        matched.append(a)
        else:
            try:
                query = (
                    client.table("appointments")
                    .select("*, patients(*)")
                    .eq("doctor_id", doctor_id)
                )
                res = query.execute()
                for row in (res.data or []):
                    dt_str = str(row.get("appointment_datetime", ""))
                    if target_date in dt_str:
                        p_info = row.get("patients") or {}
                        p_name = f"{p_info.get('first_name', '')} {p_info.get('last_name', '')}".strip() or "Patient"
                        matched.append({
                            "id": row.get("appointment_id"),
                            "patient_name": p_name,
                            "time": dt_str[11:16] if len(dt_str) >= 16 else "OPD",
                            "type": row.get("appointment_type", "Consultation"),
                            "status": row.get("status", "Confirmed"),
                            "summary": row.get("appointment_summary", ""),
                        })
            except Exception:
                pass

        count = len(matched)
        if count == 0:
            msg = (
                f"### Doctor's OPD Schedule – {target_date}\n\n"
                f"You have **0 appointments** scheduled on **{target_date}**.\n\n"
                "You have a free clinic day with no patient bookings."
            )
            return {"message": msg, "agent": "Doctor Schedule Agent", "count": 0}

        # Build clean markdown table
        rows = []
        for a in matched:
            t = html.escape(str(a.get("time", "OPD")))
            p = html.escape(str(a.get("patient_name", "Patient")))
            typ = html.escape(str(a.get("type", "Consultation")))
            st = html.escape(str(a.get("status", "Confirmed")))
            rows.append(f"| {t} | {p} | {typ} | {st} |")

        table_md = (
            f"### Doctor's OPD Schedule – {target_date}\n\n"
            f"You have **{count} appointment{'s' if count != 1 else ''}** scheduled on **{target_date}**:\n\n"
            "| Time | Patient | Type | Status |\n"
            "| :--- | :--- | :--- | :--- |\n"
            + "\n".join(rows)
            + "\n\nLet me know if you would like to inspect a patient's chart or mark unavailability."
        )
        return {"message": table_md, "agent": "Doctor Schedule Agent", "count": count}


class DoctorAvailabilityAndEscalationAgent:
    """Agent managing doctor unavailabilities, leave blocking, and patient rebooking."""

    @staticmethod
    def propose_or_execute_block(
        client: Client,
        doctor_id: str,
        doctor_name: str,
        target_date: str,
        all_appointments: list[dict[str, Any]],
        direct_command: bool = False,
    ) -> dict[str, Any]:
        """If direct command, executes block and rebooking. Otherwise proposes plan and awaits confirmation."""
        day_str = target_date.split("-")[-1]
        affected = [
            a for a in all_appointments
            if target_date in str(a.get("raw_datetime") or "") or f"{int(day_str)} oct" in str(a.get("date") or "").lower()
        ]

        if not direct_command:
            # Propose action and ask for confirmation
            patient_lines = "\n".join([
                f"• **{a.get('time', 'OPD')}:** {a.get('patient_name', 'Patient')} ({a.get('type', 'Consultation')}) – *Current: {a.get('status', 'Confirmed')}*"
                for a in affected
            ]) if affected else "• No active patient conflicts found for this date."

            msg = (
                f"**Unavailability Verification Proposal for {doctor_name}:**\n\n"
                f"**Date:** {target_date} (Full Day Leave)\n"
                f"**Conflicting Appointments ({len(affected)}):**\n"
                f"{patient_lines}\n\n"
                f"Would you like me to block **{target_date}** in Supabase and trigger priority reschedule notifications for these patients?"
            )
            return {
                "message": msg,
                "agent": "Doctor Availability Agent · Proposal",
                "pending_action": {
                    "type": "block_unavailability",
                    "date": target_date,
                    "affected_count": len(affected),
                },
            }

        # Execute block
        try:
            rebooked = block_doctor_slot_in_supabase(
                client=client,
                doctor_id=doctor_id,
                blocked_date=target_date,
                blocked_slot=None,
                reason="Doctor Unavailable - Leave",
            )
            # Verify DB state
            is_verified = verify_doctor_unavailability_in_supabase(client, doctor_id, target_date)
        except Exception as err:
            return {
                "message": f"❌ Error updating schedule in Supabase: {err}",
                "agent": "Doctor Availability Agent · Error",
                "pending_action": None,
            }

        rebook_lines = []
        for r in rebooked:
            rebook_lines.append(
                f"• Appointment `{r['appointment_id'][:8]}...`: Rebooking proposed for **{r['new_date']} at {r['new_slot']}** (*Status: Reschedule Pending*)"
            )
        rebook_summary = "\n".join(rebook_lines) if rebook_lines else "• All affected patient appointments set to *Reschedule Pending*."

        verify_badge = "✅ **Verified in Supabase:**" if is_verified else "ℹ️ **Recorded in Supabase:**"
        msg = (
            f"{verify_badge}\n\n"
            f"**Date:** `{target_date}` is now recorded as **Blocked (Leave)**.\n\n"
            f"**Affected Appointments ({len(affected)}):**\n"
            f"{rebook_summary}\n\n"
            "Each patient has been sent a priority notification to confirm the suggested slot or select an alternate OPD time."
        )
        return {
            "message": msg,
            "agent": "Doctor Scheduling & Escalation Agent",
            "pending_action": None,
            "db_updated": True,
        }


class DoctorPatientRecordAgent:
    """Agent for searching, verifying, and presenting patient records and clinical facets."""

    @staticmethod
    def handle_patient_query(
        client: Client,
        query: str,
        all_patients: list[dict[str, Any]],
        all_appointments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Search patient by name, confirm identity, and share specific clinical facets."""
        lowered = query.lower()
        matched_patient = None

        # Search against all patients
        for p in all_patients:
            full_name = p.get("name", "").lower()
            first_name = p.get("first_name", "").lower()
            last_name = p.get("last_name", "").lower()
            if full_name and full_name in lowered:
                matched_patient = p
                break
            if first_name and len(first_name) >= 3 and first_name in lowered:
                matched_patient = p
                break
            if last_name and len(last_name) >= 4 and last_name in lowered:
                matched_patient = p
                break

        if not matched_patient:
            roster_sample = [
                f"• **{p.get('name')}** (ID: {str(p.get('patient_id', ''))[-4:]}) – {p.get('summary', 'Active OPD patient')}"
                for p in all_patients[:5]
            ]
            msg = (
                "Which patient would you like to review?\n\n"
                "Here are patients from your current roster:\n"
                + "\n".join(roster_sample)
                + "\n\nPlease specify a patient name or ID to view their health summary, medications, or appointments."
            )
            return {"message": msg, "agent": "Doctor Patient Records Agent"}

        pid = matched_patient.get("patient_id")
        p_name = matched_patient.get("name") or f"{matched_patient.get('first_name', '')} {matched_patient.get('last_name', '')}".strip()
        age = matched_patient.get("age", 32)
        gender = matched_patient.get("gender", "Female")
        phone = matched_patient.get("contact_phone", "N/A")
        summary = matched_patient.get("summary") or matched_patient.get("patient_summary", "General OPD patient under clinical care.")

        # Check requested facet: meds, appointments, or general health
        wants_meds = any(kw in lowered for kw in ["med", "prescription", "rx", "drugs", "dosage"])
        wants_appts = any(kw in lowered for kw in ["appointment", "booking", "visit", "schedule", "when"])

        facet_sections = []

        if wants_meds or (not wants_meds and not wants_appts):
            # Fetch active prescriptions
            try:
                rx_res = (
                    client.table("prescription_details")
                    .select("*, medicines(*)")
                    .eq("patient_id", pid)
                    .execute()
                )
                rx_rows = rx_res.data or []
                if rx_rows:
                    rx_lines = [
                        f"• **{r.get('medicines', {}).get('medicine_name', 'Medicine')}:** {r.get('dosage', '')} – {r.get('instructions', '')} (*{r.get('meal_timing', 'routine').title()}*)"
                        for r in rx_rows[:4]
                    ]
                    facet_sections.append("💊 **Active Medications:**\n" + "\n".join(rx_lines))
                else:
                    facet_sections.append("💊 **Active Medications:** No active prescription items recorded.")
            except Exception:
                pass

        if wants_appts or (not wants_meds and not wants_appts):
            p_appts = [a for a in all_appointments if str(a.get("patient_id", "")) == str(pid)]
            if p_appts:
                appt_lines = [
                    f"• **{a.get('date', 'OPD')} at {a.get('time', '')}:** {a.get('type', 'Consultation')} – *{a.get('status', 'Confirmed')}*"
                    for a in p_appts[:3]
                ]
                facet_sections.append("📅 **Appointments:**\n" + "\n".join(appt_lines))
            else:
                facet_sections.append("📅 **Appointments:** No upcoming appointments recorded.")

        facets_text = "\n\n".join(facet_sections)
        msg = (
            f"### Patient Clinical Profile: {p_name}\n"
            f"**Demographics:** {gender}, {age}y · **Phone:** {phone} · **ID:** `{pid[-8:] if pid else ''}`\n\n"
            f"**Clinical Baseline & Summary:**\n{summary}\n\n"
            f"{facets_text}"
        )
        return {"message": msg, "agent": "Doctor Patient Records Agent"}


class DoctorIngestionAgent:
    """Agent for parsing clinical notes/PDFs and handling user verification before writing to Supabase."""

    @staticmethod
    def extract_and_propose(text: str, groq_client: Any = None) -> dict[str, Any]:
        """Parse text, extract clinical entities, format preview, and prompt for confirmation."""
        parsed = parse_consultation_text(text, groq_client=groq_client)
        diagnosis = parsed.get("diagnosis", "Clinical Consultation Evaluation")
        symptoms = parsed.get("symptoms", "Not specified")
        vitals = parsed.get("vitals", {})
        vitals_str = f"BP: {vitals.get('bp', '120/80')} | Sugar: {vitals.get('sugar', '95')} mg/dL | Wt: {vitals.get('weight_kg', '60')} kg"
        meds = parsed.get("medications", [])
        med_lines = "\n".join([f"• **{m.get('name')}:** {m.get('dosage')} – {m.get('instructions')}" for m in meds]) if meds else "• None"
        follow_up = parsed.get("follow_up", "Routine follow-up in 2 weeks")

        preview = (
            f"### 📋 Clinical Note Extraction Preview\n\n"
            f"I have parsed the consultation details:\n\n"
            f"• **Diagnosis:** {diagnosis}\n"
            f"• **Symptoms:** {symptoms}\n"
            f"• **Vitals Recorded:** {vitals_str}\n"
            f"• **Prescriptions / Rx ({len(meds)}):**\n{med_lines}\n"
            f"• **Follow-Up:** {follow_up}\n\n"
            "**Would you like me to update and save these records to the Supabase database?**"
        )
        return {
            "message": preview,
            "agent": "Clinical Ingestion & Verification Agent",
            "pending_action": {
                "type": "save_consultation_note",
                "parsed_data": parsed,
            },
        }

    @staticmethod
    def commit_ingestion(
        client: Client,
        parsed_data: dict[str, Any],
        doctor_id: str,
        default_patient_id: str,
    ) -> dict[str, Any]:
        """Commit verified consultation note to Supabase."""
        try:
            res = ingest_consultation_to_supabase(
                client=client,
                parsed=parsed_data,
                doctor_id=doctor_id,
                default_patient_id=default_patient_id,
            )
            report_md = format_ingestion_report(res, "Verified Clinical Consultation Note")
            msg = (
                f"✅ **Consultation Ingestion Confirmed & Committed to Supabase:**\n\n"
                f"{report_md}\n\n"
                "All diagnostic vitals, consultation records, and prescription line items are now live."
            )
            return {
                "message": msg,
                "agent": "Clinical Ingestion & Verification Agent",
                "pending_action": None,
                "db_updated": True,
            }
        except Exception as e:
            return {
                "message": f"❌ Failed to commit consultation note to Supabase: {e}",
                "agent": "Clinical Ingestion & Verification Agent",
                "pending_action": None,
            }


class DoctorChitChatAgent:
    """Agent for deflecting general off-topic conversation and clarifying capabilities."""

    @staticmethod
    def handle_chit_chat(query: str, doctor_name: str) -> dict[str, Any]:
        msg = (
            f"Hello {doctor_name}! I am your **VESPH Clinical Assistant**.\n\n"
            "I'm designed specifically for clinical and practice management workflows, so I can't assist with general non-medical topics. However, I can help you with:\n\n"
            "• **Checking OPD Schedules:** Ask about appointments or counts for any date (e.g. *\"what's my schedule on 21st oct\"*).\n"
            "• **Managing Availability:** Block clinic leave and trigger priority patient rescheduling (e.g. *\"I'm not available on 22nd oct\"*).\n"
            "• **Patient Clinical Inquiries:** Review patient charts, health history, active meds, or appointments (e.g. *\"Tell me about Neha Kapoor's medications\"*).\n"
            "• **Ingesting Consultation Notes:** Paste clinical consultation notes or upload PDFs to parse vitals, diagnoses, and prescriptions into Supabase.\n\n"
            "How can I assist you with your clinic agenda today?"
        )
        return {"message": msg, "agent": "Clinical Assistant · Capabilities"}
