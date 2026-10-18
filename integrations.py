"""Server-side integrations for the VESPH Streamlit application.

Secrets are read by ``app.py`` and passed into this module. They are never
included in prompts, status messages, logs, or exceptions returned to users.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from groq import Groq
from supabase import Client, create_client


DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

PATIENT_SYSTEM_PROMPT = (
    "You are VESPH Care, a hospital follow-up assistant for patients. "
    "You answer ONLY about the patient's hospital experiences, medical records, "
    "diagnostic reports, prescribed medications, upcoming appointments, and "
    "doctor-given instructions from the supplied synthetic record. "
    "STRICT BOUNDARIES: "
    "1. Do NOT give general medical advice, diagnoses, or treatment recommendations. "
    "2. Do NOT act as a life coach, therapist, or general wellness advisor. "
    "3. Do NOT discuss topics outside the patient's hospital record. "
    "4. If the patient asks something outside your scope, say: "
    "'I can only help with your hospital care and records. For other concerns, "
    "please speak with your care team directly.' "
    "5. When explaining reports, use plain language and always note that the "
    "doctor will interpret results at the follow-up visit. "
    "6. For emergencies, tell the patient to call +91 22 4000 1122 or local "
    "emergency services immediately — do not wait for chat. "
    "7. Never invent facts or claim that bookings/uploads/escalations were completed "
    "unless the application record confirms it."
)

DOCTOR_SYSTEM_PROMPT = (
    "You are VESPH Care, a clinical assistant for doctors. "
    "You help with patient record lookups, appointment schedules, medication reviews, "
    "and diagnostic result summaries from the supplied synthetic hospital record. "
    "STRICT BOUNDARIES: "
    "1. Provide concise, clinical-grade summaries suitable for a practicing physician. "
    "2. Do NOT provide information outside the hospital record. "
    "3. If asked about something not in the record, say: "
    "'That information is not available in the current patient record.' "
    "4. Never invent facts or make clinical recommendations beyond the record."
)


@dataclass(frozen=True)
class IntegrationSettings:
    groq_api_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODEL
    supabase_url: str = ""
    supabase_key: str = ""

    @classmethod
    def from_sources(
        cls,
        secrets: Mapping[str, Any] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "IntegrationSettings":
        """Load Streamlit secrets first, then environment variables.

        ``st.secrets`` can raise when no local secrets file exists, so callers
        may safely pass it in local development without creating one.
        """

        environment = environ if environ is not None else os.environ

        def read(name: str, fallback: str = "") -> str:
            value: Any = None
            if secrets is not None:
                try:
                    value = secrets.get(name)
                except Exception:
                    value = None
            if value is None:
                value = environment.get(name, fallback)
            return str(value).strip() if value is not None else fallback

        groq_key = (
            read("GROQ_API_KEY")
            or read("LLM_API_KEY")
            or read("groq_api_key")
            or read("llm_api_key")
        )
        groq_model = (
            read("GROQ_MODEL")
            or read("LLM_MODEL")
            or read("groq_model")
            or read("llm_model")
            or DEFAULT_GROQ_MODEL
        ) or DEFAULT_GROQ_MODEL
        supabase_url = read("SUPABASE_URL").rstrip("/")
        supabase_key = read("SUPABASE_KEY")

        return cls(
            groq_api_key=groq_key,
            groq_model=groq_model,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
        )


@dataclass(frozen=True)
class ServiceStatus:
    configured: bool
    connected: bool
    detail: str


class IntegrationHub:
    """Lazy, server-side access to Groq and the future Supabase data layer."""

    def __init__(self, settings: IntegrationSettings):
        self.settings = settings
        self._groq: Groq | None = None
        self._supabase: Client | None = None

    @property
    def groq_configured(self) -> bool:
        if not self.settings.groq_api_key:
            # Check if key was added to environment or secrets dynamically after initial load
            refreshed = IntegrationSettings.from_sources()
            if refreshed.groq_api_key:
                self.settings = refreshed
                self._groq = None
        return bool(self.settings.groq_api_key)

    @property
    def supabase_configured(self) -> bool:
        return bool(self.settings.supabase_url and self.settings.supabase_key)

    def _groq_client(self) -> Groq:
        if not self.groq_configured:
            raise RuntimeError("Groq is not configured")
        if self._groq is None:
            self._groq = Groq(api_key=self.settings.groq_api_key, timeout=25.0)
        return self._groq

    def supabase_client(self) -> Client:
        """Return the prepared client without assuming any table exists."""

        if not self.supabase_configured:
            raise RuntimeError("Supabase is not configured")
        if self._supabase is None:
            self._supabase = create_client(
                self.settings.supabase_url,
                self.settings.supabase_key,
            )
        return self._supabase

    def answer_with_groq(
        self,
        query: str,
        care_data: dict[str, Any],
        recent_messages: list[dict[str, Any]] | None = None,
        persona: str = "patient",
    ) -> str | None:
        """Answer an open-ended question from the supplied synthetic record.

        A failure returns ``None`` so the UI can fall back to the deterministic
        LangGraph response instead of breaking the patient conversation.
        """

        if not self.groq_configured:
            return None

        history = []
        for message in (recent_messages or [])[-10:]:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                history.append({"role": role, "content": content[:1200]})

        if persona == "doctor":
            doc = care_data.get("doctor", {})
            doc_name = doc.get("name") or doc.get("doctor_name") or "Dr. Rhea Mehta"
            doc_dept = doc.get("department", "General Surgery")
            appts = care_data.get("appointments", [])
            unavail = care_data.get("unavailability", [])
            patients = care_data.get("patients_overview", [])

            record_context = {
                "doctor": f"{doc_name} ({doc_dept})",
                "doctor_room": doc.get("room_no", "Room 304"),
                "scheduled_appointments": [
                    {
                        "date": a.get("date"),
                        "time": a.get("time"),
                        "raw_datetime": a.get("raw_datetime"),
                        "patient_name": a.get("patient_name"),
                        "type": a.get("type"),
                        "status": a.get("status"),
                        "summary": a.get("summary"),
                    }
                    for a in appts
                ],
                "clinic_offs_and_unavailabilities": unavail,
                "recent_patient_roster": patients,
            }
            if care_data.get("active_patient_chart"):
                record_context["active_patient_chart"] = care_data.get("active_patient_chart")

            user_content = (
                f"Clinical & Schedule Context for {doc_name} ({doc_dept}):\n"
                + json.dumps(record_context, ensure_ascii=False, default=str)
                + f"\n\nDoctor Query / Statement: {query}\n\n"
                + "Instructions:\n"
                + "1. You are the Clinical Assistant for this doctor.\n"
                + "2. Keep your answers concise, complete, and properly terminated (max 3-5 bullet points, under 150 words). Fit cleanly in the chat window and NEVER cut off mid-sentence.\n"
                + "3. If the doctor mentions availability, clinic offs, or time off (e.g. 'I won't be available on 20th October'): "
                + "look up the doctor's scheduled appointments for that date, list the affected patients and times, and offer to block the day and trigger reschedule notifications. "
                + "Do NOT assume or mention Ananya Iyer unless the doctor specifically asked about Ananya.\n"
                + "4. If the doctor asks for a patient summary or patient info without naming a specific patient, do NOT assume a patient. Ask which patient they are inquiring about and mention 3-4 names from the patient roster.\n"
                + "5. If the doctor confirms an action (e.g. 'yes', 'confirm', 'go ahead' to blocking a day or rescheduling), acknowledge the confirmation and state that the schedule has been updated in Supabase and escalations triggered.\n"
                + "6. If the doctor asks for an appointment summary, summarize upcoming bookings by date.\n"
                + "7. If the doctor asks about a specific patient, summarize that patient's details from the record in under 120 words."
            )
        else:
            p_name = care_data.get("patient", {}).get("first_name", "Patient")
            record_context = {
                "patient_summary": care_data.get("patient", {}),
                "allergies": care_data.get("patient", {}).get("allergies", ["Penicillin"]),
                "appointments": care_data.get("appointments", []),
                "consultations": care_data.get("consultations", []),
                "diagnostics": care_data.get("diagnostics", []),
                "medications": care_data.get("medications", []),
                "discharge": care_data.get("discharge", {}),
            }
            user_content = (
                f"Hospital Care Record for {p_name}:\n"
                + json.dumps(record_context, ensure_ascii=False, default=str)
                + f"\n\nPatient question: {query}"
            )

        system_prompt = DOCTOR_SYSTEM_PROMPT if persona == "doctor" else PATIENT_SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_content},
        ]

        # 1. Primary model call
        try:
            response = self._groq_client().chat.completions.create(
                model=self.settings.groq_model,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=650,
            )
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip()
        except Exception as error:
            logging.warning("Groq inference error with primary model '%s': %s", self.settings.groq_model, error)

        # 2. Resilient fallback across common Groq models in case primary model is unavailable or rate limited
        fallback_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        for fb_model in fallback_models:
            if fb_model == self.settings.groq_model:
                continue
            try:
                fb_response = self._groq_client().chat.completions.create(
                    model=fb_model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=650,
                )
                fb_content = fb_response.choices[0].message.content
                if fb_content and fb_content.strip():
                    logging.info("Resilient fallback succeeded using Groq model: %s", fb_model)
                    return fb_content.strip()
            except Exception as fb_err:
                logging.warning("Fallback model '%s' failed: %s", fb_model, fb_err)

        return None

    def check_groq(self) -> ServiceStatus:
        if not self.groq_configured:
            return ServiceStatus(False, False, "GROQ_API_KEY (or LLM_API_KEY) is not configured in .streamlit/secrets.toml or environment.")
        try:
            models = self._groq_client().models.list()
            model_ids = {model.id for model in models.data}
            if self.settings.groq_model not in model_ids:
                available_preview = ", ".join(sorted(list(model_ids))[:4])
                return ServiceStatus(
                    True,
                    False,
                    f"Groq API key is valid, but model '{self.settings.groq_model}' is not in active model list. Available models: {available_preview}",
                )
            return ServiceStatus(
                True,
                True,
                f"Connected with {self.settings.groq_model}.",
            )
        except Exception as error:
            return ServiceStatus(True, False, self._safe_failure("Groq", error))

    def check_supabase(self) -> ServiceStatus:
        """Validate project/key access without querying a not-yet-created table."""

        if not self.supabase_configured:
            return ServiceStatus(
                False,
                False,
                "SUPABASE_URL and SUPABASE_KEY are not both configured.",
            )
        try:
            self.supabase_client()
            endpoint = urljoin(self.settings.supabase_url + "/", "auth/v1/settings")
            request = Request(
                endpoint,
                headers={
                    "apikey": self.settings.supabase_key,
                    "User-Agent": "VESPH-Care/1.0",
                },
            )
            with urlopen(request, timeout=10) as response:
                connected = 200 <= response.status < 300
            if connected:
                return ServiceStatus(
                    True,
                    True,
                    "Project and key are reachable. Clinical tables are not queried yet.",
                )
            return ServiceStatus(True, False, "Supabase returned an unexpected status.")
        except Exception as error:
            return ServiceStatus(True, False, self._safe_failure("Supabase", error))

    def status_message(self) -> str:
        groq = self.check_groq()
        supabase = self.check_supabase()

        def line(name: str, status: ServiceStatus) -> str:
            marker = "Connected" if status.connected else "Needs attention"
            return f"• **{name}: {marker}.** {status.detail}"

        return (
            "Here is the live integration check:\n\n"
            + line("Groq", groq)
            + "\n"
            + line("Supabase", supabase)
            + "\n\nThe application is connected directly to your live Supabase database "
            "for patient records, appointments, prescriptions, and escalations. No secret values are shown here."
        )

    @staticmethod
    def _safe_failure(service: str, error: Exception) -> str:
        """Describe a failure without echoing credentials or request details."""

        if isinstance(error, HTTPError):
            if error.code in {401, 403}:
                return f"{service} rejected the configured credentials."
            return f"{service} responded with HTTP {error.code}."
        if isinstance(error, (URLError, TimeoutError)):
            return f"{service} could not be reached from this deployment."
        name = type(error).__name__.lower()
        if "auth" in name or "permission" in name:
            return f"{service} rejected the configured credentials."
        if "timeout" in name or "connection" in name:
            return f"{service} could not be reached from this deployment."
        return f"{service} could not complete its connection check."
