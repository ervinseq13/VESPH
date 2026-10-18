"""Doctor Multi-Agent Orchestrator for VESPH Care."""

from __future__ import annotations

import re
from typing import Any
from supabase import Client

from agents.doctor_agents import (
    DoctorScheduleAgent,
    DoctorAvailabilityAndEscalationAgent,
    DoctorPatientRecordAgent,
    DoctorIngestionAgent,
    DoctorChitChatAgent,
)


def parse_date_safe(
    text: str,
    default_month_num: int = 10,
    default_year: int = 2026,
) -> str | None:
    """Extract dates using word-boundary regex patterns, ensuring ordinal numbers

    (e.g., 22nd) are never matched inside single-digit matches (e.g., 2nd),
    and defaults omitted months to the active week's month.
    """
    lowered = text.lower()

    # 1. Check ISO format: YYYY-MM-DD
    iso_match = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])-([0-3][0-9])\b", lowered)
    if iso_match:
        return f"{iso_match.group(1)}-{iso_match.group(2)}-{iso_match.group(3)}"

    # Month dictionary
    months_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    month_pattern = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

    # 2. Pattern: "22nd oct", "22 october", "22nd october 2026"
    m1 = re.search(
        rf"\b(2[0-9]|3[01]|1[0-9]|[1-9])(?:st|nd|rd|th)?\s+({month_pattern})(?:\s+(20\d{{2}}))?\b",
        lowered,
    )
    if m1:
        d = int(m1.group(1))
        m_str = m1.group(2)
        m = months_map.get(m_str[:3], default_month_num)
        y = int(m1.group(3)) if m1.group(3) else default_year
        return f"{y:04d}-{m:02d}-{d:02d}"

    # 3. Pattern: "oct 22", "october 22nd", "october 22nd, 2026"
    m2 = re.search(
        rf"\b({month_pattern})\s+(2[0-9]|3[01]|1[0-9]|[1-9])(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{{2}}))?\b",
        lowered,
    )
    if m2:
        m_str = m2.group(1)
        d = int(m2.group(2))
        m = months_map.get(m_str[:3], default_month_num)
        y = int(m2.group(3)) if m2.group(3) else default_year
        return f"{y:04d}-{m:02d}-{d:02d}"

    # 4. Pattern with omitted month: "21st", "22nd", "on the 22nd", "schedule on 21"
    # Using strict word boundaries so 2nd doesn't match 22nd
    m3 = re.search(r"\b(2[0-9]|3[01]|1[0-9]|[1-9])(?:st|nd|rd|th)\b", lowered)
    if m3:
        d = int(m3.group(1))
        return f"{default_year:04d}-{default_month_num:02d}-{d:02d}"

    # 5. Look for standalone day numbers preceded by date keywords (e.g. "on 21", "date 22")
    m4 = re.search(r"\b(?:on|date|schedule|day|for)\s+(2[0-9]|3[01]|1[0-9]|[1-9])\b", lowered)
    if m4:
        d = int(m4.group(1))
        return f"{default_year:04d}-{default_month_num:02d}-{d:02d}"

    # 6. Relative tokens
    if "today" in lowered:
        return f"{default_year:04d}-10-18"
    if "tomorrow" in lowered:
        return f"{default_year:04d}-10-19"

    return None


def classify_doctor_intent(
    query: str,
    pending_action: dict[str, Any] | None = None,
) -> str:
    """Classify user query into specialized intent categories."""
    lowered = query.lower().strip()

    # 1. Confirmation check
    confirmations = {
        "yes", "yep", "yeah", "sure", "confirm", "proceed", "please do",
        "go ahead", "do it", "yes please", "yes, please", "block it",
        "save it", "save note", "yes save", "update db", "update database"
    }
    if lowered in confirmations or (pending_action and ("confirm" in lowered or "yes" in lowered or "proceed" in lowered)):
        return "CONFIRM_ACTION"

    # 2. Clinical note ingestion check
    clinical_keywords = ["diagnosis", "consultation", "patient:", "vitals", "rx:", "prescribe", "follow-up", "bp:", "symptoms:"]
    matched_kws = sum(1 for kw in clinical_keywords if kw in lowered)
    if matched_kws >= 2 or ("patient" in lowered and ("rx" in lowered or "prescribe" in lowered or "follow-up" in lowered)):
        return "CLINICAL_NOTE"

    # 3. Doctor availability / leave / blocking
    if any(w in lowered for w in ["unavailable", "not available", "leave", "off day", "block", "take off", "clinic off", "unavailability"]):
        return "BLOCK_UNAVAILABILITY"

    # 4. Schedule and appointment query check (handles typos like "what's me schedule")
    schedule_keywords = ["schedule", "agenda", "appointment", "appointments", "booked", "booking", "how many", "slots", "calendar"]
    if any(sk in lowered for sk in schedule_keywords):
        return "CHECK_SCHEDULE"

    # 5. Patient specific inquiry ("Tell me about Neha Kapoor", "patient summary", "patient info")
    patient_keywords = ["tell me about", "who is", "patient info", "patient summary", "patient details", "patient chart", "show patient"]
    if any(pk in lowered for pk in patient_keywords) or "patient" in lowered:
        return "PATIENT_QUERY"

    # 6. Chit-chat / General inquiries / Greeting / Off-topic
    chit_chat_phrases = [
        "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
        "how are you", "who are you", "what can you do", "help", "thanks", "thank you",
        "ok", "okay", "k", "cool", "great", "perfect", "bye", "weather", "joke"
    ]
    if any(lowered == phrase or lowered.startswith(phrase + " ") or lowered.endswith(" " + phrase) for phrase in chit_chat_phrases):
        return "CHIT_CHAT"

    return "GENERAL"


