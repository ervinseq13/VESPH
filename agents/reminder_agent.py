"""Reminder Agent for appointment and medication follow-up conversations."""

from __future__ import annotations

from langgraph.runtime import Runtime

from agents.models import AgentSpec
from orchestrator.state import OrchestratorContext, OrchestratorState


PAST_QUERY_MARKERS = (
    "last appointment", "past appointment", "previous appointment",
    "last visit", "previous visit", "past visit",
    "what happened", "what did the doctor say", "what was decided",
    "last consultation", "previous consultation", "past consultation",
    "earlier appointment", "notes from", "summary of my", "what took place",
    "what was discussed", "happened in", "happened at",
)

REMINDER_TERMS = (
    # Appointments — natural ways patients ask about upcoming/pending visits
    "next appointment", "upcoming appointment", "my appointment",
    "when is my appointment", "appointment time", "appointment date",
    "appointment schedule", "reschedule appointment", "confirm appointment",
    "book appointment", "appointment reminder", "appointment",
    "when do i go", "when do i have to go", "have to go",
    "when is my visit", "next visit", "hospital visit", "hospital",
    "do i have to come in", "am i supposed to go", "what time is my",
    "when do i see the doctor", "when do i see dr", "coming saturday",
    "this week at the hospital", "confirm my visit", "can i change the date",
    "reschedule", "rebook", "move my appointment", "cancel my visit",
    "postpone", "book", "confirm", "reminder", "visit", "clinic", "checkup",
    # Medication timing
    "when do i take", "next dose", "did i take my", "morning pills",
    "evening meds", "what meds with breakfast", "what meds with lunch",
    "what meds with dinner", "should i take it now", "medication reminder",
    "took my medicine", "haven't taken", "forgot my meds", "pill", "tablet",
    # Diagnostic scheduling reminders
    "blood test before", "get a test done", "lab before my appointment",
    "doctor told me to get", "test before the visit", "need to schedule a blood",
    "when is my cbc", "diagnostic", "blood test", "lab test", "ultrasound",
)


def _matches(query: str) -> bool:
    lowered = query.lower().strip()
    if any(marker in lowered for marker in PAST_QUERY_MARKERS):
        return False
    return any(term in lowered for term in REMINDER_TERMS)


def _handle(
    state: OrchestratorState, runtime: Runtime[OrchestratorContext]
) -> dict:
    text = state.get("query", "").lower().strip()
    data = runtime.context.care_data

    # Branch 1: Pre-visit diagnostic test reminders (e.g. blood diagnostics before next appointment)
    if any(term in text for term in (
        "blood test before", "get a test done", "lab before my appointment",
        "doctor told me to get", "test before the visit", "schedule a blood",
        "when is my cbc", "diagnostic", "blood test", "lab test"
    )):
        diag_sched = data.get("diagnostic_schedule", [])
        if diag_sched:
            test_info = diag_sched[0]
            message = (
                f"Reminder: As recommended by your doctor, you have a {test_info.get('test', 'Complete Blood Count (CBC)')} "
                f"scheduled for {test_info.get('date', '20 Oct 2026')} at {test_info.get('time', '09:00 AM')} "
                f"at {test_info.get('location', 'Pathology Lab · 1st Floor')}. "
                f"Preparation: {test_info.get('preparation', 'No fasting required')}. "
                "Please complete this test prior to your surgical follow-up so results are ready for your doctor."
            )
        else:
            message = (
                "Reminder: Please schedule your recommended pre-visit blood diagnostics (CBC) "
                "at least 48 hours before your next surgical consultation so results are ready for review."
            )
        route = "Diagnostic Tests"

    # Branch 2: Medication timing & meal check reminders
    elif any(term in text for term in (
        "next dose", "when do i take", "medication reminder", "morning pills",
        "evening meds", "what meds with breakfast", "what meds with lunch",
        "what meds with dinner", "did i take", "took my", "forgot my", "medicine"
    )):
        meds = data.get("medications", [])
        b_meds = [m for m in meds if m.get("meal_timing") == "breakfast"]
        l_meds = [m for m in meds if m.get("meal_timing") == "lunch"]
        d_meds = [m for m in meds if m.get("meal_timing") == "dinner"]

        if "breakfast" in text or "morning" in text:
            target_list = b_meds
            meal_name = "Breakfast (Morning)"
        elif "lunch" in text or "afternoon" in text:
            target_list = l_meds
            meal_name = "Lunch (Afternoon)"
        elif "dinner" in text or "night" in text or "evening" in text:
            target_list = d_meds
            meal_name = "Dinner (Night)"
        else:
            # Check for next pending dose
            pending = [m for m in meds if not m.get("is_taken")]
            target_list = pending[:1] if pending else meds[:1]
            meal_name = target_list[0].get("meal_timing", "current schedule").title() if target_list else "today"

        if target_list:
            m = target_list[0]
            status_str = "already marked as taken ✓" if m.get("is_taken") else "scheduled/pending"
            message = (
                f"Medication Reminder for {meal_name}: {m['name']} ({m.get('dosage', '')}). "
                f"Instruction: {m['instruction']}. Current status: {status_str}. "
                "You can tap the checkbox in your Medications tab to confirm your dose."
            )
        else:
            medication = meds[0] if meds else {"name": "Pantocid 40", "instruction": "Take before breakfast", "next_dose": "Daily"}
            message = (
                f"Your next scheduled medication is {medication['name']}: {medication['instruction']}. "
                "Remember to follow your meal timing and keep your care team informed."
            )
        route = "Medication Timing"

    # Branch 3: Appointment attendance confirmation and scheduling
    else:
        appts = data.get("appointments", [])
        upcoming = [a for a in appts if a.get("status") not in ("Completed", "Cancelled")]
        appointment = upcoming[0] if upcoming else (appts[0] if appts else {})
        if appointment:
            message = (
                f"Hospital Visit Confirmation: Your next visit is a {appointment.get('type', 'Consultation')} "
                f"with {appointment.get('doctor', 'Dr. Rhea Mehta')} on {appointment.get('date', '22 Oct 2026')} "
                f"at {appointment.get('time', '11:30 AM')} in {appointment.get('location', 'OPD Wing B, Room 304')}. "
                f"Status: {appointment.get('status', 'Confirmed')}. "
                f"Preparation: {appointment.get('preparation', 'Please bring previous reports')}. "
                "If you need to change your date, tap Reschedule in your Appointments tab to view available open slots."
            )
        else:
            message = "You have no pending hospital appointments currently scheduled on file."
        route = "Appointment Attendance"

    return {
        "message": message,
        "agent": f"Reminder Agent · {route}",
        "escalated": False,
        "escalation": None,
    }



def build() -> AgentSpec:
    return AgentSpec(
        name="reminder_agent",
        description="Handles reminders, confirmations, reschedules, and dose timing.",
        matches=_matches,
        handle=_handle,
    )
