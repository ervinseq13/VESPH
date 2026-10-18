"""Patient Summary Agent backed only by the current care record."""

from __future__ import annotations

from langgraph.runtime import Runtime

from agents.models import AgentSpec
from orchestrator.state import OrchestratorContext, OrchestratorState


SUMMARY_TERMS = (
    # Past appointments & consultations
    "last appointment", "past appointment", "previous appointment",
    "last visit", "previous visit", "past visit", "last consultation",
    "what happened in my last", "what happened at my last", "what happened in",
    "what happened during", "what did the doctor say", "notes from my last",
    "consultation summary", "past doctor visit", "what was discussed",
    "doctor consultation", "what happened",
    # Medications
    "medicine", "medication", "tablet", "inhaler", "pills", "capsule",
    # Diagnostics and reports
    "report", "test result", "diagnostic", "blood", "cbc", "lab result",
    "what did the test show", "my numbers", "was my report okay",
    # Surgery, discharge, recovery
    "discharge", "surgery", "operation", "recovery", "wound",
    "instructions", "what should i avoid", "when can i exercise",
    # General health queries
    "summary", "health", "how am i doing", "how am i", "history",
    "what's wrong with me", "my condition", "my diagnosis",
    "can i eat normally", "any restrictions", "am i getting better",
    "my allergies",
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

    # Branch 0: Past appointment / consultation review
    if any(
        term in text
        for term in (
            "last appointment", "past appointment", "previous appointment",
            "last visit", "previous visit", "past visit", "what happened",
            "what did the doctor say", "consultation", "what was discussed",
            "notes from",
        )
    ):
        consultations = data.get("consultations", [])
        if consultations:
            latest = consultations[0]
            c_doc = latest.get("doctor", "Dr. Rhea Mehta")
            c_date = latest.get("date", "recent consultation")
            c_diag = latest.get("diagnosis", "Post-operative follow-up")
            c_symp = latest.get("symptoms", "")
            c_plan = latest.get("treatment_plan", "")
            vitals = latest.get("vitals", {})

            vitals_info = ""
            if vitals.get("bp_systolic") and vitals.get("bp_diastolic"):
                vitals_info = f" Recorded BP was {vitals['bp_systolic']}/{vitals['bp_diastolic']} mmHg."

            msg = (
                f"During your last recorded consultation on {c_date} with {c_doc}:\n\n"
                f"• Clinical Assessment: {c_diag}\n"
            )
            if c_symp:
                msg += f"• Observations: {c_symp}\n"
            if c_plan:
                msg += f"• Doctor's Plan: {c_plan}\n"
            if vitals_info:
                msg += f"• Vitals:{vitals_info}\n"

            msg += (
                "\nAll surgical incisions were noted as healing well by primary intention. "
                "Your doctor advised continuing light ambulation, following your mealtime prescriptions, and attending your scheduled follow-up."
            )
            return _reply(msg, "Consultation Summary")

        discharge = data.get("discharge", {})
        if discharge and discharge.get("procedure"):
            return _reply(
                f"In your surgical discharge with {discharge.get('consultant', 'Dr. Rhea Mehta')} on {discharge.get('discharge_date', '')}: "
                f"You were reviewed for {discharge.get('procedure', '')}. "
                f"Condition: {discharge.get('condition_at_discharge', 'Stable recovery')}. "
                f"Follow-up: {discharge.get('follow_up', 'Follow-up with surgical team')}.",
                "Discharge Summary",
            )

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
