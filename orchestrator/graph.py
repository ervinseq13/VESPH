"""LangGraph supervisor for VESPH specialist agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from agents.escalation_agent import build as build_escalation
from agents.reminder_agent import build as build_reminder
from agents.summary_agent import build as build_summary
from orchestrator.memory import MemoryBackends, build_memory
from orchestrator.state import EscalationState, OrchestratorContext, OrchestratorState
from tools.db_tools import confirm_escalation


@dataclass(frozen=True)
class OrchestratorResult:
    message: str
    agent: str
    escalated: bool = False
    escalation: EscalationState | None = None


def build_orchestrator(memory: MemoryBackends | None = None):
    """Compile the deterministic supervisor with isolated memory backends."""

    memory = memory or build_memory()
    summary = build_summary()
    reminder = build_reminder()
    escalation = build_escalation()
    agents = (escalation, reminder, summary)

    def route(state: OrchestratorState) -> str:
        if state.get("action") == "resolve_escalation":
            return "resolve_escalation"
        query = state.get("query", "").lower().strip()
        return next((agent.name for agent in agents if agent.matches(query)), summary.name)

    def with_conversation_history(handler: Callable):
        def node(
            state: OrchestratorState, runtime: Runtime[OrchestratorContext]
        ) -> dict[str, Any]:
            update = handler(state, runtime)
            update["messages"] = [
                {
                    "role": "assistant",
                    "content": update["message"],
                    "agent": update["agent"],
                }
            ]
            return update

        return node

    def resolve_node(
        state: OrchestratorState, runtime: Runtime[OrchestratorContext]
    ) -> dict[str, Any]:
        try:
            escalation_record = confirm_escalation(
                runtime.context.care_data,
                state.get("escalation_id", ""),
                state.get("resolution", ""),
            )
        except ValueError as error:
            update = {
                "message": str(error),
                "agent": "Escalation Agent · Confirmation",
                "escalated": True,
                "escalation": None,
            }
            update["messages"] = [
                {
                    "role": "assistant",
                    "content": update["message"],
                    "agent": update["agent"],
                }
            ]
            return update

        if runtime.store:
            runtime.store.put(
                ("patients", runtime.context.patient_id, "escalation_resolutions"),
                escalation_record["id"],
                {
                    "category": escalation_record["category"],
                    "resolution": escalation_record["resolution"],
                },
            )
        update = {
            "message": (
                f"Confirmed — I recorded “{escalation_record['resolution']}” for the "
                f"{escalation_record['category']} escalation. The relevant hospital team "
                "can now follow that instruction."
            ),
            "agent": "Escalation Agent · Resolution confirmed",
            "escalated": False,
            "escalation": escalation_record,
        }
        update["messages"] = [
            {
                "role": "assistant",
                "content": update["message"],
                "agent": update["agent"],
            }
        ]
        return update

    workflow = StateGraph(OrchestratorState, context_schema=OrchestratorContext)
    workflow.add_node(summary.name, with_conversation_history(summary.handle))
    workflow.add_node(reminder.name, with_conversation_history(reminder.handle))
    workflow.add_node(escalation.name, with_conversation_history(escalation.handle))
    workflow.add_node("resolve_escalation", resolve_node)
    workflow.add_conditional_edges(
        START,
        route,
        {
            summary.name: summary.name,
            reminder.name: reminder.name,
            escalation.name: escalation.name,
            "resolve_escalation": "resolve_escalation",
        },
    )
    for node in (summary.name, reminder.name, escalation.name, "resolve_escalation"):
        workflow.add_edge(node, END)
    return workflow.compile(
        checkpointer=memory.checkpointer,
        store=memory.store,
    )


def _as_result(output: OrchestratorState) -> OrchestratorResult:
    return OrchestratorResult(
        message=output["message"],
        agent=output["agent"],
        escalated=output.get("escalated", False),
        escalation=output.get("escalation"),
    )


def run(
    orchestrator,
    query: str,
    care_data: dict[str, Any],
    patient_id: str,
    *,
    thread_id: str | None = None,
) -> OrchestratorResult:
    """Route one patient message with fresh clinical data as run context."""

    output = orchestrator.invoke(
        {
            "messages": [{"role": "user", "content": query}],
            "action": "message",
            "query": query,
            "resolution": "",
            "escalation_id": "",
            "escalation": None,
        },
        config={"configurable": {"thread_id": thread_id or patient_id}},
        context=OrchestratorContext(patient_id=patient_id, care_data=care_data),
    )
    return _as_result(output)


def resolve(
    orchestrator,
    escalation_id: str,
    resolution: str,
    care_data: dict[str, Any],
    patient_id: str,
    *,
    thread_id: str | None = None,
) -> OrchestratorResult:
    """Resume the thread with the patient's explicit escalation resolution."""

    output = orchestrator.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"Resolution confirmed: {resolution}",
                }
            ],
            "action": "resolve_escalation",
            "query": "",
            "resolution": resolution,
            "escalation_id": escalation_id,
        },
        config={"configurable": {"thread_id": thread_id or patient_id}},
        context=OrchestratorContext(patient_id=patient_id, care_data=care_data),
    )
    return _as_result(output)
