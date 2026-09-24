"""Database boundary used by the agent workflow.

For the capstone this writes to the mutable JSON-backed session snapshot passed
by Streamlit. Replacing these functions with Supabase calls leaves agents and UI
code unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from orchestrator.state import EscalationState


def create_escalation(
    care_data: dict[str, Any], escalation: EscalationState
) -> EscalationState:
    """Persist a pending escalation without duplicating graph retries."""

    escalations = care_data.setdefault("escalations", [])
    existing = next(
        (item for item in escalations if item["id"] == escalation["id"]), None
    )
    if existing is None:
        existing = deepcopy(escalation)
        escalations.append(existing)
    return deepcopy(existing)


def confirm_escalation(
    care_data: dict[str, Any], escalation_id: str, resolution: str
) -> EscalationState:
    """Record the patient's chosen resolution for a pending escalation."""

    escalations = care_data.setdefault("escalations", [])
    escalation = next(
        (item for item in escalations if item["id"] == escalation_id), None
    )
    if escalation is None:
        raise ValueError("The escalation is no longer available to confirm.")
    if escalation.get("status") == "confirmed":
        return deepcopy(escalation)
    if resolution not in escalation.get("options", []):
        raise ValueError("Choose one of the resolution options shown in chat.")

    escalation["status"] = "confirmed"
    escalation["resolution"] = resolution
    return deepcopy(escalation)
