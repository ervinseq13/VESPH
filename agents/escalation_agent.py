"""Escalation Agent with explicit patient resolution confirmation."""

from __future__ import annotations

from uuid import uuid4

from langgraph.runtime import Runtime

from agents.models import AgentSpec
from orchestrator.state import EscalationState, OrchestratorContext, OrchestratorState
from tools.db_tools import create_escalation


EMERGENCY_TERMS = (
    "emergency",
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "severe pain",
    "fainted",
    "unconscious",
    "heavy bleeding",
)
ESCALATION_TERMS = EMERGENCY_TERMS + (
    "wrong report",
    "someone else",
    "not my report",
    "reissue",
    "old report",
    "previous report",
    "report copy",
    "doctor not available",
    "doctor is not available",
    "doctor unavailable",
    "doctor is unavailable",
    "missed appointment",
    "new appointment",
    "place new test",
    "new test",
    "order a test",
)


def _matches(query: str) -> bool:
    return any(term in query for term in ESCALATION_TERMS)


def _details(text: str, patient_id: str) -> tuple[str, str, str, list[str], str]:
    if any(term in text for term in EMERGENCY_TERMS):
        return (
            "emergency",
            "Possible urgent medical need",
            (
                "This could need urgent medical attention. Call the hospital emergency "
                "desk at +91 22 4000 1122 or your local emergency service now. Do not "
                "wait for chat. I can also record how you are proceeding for the care team."
            ),
            [
                "I’m calling emergency services now",
                "Contact the hospital emergency desk",
                "Notify my care team as well",
            ],
            "How are you proceeding with this urgent escalation?",
        )
    if any(term in text for term in ("wrong report", "someone else", "not my report")):
        return (
            "records",
            "Possible incorrect report",
            (
                "I’ve opened a Records Desk escalation for a possible incorrect report "
                f"attached to patient {patient_id}. Do not use or share the file until its "
                "identity is verified."
            ),
            [
                "Remove it and verify identity",
                "Request a corrected report",
                "Ask the Records Desk to call me",
            ],
            "Please confirm how you want the Records Desk to resolve this.",
        )
    if any(term in text for term in ("reissue", "old report", "previous report", "report copy")):
        return (
            "records",
            "Previous report requested",
            (
                "I can send a reissue request to the Records Desk. Available records include "
                "CBC (16 Sep), appendix histopathology (10 Sep), and ultrasound abdomen "
                "(7 Sep)."
            ),
            [
                "Reissue the latest report",
                "Let me choose the report first",
                "Ask the Records Desk to call me",
            ],
            "How should the Records Desk handle the reissue?",
        )
    if any(term in text for term in ("new test", "place new test", "order a test")):
        return (
            "diagnostics",
            "New diagnostic requested",
            (
                "A clinician must approve a new diagnostic order. I can route your request "
                "to the care team without creating an unapproved test booking."
            ),
            [
                "Send the request to my doctor",
                "Ask Diagnostics to call me",
                "Show existing diagnostic bookings",
            ],
            "Please confirm how you want this diagnostic request handled.",
        )
    if "new appointment" in text:
        return (
            "scheduling",
            "New appointment requested",
            "I can send a new appointment request to the scheduling desk.",
            [
                "Show available appointments",
                "Ask Scheduling to call me",
                "Send the request to my doctor",
            ],
            "Please confirm how you want to continue with the new appointment.",
        )
    return (
        "scheduling",
        "Appointment needs staff review",
        (
            "I can route this to the scheduling desk. Dr. Kabir Sen has General Surgery "
            "availability on 24 Sep if Dr. Rhea Mehta is unavailable. No booking will be "
            "changed until you confirm how to proceed."
        ),
        [
            "Show Dr. Kabir Sen’s times",
            "Keep my current appointment",
            "Ask Scheduling to call me",
        ],
        "Please confirm how you want the scheduling escalation resolved.",
    )


def _handle(
    state: OrchestratorState, runtime: Runtime[OrchestratorContext]
) -> dict:
    text = state.get("query", "").lower().strip()
    category, reason, message, options, prompt = _details(
        text, runtime.context.patient_id
    )
    escalation: EscalationState = {
        "id": f"ESC-{uuid4().hex[:8].upper()}",
        "category": category,
        "reason": reason,
        "prompt": prompt,
        "options": options,
        "status": "pending_confirmation",
    }
    escalation = create_escalation(runtime.context.care_data, escalation)
    return {
        "message": message + " Choose one of the resolution options below.",
        "agent": f"Escalation Agent · {category.title()}",
        "escalated": True,
        "escalation": escalation,
    }


def build() -> AgentSpec:
    return AgentSpec(
        name="escalation_agent",
        description=(
            "Routes emergencies, missed care, unavailable clinicians, and record issues "
            "to a hospital team with patient-confirmed resolution."
        ),
        matches=_matches,
        handle=_handle,
    )
