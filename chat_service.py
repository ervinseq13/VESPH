"""Chat routing that combines deterministic agents with optional integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from orchestrator.graph import run
from orchestrator.state import EscalationState


CONNECTION_TERMS = (
    "check connection",
    "connection status",
    "connections working",
    "groq connected",
    "is groq connected",
    "is groq working",
    "why is groq not working",
    "groq working",
    "groq status",
    "test groq",
    "supabase connected",
    "llm connected",
    "is llm connected",
    "is llm working",
    "llm status",
    "llm and supabase",
    "groq and supabase",
    "system status",
    "status check",
)


class IntegrationAccess(Protocol):
    groq_configured: bool
    settings: Any

    def status_message(self) -> str: ...

    def answer_with_groq(
        self,
        query: str,
        care_data: dict[str, Any],
        recent_messages: list[dict[str, Any]] | None = None,
    ) -> str | None: ...


@dataclass(frozen=True)
class ChatReply:
    message: str
    agent: str
    escalated: bool = False
    escalation: EscalationState | None = None


def is_connection_query(prompt: str) -> bool:
    normalized = " ".join(prompt.lower().split())
    return any(term in normalized for term in CONNECTION_TERMS)


def answer_chat(
    orchestrator,
    integrations: IntegrationAccess,
    prompt: str,
    care_data: dict[str, Any],
    patient_id: str,
    *,
    recent_messages: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    persona: str = "patient",
) -> ChatReply:
    """Use deterministic safety routes first and Groq only for open questions."""

    if is_connection_query(prompt):
        return ChatReply(
            message=integrations.status_message(),
            agent="System · Connection check",
        )

    deterministic = run(
        orchestrator,
        prompt,
        care_data,
        patient_id,
        thread_id=thread_id,
    )

    # 1. Safety Invariant: Emergency medical escalations always take top precedence
    if deterministic.escalated:
        return ChatReply(
            message=deterministic.message,
            agent=deterministic.agent,
            escalated=True,
            escalation=deterministic.escalation,
        )

    # 2. Contextual Intelligence: If Groq is configured, answer with contextual reasoning
    if integrations.groq_configured:
        generated = integrations.answer_with_groq(
            prompt,
            care_data,
            recent_messages=recent_messages,
            persona=persona,
        )
        if generated:
            agent_badge = (
                f"Groq Clinical Assistant · {integrations.settings.groq_model}"
                if persona == "doctor"
                else (
                    f"Reminder Agent · {integrations.settings.groq_model}"
                    if "Reminder" in deterministic.agent
                    else f"Clinical Care Assistant · {integrations.settings.groq_model}"
                )
            )
            return ChatReply(
                message=generated,
                agent=agent_badge,
            )

    # 3. Fallback to deterministic specialist agent
    return ChatReply(
        message=deterministic.message,
        agent=deterministic.agent,
        escalated=deterministic.escalated,
        escalation=deterministic.escalation,
    )
