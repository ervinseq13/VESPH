"""Patient Summary Agent backed only by the current care record."""

from __future__ import annotations

from langgraph.runtime import Runtime

from agents.models import AgentSpec
from orchestrator.state import OrchestratorContext, OrchestratorState


SUMMARY_TERMS = (
    "medicine",
    "medication",
    "tablet",
    "inhaler",
    "report",
    "test result",
    "diagnostic",
    "blood",
    "cbc",
    "discharge",
    "surgery",
    "operation",
    "recovery",
    "instructions",
    "summary",
    "health",
    "how am i",
    "history",
)


def _matches(query: str) -> bool:
    return any(term in query for term in SUMMARY_TERMS)


def _reply(message: str, route: str) -> dict:
    return {
        "message": message,
        "agent": f"Patient Summary Agent · {route}",
        "escalated": False,
        "escalation": None,
    }


def _handle(
    state: OrchestratorState, runtime: Runtime[OrchestratorContext]
) -> dict:
    text = state.get("query", "").lower().strip()
    data = runtime.context.care_data
    patient = data["patient"]

    if any(
        term in text
        for term in ("medicine", "medication", "tablet", "dose", "inhaler")
    ):
        lines = [
            f"• {item['name']}: {item['instruction']}"
            for item in data["medications"]
        ]
        return _reply(
            "Your current medication list is:\n\n"
            + "\n".join(lines)
            + "\n\nFollow the discharge prescription. For a missed dose or side effects, "
            "contact your care team rather than changing the dose yourself.",
            "Medications",
        )

    if any(
        term in text
        for term in ("report", "test", "diagnostic", "blood", "cbc", "result")
    ):
        latest = data["diagnostics"][0]
        return _reply(
            f"Your latest result is {latest['name']} from {latest['date']}. "
            f"{latest['summary']} The report is marked as reviewed. Your doctor will "
            "interpret it alongside your recovery at the follow-up visit.",
            "Diagnostics",
        )

    if any(
        term in text
        for term in ("discharge", "surgery", "operation", "recovery", "instructions")
    ):
        discharge = data["discharge"]
        return _reply(
            f"You were discharged on {discharge['discharge_date']} after "
            f"{discharge['procedure'].lower()}. The discharge note says: "
            f"{discharge['condition_at_discharge']} Your planned follow-up is "
            f"{discharge['follow_up']}.",
            "Discharge",
        )

    if any(term in text for term in ("summary", "health", "how am i", "history")):
        return _reply(
            patient["health_summary"]
            + " This is a summary of your hospital record, not a new diagnosis.",
            "Overview",
        )

    return {
        "message": (
            "I can help with your health summary, appointments, reports, medicines, "
            "discharge guidance, or route an issue to the hospital team. Try asking "
            "“When is my next appointment?”"
        ),
        "agent": "Follow-up Assistant · Router",
        "escalated": False,
        "escalation": None,
    }


def build() -> AgentSpec:
    return AgentSpec(
        name="summary_agent",
        description="Answers grounded questions about patient records and recovery.",
        matches=_matches,
        handle=_handle,
    )
