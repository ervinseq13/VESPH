"""Shared contracts for plug-and-play VESPH agents."""

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
    """The one-function contract every specialist exposes through ``build``."""

    name: str
    description: str
    matches: IntentMatcher
    handle: AgentHandler
