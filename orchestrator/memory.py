"""Short- and long-term memory backends for the local capstone demo.

The checkpointer retains graph/thread state, including accumulated messages.
The store holds patient-scoped facts such as confirmed escalation resolutions.
Both implementations are process-local: restarting or redeploying Streamlit
clears them. Production can replace these objects with PostgresSaver and
PostgresStore using the Supabase Postgres connection string without changing
the specialist-agent contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


@dataclass(frozen=True)
class MemoryBackends:
    """Keep thread checkpoints and cross-thread facts as separate concerns."""

    checkpointer: InMemorySaver
    store: InMemoryStore


def build_memory() -> MemoryBackends:
    """Create process-local thread state and a separate patient-fact store.

    "Durable" here means separate from a single graph invocation, not durable
    across a Streamlit process restart; persistence requires Postgres backends.
    """

    return MemoryBackends(
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
    )
