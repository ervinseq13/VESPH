"""Backward-compatible entry point for the VESPH orchestrator.

New code should import ``orchestrator.graph`` directly. Keeping ``respond``
avoids breaking existing callers while the capstone transitions to LangGraph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from orchestrator.graph import build_orchestrator, run
from orchestrator.state import EscalationState


@dataclass(frozen=True)
class AgentReply:
    message: str
    agent: str
    escalated: bool = False
    escalation: EscalationState | None = None


def respond(query: str, data: dict[str, Any]) -> AgentReply:
    """Route one message through an isolated graph for legacy callers."""

    patient_id = data["patient"]["id"]
    result = run(
        build_orchestrator(),
        query,
        data,
        patient_id,
        thread_id=f"legacy-{uuid4().hex}",
    )
    return AgentReply(
        message=result.message,
        agent=result.agent,
        escalated=result.escalated,
        escalation=result.escalation,
    )
