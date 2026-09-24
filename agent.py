"""Deterministic agent router for a reliable capstone demo.

This deliberately does not diagnose or invent patient facts. A LangGraph workflow
can call the same intent handlers later after adding retrieval and guardrails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentReply:
    message: str
    agent: str
    escalated: bool = False


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def respond(query: str, data: dict[str, Any]) -> AgentReply:
    """Route a patient question to a safe, context-grounded demo response."""

    text = query.lower().strip()
    patient = data["patient"]
    appointments = data["appointments"]
    medications = data["medications"]
    diagnostics = data["diagnostics"]
    discharge = data["discharge"]

    if _contains(
        text,
        (
            "emergency",
            "chest pain",
            "can't breathe",
            "cannot breathe",
            "severe pain",
            "fainted",
            "unconscious",
            "heavy bleeding",
        ),
    ):
        return AgentReply(
            "This could need urgent medical attention. Please call the hospital emergency desk at "
            "+91 22 4000 1122 or your local emergency service now. I can send your patient ID and "
            "recent discharge context to the escalation desk, but I cannot assess an emergency here.",
            "Escalation Agent · Emergency",
            True,
        )

    if _contains(text, ("wrong report", "someone else", "not my report")):
        return AgentReply(
            "I’ve prepared an escalation for the Records Desk: possible incorrect report attached to "
            f"patient {patient['id']}. Please do not use or share the file. A staff member should verify "
            "the report identity before a replacement is issued.",
            "Escalation Agent · Records",
            True,
        )

    if _contains(text, ("reissue", "old report", "previous report", "report copy")):
        return AgentReply(
            "I can request a reissued report. Your available records are CBC (16 Sep), appendix "
            "histopathology (10 Sep), and ultrasound abdomen (7 Sep). Tell me which one you need.",
            "Escalation Agent · Records",
        )

    if _contains(text, ("doctor not available", "doctor unavailable", "missed appointment")):
        return AgentReply(
            "I can route this to the scheduling desk. Dr. Kabir Sen has General Surgery availability "
            "on 24 Sep if Dr. Rhea Mehta is unavailable. I’ll show the available times before any "
            "booking is changed.",
            "Escalation Agent · Scheduling",
            True,
        )

    if _contains(text, ("appointment", "book", "reschedule", "confirm", "doctor")):
        next_appointment = appointments[0]
        return AgentReply(
            f"Your next appointment is {next_appointment['type']} with {next_appointment['doctor']} "
            f"on {next_appointment['date']} at {next_appointment['time']} in "
            f"{next_appointment['location']}. Its current status is "
            f"{next_appointment['status'].lower()}. Use Confirm or Reschedule in the reminder card.",
            "Reminder Agent · Appointments",
        )

    if _contains(text, ("medicine", "medication", "tablet", "dose", "inhaler")):
        lines = [f"• {item['name']}: {item['instruction']}" for item in medications]
        return AgentReply(
            "Your current medication list is:\n\n"
            + "\n".join(lines)
            + "\n\nFollow the discharge prescription. For a missed dose or side effects, contact "
            "your care team rather than changing the dose yourself.",
            "Patient Summary Agent · Medications",
        )

    if _contains(text, ("report", "test", "diagnostic", "blood", "cbc", "result")):
        latest = diagnostics[0]
        return AgentReply(
            f"Your latest result is {latest['name']} from {latest['date']}. {latest['summary']} "
            "The report is marked as reviewed. Your doctor will interpret it alongside your recovery "
            "at the follow-up visit.",
            "Patient Summary Agent · Diagnostics",
        )

    if _contains(text, ("discharge", "surgery", "operation", "recovery", "instructions")):
        return AgentReply(
            f"You were discharged on {discharge['discharge_date']} after "
            f"{discharge['procedure'].lower()}. The discharge note says: "
            f"{discharge['condition_at_discharge']} Your planned follow-up is "
            f"{discharge['follow_up']}.",
            "Patient Summary Agent · Discharge",
        )

    if _contains(text, ("summary", "health", "how am i", "history")):
        return AgentReply(
            patient["health_summary"]
            + " This is a summary of your hospital record, not a new diagnosis.",
            "Patient Summary Agent · Overview",
        )

    return AgentReply(
        "I can help with your health summary, appointments, reports, medicines, discharge guidance, "
        "or route an issue to the hospital team. Try asking “When is my next appointment?”",
        "Follow-up Assistant · Router",
    )