def run_doctor_orchestrator(
    query: str,
    doc_snapshot: dict[str, Any],
    client: Client,
    pending_action: dict[str, Any] | None = None,
    current_week_choice: str = "This (18–24 Oct)",
) -> dict[str, Any]:
    """Central entry point routing doctor requests through memory, parsing, and specialized agents."""
    doc_info = doc_snapshot.get("doctor", {})
    doc_id = doc_info.get("doctor_id") or doc_info.get("id", "11111111-1111-1111-1111-111111111111")
    doc_name = doc_info.get("name") or doc_info.get("doctor_name", "Dr. Rhea Mehta")

    all_appts = doc_snapshot.get("all_appointments", [])
    if not all_appts:
        all_appts = doc_snapshot.get("today_appointments", []) + doc_snapshot.get("week_appointments", [])

    all_patients = doc_snapshot.get("patients_overview", [])

    intent = classify_doctor_intent(query, pending_action=pending_action)
    extracted_date = parse_date_safe(query, default_month_num=10, default_year=2026)

    # ── Intent: Confirmation of Pending Action ──
    if intent == "CONFIRM_ACTION" and pending_action:
        act_type = pending_action.get("type")
        if act_type == "block_unavailability":
            target_date = pending_action.get("date", "2026-10-22")
            return DoctorAvailabilityAndEscalationAgent.propose_or_execute_block(
                client=client,
                doctor_id=doc_id,
                doctor_name=doc_name,
                target_date=target_date,
                all_appointments=all_appts,
                direct_command=True,
            )
        elif act_type == "save_consultation_note":
            parsed_data = pending_action.get("parsed_data", {})
            default_pid = doc_snapshot.get("active_patient_id", "22222222-2222-2222-2222-222222222222")
            return DoctorIngestionAgent.commit_ingestion(
                client=client,
                parsed_data=parsed_data,
                doctor_id=doc_id,
                default_patient_id=default_pid,
            )

    # ── Intent: Clinical Note Ingestion (Verification Gate) ──
    if intent == "CLINICAL_NOTE":
        groq_client = doc_snapshot.get("groq_client")
        return DoctorIngestionAgent.extract_and_propose(query, groq_client=groq_client)

    # ── Intent: Block Unavailability ──
    if intent == "BLOCK_UNAVAILABILITY":
        target_date = extracted_date or "2026-10-22"
        # Check if direct execution requested
        direct = ("block" in query.lower() and ("reschedule" in query.lower() or "supabase" in query.lower() or "trigger" in query.lower()))
        return DoctorAvailabilityAndEscalationAgent.propose_or_execute_block(
            client=client,
            doctor_id=doc_id,
            doctor_name=doc_name,
            target_date=target_date,
            all_appointments=all_appts,
            direct_command=direct,
        )

    # ── Intent: Check Schedule ──
    if intent == "CHECK_SCHEDULE":
        target_date = extracted_date or "2026-10-21"
        # Check if specific time was requested
        time_match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", query.lower())
        target_time = time_match.group(1) if time_match else None
        return DoctorScheduleAgent.handle_schedule_query(
            client=client,
            doctor_id=doc_id,
            doctor_name=doc_name,
            target_date=target_date,
            target_time=target_time,
            all_appointments=all_appts,
        )

    # ── Intent: Patient Query ──
    if intent == "PATIENT_QUERY":
        return DoctorPatientRecordAgent.handle_patient_query(
            client=client,
            query=query,
            all_patients=all_patients,
            all_appointments=all_appts,
        )

    # ── Intent: Chit-Chat Deflection ──
    if intent == "CHIT_CHAT":
        return DoctorChitChatAgent.handle_chit_chat(query, doctor_name=doc_name)

    # Default fallback: Schedule summary for active day or capability guidance
    if extracted_date:
        return DoctorScheduleAgent.handle_schedule_query(
            client=client,
            doctor_id=doc_id,
            doctor_name=doc_name,
            target_date=extracted_date,
            all_appointments=all_appts,
        )

    return DoctorChitChatAgent.handle_chit_chat(query, doctor_name=doc_name)
