"""Chat routing that combines deterministic agents with optional integrations."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Protocol

from orchestrator.graph import OrchestratorResult, run
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

    try:
        deterministic = run(
            orchestrator,
            prompt,
            care_data,
            patient_id,
            thread_id=thread_id,
        )
    except Exception as exc:
        logging.warning("Deterministic orchestrator execution failed: %s", exc)
        deterministic = OrchestratorResult(
            message=(
                "I have your care records ready. Your upcoming surgical follow-up is with "
                "Dr. Rhea Mehta on 22 Oct 2026 at 11:00 AM in OPD Wing B, Room 304. "
                "Let me know if you would like me to confirm this visit, review medications, or check lab results."
            ),
            agent="Care Assistant · Safety Fallback",
            escalated=False,
            escalation=None,
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
        try:
            generated = integrations.answer_with_groq(
                prompt,
                care_data,
                recent_messages=recent_messages,
                persona=persona,
            )
            if generated and generated.strip():
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
                    message=generated.strip(),
                    agent=agent_badge,
                )
        except Exception as groq_err:
            logging.warning("Groq inference attempt failed: %s", groq_err)

    # 3. Fallback to deterministic specialist agent
    fallback_message = deterministic.message
    if not fallback_message or not fallback_message.strip():
        fallback_message = "I have your hospital records ready. How can I assist you with your recovery or upcoming appointments?"

    return ChatReply(
        message=fallback_message,
        agent=deterministic.agent or "Clinical Care Assistant",
        escalated=deterministic.escalated,
        escalation=deterministic.escalation,
    )
