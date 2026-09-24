"""State and run-scoped context for the VESPH LangGraph workflow."""

from __future__ import annotations

from dataclasses import dataclass
from operator import add
from typing import Annotated, Any, Literal, TypedDict


EscalationStatus = Literal["pending_confirmation", "confirmed"]


class EscalationState(TypedDict, total=False):
    id: str
    category: str
    reason: str
    prompt: str
    options: list[str]
    status: EscalationStatus
    resolution: str


class ConversationMessage(TypedDict, total=False):
    role: Literal["user", "assistant"]
    content: str
    agent: str


class OrchestratorState(TypedDict, total=False):
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
    """Data available for one run but deliberately excluded from checkpoints."""

    patient_id: str
    care_data: dict[str, Any]
