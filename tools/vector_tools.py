"""Grounded document retrieval seam for a future ChromaDB integration."""

from __future__ import annotations

from typing import Any


def searchable_care_documents(care_data: dict[str, Any]) -> list[dict[str, str]]:
    """Return synthetic document text in the shape a vector index can ingest."""

    documents = [
        {
            "id": item["id"],
            "text": f"{item['name']} {item['date']} {item['summary']}",
        }
        for item in care_data["diagnostics"]
    ]
    discharge = care_data["discharge"]
    documents.append(
        {
            "id": "discharge-summary",
            "text": (
                f"{discharge['procedure']} {discharge['condition_at_discharge']} "
                f"{discharge['follow_up']}"
            ),
        }
    )
    return documents
