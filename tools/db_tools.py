"""Record-mutation boundary used by the agent workflow.

For the capstone this writes to the mutable JSON-backed session snapshot passed
by Streamlit. Replacing these functions with Supabase calls leaves agents and UI
code unchanged. These are the only specialist-facing functions in the current
flow that change patient-related demo data; neither function contacts a real
hospital system today.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from orchestrator.state import EscalationState


def create_escalation(
    care_data: dict[str, Any], escalation: EscalationState
) -> EscalationState:
    """Persist a pending escalation without duplicating graph retries.

    Side effect: appends to ``care_data['escalations']`` when the ID is new.
    ``deepcopy`` prevents callers from accidentally mutating the stored record
    through the object returned to graph/UI state.
    """

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
    """Record the patient's chosen resolution for a pending escalation.

    Side effect: changes the matching demo escalation to ``confirmed`` and
    stores the selected option. Unknown IDs and unoffered options are rejected.
    A future Supabase implementation should preserve this validation and make
    the update atomically under the authenticated patient's access policy.
    """

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
