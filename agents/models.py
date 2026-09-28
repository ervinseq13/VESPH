"""Shared plug-in contract between specialist agents and the orchestrator.

An agent supplies intent matching plus one handler. The orchestrator depends on
this contract rather than importing specialist internals, which makes adding or
testing a specialist possible without coupling agents to one another.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.runtime import Runtime

from orchestrator.state import OrchestratorContext, OrchestratorState


AgentHandler = Callable[
    [OrchestratorState, Runtime[OrchestratorContext]], dict[str, Any]
]
IntentMatcher = Callable[[str], bool]


@dataclass(frozen=True)
class AgentSpec:
    """Everything the supervisor needs to register and invoke a specialist.

    ``matches`` classifies a normalized query without side effects. ``handle``
    reads graph state/runtime context and returns a graph-state update; a handler
    may use an explicit tool when its route is allowed to change demo records.
    """

    name: str
    description: str
    matches: IntentMatcher
    handle: AgentHandler
