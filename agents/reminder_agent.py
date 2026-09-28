"""Reminder Agent for read-only appointment and dose-timing questions.

This specialist owns appointment, confirmation/reschedule, doctor, reminder,
and next-dose intents. It reports schedule data from the current run context;
it does not itself change a booking or medication. Actual UI actions remain
explicit buttons/dialogs so a chat response cannot silently alter care records.
"""

from __future__ import annotations

from langgraph.runtime import Runtime

from agents.models import AgentSpec
from orchestrator.state import OrchestratorContext, OrchestratorState


REMINDER_TERMS = (
    "appointment",
    "book",
    "reschedule",
    "confirm",
    "doctor",
    "reminder",
    "next dose",
    "when do i take",
)


def _matches(query: str) -> bool:
    """Claim reminder-related phrases; escalation wins overlapping phrases."""

    return any(term in query for term in REMINDER_TERMS)


def _handle(
    state: OrchestratorState, runtime: Runtime[OrchestratorContext]
) -> dict:
    """Read the next relevant schedule item and return a grounded response."""

    text = state.get("query", "").lower().strip()
    data = runtime.context.care_data

    if any(term in text for term in ("next dose", "when do i take", "medication reminder")):
        medication = data["medications"][0]
        message = (
            f"Your next listed medication is {medication['name']}: "
            f"{medication['instruction']}. The schedule shows {medication['next_dose']}. "
            "Follow the prescription and contact your care team if a dose was missed."
        )
        route = "Medications"
    else:
        appointment = data["appointments"][0]
        message = (
            f"Your next appointment is {appointment['type']} with "
            f"{appointment['doctor']} on {appointment['date']} at "
            f"{appointment['time']} in {appointment['location']}. Its current status "
            f"is {appointment['status'].lower()}. Use Confirm or Reschedule in the "
            "reminder card."
        )
        route = "Appointments"

    return {
        "message": message,
        "agent": f"Reminder Agent · {route}",
        "escalated": False,
        "escalation": None,
    }


def build() -> AgentSpec:
    """Expose this specialist through the common orchestrator contract."""

    return AgentSpec(
        name="reminder_agent",
        description="Handles reminders, confirmations, reschedules, and dose timing.",
        matches=_matches,
        handle=_handle,
    )
