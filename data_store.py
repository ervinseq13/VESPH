"""Small JSON repository used by the frontend demo.

The files contain synthetic patient data only. Replacing this module with API/S3
calls later keeps storage concerns out of the Streamlit UI.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).parent / "data"


def _read_json(filename: str) -> Any:
    with (DATA_DIR / filename).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_demo_data() -> dict[str, Any]:
    """Return a new mutable copy of all records needed by the app."""

    data = {
        "patient": _read_json("patient.json"),
        "appointments": _read_json("patient_appointments.json"),
        "diagnostics": _read_json("patient_diagnostics.json"),
        "discharge": _read_json("patient_discharge.json"),
        "medications": _read_json("medications.json"),
        "appointment_schedule": _read_json("appointment_schedule.json"),
        "diagnostic_schedule": _read_json("diagnostic_schedule.json"),
        "doctor_schedule": _read_json("doctor_schedule.json"),
        "operation_schedule": _read_json("operation_schedule.json"),
        "reminders": _read_json("reminders.json"),
    }
    return deepcopy(data)

