"""Application boundary between the Streamlit UI and the agent system.

Call flow:
    Streamlit -> ``answer_chat`` -> deterministic LangGraph workflow
    -> specialist response, or Groq for an unmatched open question -> Streamlit

This layer chooses *how* to obtain an answer and normalizes the result into a
``ChatReply``. It does not write chat history, persist patient records, or
render UI; those responsibilities stay with ``app.py`` and the tool boundary.
"""

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
    "supabase connected",
    "llm connected",
    "llm and supabase",
    "groq and supabase",
)


class IntegrationAccess(Protocol):
    """Small interface chat routing needs from the external-integration layer.

    Using a protocol keeps routing testable with a fake integration object and
    prevents this module from depending on Groq or Supabase client details.
    """

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
    """Provider-independent result returned to the Streamlit presentation layer."""

    message: str
    agent: str
    escalated: bool = False
    escalation: EscalationState | None = None


def is_connection_query(prompt: str) -> bool:
    """Recognize an explicit request to test configured external services."""

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
) -> ChatReply:
    """Use deterministic safety routes first and Groq only for open questions.

    Ordering is intentional: connection checks must report real service health,
    while clinical and operational intents first pass through predictable
    specialist rules. Groq is outside the graph and receives only questions for
    which the deterministic workflow returned its generic Router response.

    This function itself is not a persistence boundary. Any record mutation
    comes from a specialist tool invoked inside the graph; the caller stores
    the returned reply in UI chat history.
    """

    # Connection checks bypass patient-intent routing and may make live service
    # health requests through IntegrationHub. They never reveal secret values.
    if is_connection_query(prompt):
        return ChatReply(
            message=integrations.status_message(),
            agent="System · Connection check",
        )

    # The graph always runs first so emergency/escalation and known patient
    # intents cannot be overridden by a generative model response.
    deterministic = run(
        orchestrator,
        prompt,
        care_data,
        patient_id,
        thread_id=thread_id,
    )
    if deterministic.agent != "Follow-up Assistant · Router":
        return ChatReply(
            message=deterministic.message,
            agent=deterministic.agent,
            escalated=deterministic.escalated,
            escalation=deterministic.escalation,
        )

    # The Router label is the graph's explicit signal that no specialist gave
    # a specific answer. Groq is therefore a fallback, not a fourth graph node.
    generated = integrations.answer_with_groq(
        prompt,
        care_data,
        recent_messages=recent_messages,
    )
    if generated:
        return ChatReply(
            message=generated,
            agent=f"Groq Care Assistant · {integrations.settings.groq_model}",
        )

    # Missing configuration or a failed Groq request returns the safe,
    # deterministic Router guidance instead of breaking the conversation.
    return ChatReply(
        message=deterministic.message,
        agent=deterministic.agent,
    )
