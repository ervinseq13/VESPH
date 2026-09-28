"""Data contracts shared by the VESPH LangGraph supervisor and specialists.

``OrchestratorState`` is eligible for thread checkpointing. In contrast,
``OrchestratorContext`` exists only for one invocation, keeping the full current
patient record out of saved conversation state.
"""

from __future__ import annotations

from dataclasses import dataclass
from operator import add
from typing import Annotated, Any, Literal, TypedDict


EscalationStatus = Literal["pending_confirmation", "confirmed"]


class EscalationState(TypedDict, total=False):
    """Pending or confirmed hospital-team action shown back to the patient."""

    id: str
    category: str
    reason: str
    prompt: str
    options: list[str]
    status: EscalationStatus
    resolution: str


class ConversationMessage(TypedDict, total=False):
    """Minimal message shape accumulated by LangGraph checkpoints."""

    role: Literal["user", "assistant"]
    content: str
    agent: str


class OrchestratorState(TypedDict, total=False):
    """Checkpointable inputs and outputs passed between graph nodes.

    The ``add`` reducer appends new messages instead of replacing prior thread
    history. Other fields describe only the current graph action/result.
    """

    messages: Annotated[list[ConversationMessage], add]
    action: Literal["message", "resolve_escalation"]
    query: str
    resolution: str
    escalation_id: str
    message: str
    agent: str
    escalated: bool
    escalation: EscalationState | None


@dataclass(frozen=True)
class OrchestratorContext:
    """Fresh data available for one run but excluded from checkpoints.

    Specialists read the current mutable demo record through ``care_data``.
    Keeping it here avoids stale clinical snapshots in conversation memory and
    provides the seam where a future Supabase-backed record can be supplied.
    """

    patient_id: str
    care_data: dict[str, Any]
