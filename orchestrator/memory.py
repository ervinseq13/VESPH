"""Short- and long-term memory backends for the local capstone demo.

The in-memory implementations keep the project runnable without infrastructure.
Production can replace these two objects with PostgresSaver and PostgresStore
using the Supabase Postgres connection string.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


@dataclass(frozen=True)
class MemoryBackends:
    checkpointer: InMemorySaver
    store: InMemoryStore


def build_memory() -> MemoryBackends:
    """Create thread-scoped chat state and a separate durable-fact store."""

    return MemoryBackends(
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
    )
