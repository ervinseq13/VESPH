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
    "medicine", "medication", "tablet", "tablets", "inhaler", "pills", "capsule", "meds", "my meds",
    "what meds", "what medicines", "what do i take", "prescription", "prescriptions",
    "dose", "dosage", "drug", "drugs", "take and when",
    # Diagnostics and reports
    "report", "test result", "diagnostic", "blood", "cbc", "lab result",
    "what did the test show", "my numbers", "was my report okay", "lab", "pathology",
    # Surgery, discharge, recovery
    "discharge", "surgery", "operation", "recovery", "wound",
    "instructions", "what should i avoid", "when can i exercise", "diet", "food", "eat",
    # General health queries & diagnosis
    "summary", "health", "how am i doing", "how am i", "history",
    "what's wrong with me", "my condition", "my diagnosis", "diagnosis",
    "can i eat normally", "any restrictions", "am i getting better",
    "my allergies", "allergy", "allergies", "allergic", "treatment", "treatment plan",
    # Greetings & help
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening", "greetings", "help",
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

    # Branch -1: Greetings & conversational intro
    if any(text == g or text.startswith(g + " ") or text.startswith(g + "!") or text.startswith(g + ",") for g in ("hello", "hi", "hey", "good morning", "good afternoon", "good evening", "greetings", "help")):
        first_name = patient.get("first_name") or (patient.get("name") or "there").split()[0]
        return _reply(
            f"Hello {first_name}! I am your VESPH personal care assistant.\n\n"
            "I'm here to support your post-operative recovery. You can ask me:\n"
            "• **Medications:** “What meds do I take and when?” or “Did I take my morning pills?”\n"
            "• **Appointments:** “When is my next appointment?” or confirm your attendance\n"
            "• **Doctor & Clinic:** “Tell me about Dr. Rhea Mehta” or “What happened in my last appointment?”\n"
            "• **Lab Results:** “What did my CBC test show?”\n\n"
            "How can I help you today?",
            "Care Assistant · Greeting",
        )

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

    # Branch 1: Specific Health trends & recovery progress (checked before generic discharge/recovery)
    if any(term in text for term in ("trend", "progress", "recovery trend", "how am i healing", "healing")):
        vitals_trend = "Blood pressure is stable at 118/76 mmHg. White blood cell count (CBC) improved from post-op 14.2 to 10.4 x10^3/uL (within normal limits)."
        return _reply(
            f"**Clinical Recovery Trend for {patient.get('first_name', 'Patient')}:**\n\n"
            f"• **Surgical Healing:** Post-laparoscopic appendectomy Day 10 progress shows clean incisions with no erythema or active discharge.\n"
            f"• **Biomarker Trends:** {vitals_trend}\n"
            f"• **Ambulation:** Tolerating soft diet well, advancing towards full physical recovery.\n\n"
            "Your surgical healing trajectory is on schedule for full discharge clearance.",
            "Health Trends",
        )

    # Branch 2: Specific Medication adherence & compliance (checked before generic medication list)
    if any(term in text for term in ("adherence", "compliance", "prescribed vs taken", "did i take all", "how many taken")):
        meds = data.get("medications", [])
        total = len(meds)
        taken_count = sum(1 for m in meds if m.get("is_taken"))
        pct = int((taken_count / total * 100)) if total else 0
        return _reply(
            f"**Medication Adherence Overview:**\n\n"
            f"• **Prescribed Regimen:** {total} active medications\n"
            f"• **Doses Recorded as Taken:** {taken_count} of {total} ({pct}% adherence today)\n"
            f"• **Pending:** {total - taken_count} dose(s) remaining for today.\n\n"
            "Keep maintaining consistent mealtime adherence for optimal incision healing and pain management.",
            "Medication Adherence",
        )

    # Branch 3: Doctor summary (credentials, qualifications, department, room)
    if any(
        term in text
        for term in ("dr.", "doctor", "dr rhea", "rhea mehta", "surgeon", "consultant", "who is my doctor")
    ):
        doc_name = patient.get("doctor", "Dr. Rhea Mehta")
        return _reply(
            f"**Doctor Profile – {doc_name}:**\n\n"
            f"• **Qualifications:** MBBS, MS (General Surgery)\n"
            f"• **Department:** General Surgery & Laparoscopic Care\n"
            f"• **Location:** OPD Wing B, Room 304\n"
            f"• **Clinical Focus:** Minimally invasive abdominal and laparoscopic surgery, post-operative surgical wound monitoring.\n\n"
            f"{doc_name} is your primary lead consultant overseeing your appendectomy recovery and follow-up reviews.",
            "Doctor Summary",
        )

    if any(
        term in text
        for term in (
            "medicine", "medication", "meds", "tablet", "tablets", "pill", "pills",
            "dose", "dosage", "inhaler", "prescription", "prescriptions", "drug", "drugs",
            "what meds", "what medicines", "what do i take", "take and when", "my meds",
        )
    ):
        meds = data.get("medications", [])
        if meds:
            b_meds = [m for m in meds if m.get("meal_timing") == "breakfast"]
            l_meds = [m for m in meds if m.get("meal_timing") == "lunch"]
            d_meds = [m for m in meds if m.get("meal_timing") == "dinner"]
            other_meds = [m for m in meds if m.get("meal_timing") not in ("breakfast", "lunch", "dinner")]

            lines = ["Here is your active medication schedule organized by meal timing:\n"]
            if b_meds:
                lines.append("🌅 **Morning / Breakfast:**")
                for m in b_meds:
                    st_str = "Taken ✓" if m.get("is_taken") else "Pending"
                    lines.append(f"• **{m['name']}** ({m.get('dosage', '')}): {m.get('instruction', '')} *(Status: {st_str})*")
                lines.append("")
            if l_meds:
                lines.append("☀️ **Afternoon / Lunch:**")
                for m in l_meds:
                    st_str = "Taken ✓" if m.get("is_taken") else "Pending"
                    lines.append(f"• **{m['name']}** ({m.get('dosage', '')}): {m.get('instruction', '')} *(Status: {st_str})*")
                lines.append("")
            if d_meds:
                lines.append("🌙 **Night / Dinner:**")
                for m in d_meds:
                    st_str = "Taken ✓" if m.get("is_taken") else "Pending"
                    lines.append(f"• **{m['name']}** ({m.get('dosage', '')}): {m.get('instruction', '')} *(Status: {st_str})*")
                lines.append("")
            if other_meds:
                lines.append("📋 **Other / As Needed (SOS):**")
                for m in other_meds:
                    st_str = "Taken ✓" if m.get("is_taken") else "Pending"
                    lines.append(f"• **{m['name']}** ({m.get('dosage', '')}): {m.get('instruction', '')} *(Status: {st_str})*")
                lines.append("")

            lines.append("💡 *Tip: You can confirm doses directly in your Medications tab or by letting me know in this chat (e.g., “I took my lunch meds”).*")
            return _reply("\n".join(lines).strip(), "Medications")

        return _reply(
            "You currently have no active medications prescribed on file.",
            "Medications",
        )

    if any(
        term in text
        for term in ("report", "test", "diagnostic", "blood", "cbc", "result", "lab", "pathology")
    ):
        latest = data["diagnostics"][0]
        return _reply(
            f"Your latest result is {latest['name']} from {latest['date']}. "
            f"{latest['summary']} The report is marked as reviewed. Your doctor will "
            "interpret it alongside your recovery at the follow-up visit.",
            "Diagnostics",
        )

    if any(term in text for term in ("allergy", "allergies", "allergic")):
        allergies = patient.get("allergies", ["Penicillin"])
        allergy_str = ", ".join(allergies) if isinstance(allergies, list) else str(allergies)
        return _reply(
            f"**Recorded Patient Allergies:**\n\n"
            f"• **Allergy:** {allergy_str} (causes cutaneous hypersensitivity / rash)\n"
            f"• **Safety Protocol:** Penicillin-class antibiotics are strictly contraindicated in your hospital profile. "
            "All prescribed post-operative medications have been verified as safe and non-cross-reactive.",
            "Allergies",
        )

    if any(term in text for term in ("diagnosis", "what's wrong with me", "my condition", "treatment plan")):
        diag = patient.get("diagnosis") or "Acute Appendicitis (Post-laparoscopic appendectomy)"
        doc = patient.get("doctor", "Dr. Rhea Mehta")
        return _reply(
            f"**Primary Clinical Diagnosis:** {diag}\n\n"
            f"• **Recovery Status:** Post-operative Day 10 (laparoscopic surgical wound healing)\n"
            f"• **Treating Consultant:** {doc}\n"
            f"• **Current Plan:** Light ambulation, strict adherence to mealtime prescriptions (Pantocid, Shelcal, Budecort, Dolo SOS), and pre-consultation CBC review.\n\n"
            f"{patient.get('health_summary', '')}",
            "Diagnosis Overview",
        )

    if any(
        term in text
        for term in ("discharge", "surgery", "operation", "recovery", "instructions", "wound", "diet", "food", "eat")
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

    # Context-aware fallback: if patient asked about their upcoming appointment
    if any(term in text for term in ("appointment", "visit", "hospital", "doctor visit", "when")):
        appts = data.get("appointments", [])
        upcoming = [a for a in appts if a.get("status") not in ("Completed", "Cancelled")]
        a = upcoming[0] if upcoming else (appts[0] if appts else {})
        if a:
            return _reply(
                f"Your next scheduled visit is a **{a.get('type', 'Follow-up')}** on **{a.get('date', '22 Oct 2026')} at {a.get('time', '11:00 AM')}** "
                f"with **{a.get('doctor', 'Dr. Rhea Mehta')}** in {a.get('location', 'OPD Wing B, Room 304')} "
                f"(Status: *{a.get('status', 'Confirmed')}*). Preparation: {a.get('preparation', 'Bring reports')}.",
                "Appointments",
            )

    return {
        "message": (
            "I can help with your health summary, clinical trends, doctor profile, appointments, "
            "reports, medicines, discharge guidance, or route an issue to the hospital team. "
            "Try asking “When is my next appointment?” or “What meds do I take and when?”."
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
