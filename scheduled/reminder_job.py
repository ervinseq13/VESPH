"""Pure reminder generation logic for a future EC2 cron entry."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def appointments_due_within(
    appointments: list[dict[str, Any]], now: datetime, hours: int = 48
) -> list[dict[str, Any]]:
    """Find confirmed appointments in the requested reminder window."""

    deadline = now + timedelta(hours=hours)
    due: list[dict[str, Any]] = []
    for appointment in appointments:
        if appointment.get("status") != "Confirmed":
            continue
        scheduled = datetime.strptime(
            f"{appointment['date']} {appointment['time']}", "%d %b %Y %I:%M %p"
        )
        if now <= scheduled <= deadline:
            due.append(appointment)
    return due
