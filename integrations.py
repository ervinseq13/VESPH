"""Server-side integrations for the VESPH Streamlit application.

Secrets are read by ``app.py`` and passed into this module. They are never
included in prompts, status messages, logs, or exceptions returned to users.

Groq is an answer-generation fallback outside the LangGraph specialist graph.
Supabase is currently connectivity-tested only; the synthetic JSON/session
record remains the clinical source until tables and row-level security exist.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from groq import Groq
from supabase import Client, create_client


DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"


@dataclass(frozen=True)
class IntegrationSettings:
    """Secret-backed server configuration with no network side effects."""

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

        return cls(
            groq_api_key=read("LLM_API_KEY"),
            groq_model=read("GROQ_MODEL", DEFAULT_GROQ_MODEL)
            or DEFAULT_GROQ_MODEL,
            supabase_url=read("SUPABASE_URL").rstrip("/"),
            supabase_key=read("SUPABASE_KEY"),
        )


@dataclass(frozen=True)
class ServiceStatus:
    """Secret-safe connection result that can be displayed in patient chat."""

    configured: bool
    connected: bool
    detail: str


class IntegrationHub:
    """Lazy, server-side access to Groq and the future Supabase data layer.

    Constructing the hub does not contact either service. Network access starts
    only when an answer or explicit connection check requests a client method.
    """

    def __init__(self, settings: IntegrationSettings):
        self.settings = settings
        self._groq: Groq | None = None
        self._supabase: Client | None = None

    @property
    def groq_configured(self) -> bool:
        return bool(self.settings.groq_api_key)

    @property
    def supabase_configured(self) -> bool:
        return bool(self.settings.supabase_url and self.settings.supabase_key)

    def _groq_client(self) -> Groq:
        if not self.groq_configured:
            raise RuntimeError("Groq is not configured")
        if self._groq is None:
            self._groq = Groq(api_key=self.settings.groq_api_key, timeout=12.0)
        return self._groq

    def supabase_client(self) -> Client:
        """Return the prepared client without assuming or querying any table.

        This is the future clinical-data seam. Current agent handlers still
        receive the synthetic record through ``OrchestratorContext``.
        """

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
    ) -> str | None:
        """Answer an open-ended question from the supplied synthetic record.

        This method makes an external Groq API request using a bounded synthetic
        record snapshot and recent chat context. It does not write patient data,
        update bookings, or persist the generated answer. A failure returns
        ``None`` so the UI can fall back to the deterministic LangGraph response
        instead of breaking the patient conversation.
        """

        if not self.groq_configured:
            return None

        record_context = {
            "patient_summary": care_data.get("patient", {}),
            "appointments": care_data.get("appointments", []),
            "diagnostics": care_data.get("diagnostics", []),
            "medications": care_data.get("medications", []),
            "discharge": care_data.get("discharge", {}),
        }
        history = []
        for message in (recent_messages or [])[-6:]:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                history.append({"role": role, "content": content[:1200]})

        system_prompt = (
            "You are the VESPH Care patient follow-up assistant for a capstone "
            "prototype. Answer only from the supplied synthetic hospital record. "
            "Do not invent facts, diagnose, or recommend starting, stopping, or "
            "changing treatment. If the record does not answer the question, say "
            "so and suggest the relevant hospital team. Keep the response concise "
            "and patient-friendly. For possible emergencies, tell the patient not "
            "to wait for chat and to call the hospital emergency number or local "
            "emergency services. Never claim that a booking, upload, or escalation "
            "was completed unless the application record says it was."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {
                "role": "user",
                "content": (
                    "Synthetic patient record:\n"
                    + json.dumps(record_context, ensure_ascii=False, default=str)
                    + "\n\nPatient question: "
                    + query
                ),
            },
        ]

        try:
            response = self._groq_client().chat.completions.create(
                model=self.settings.groq_model,
                messages=messages,
                temperature=0.2,
                max_completion_tokens=420,
            )
            content = response.choices[0].message.content
            return content.strip() if content else None
        except Exception:
            return None

    def check_groq(self) -> ServiceStatus:
        """Make a live model-list request without sending patient information."""

        if not self.groq_configured:
            return ServiceStatus(False, False, "LLM_API_KEY is not configured.")
        try:
            models = self._groq_client().models.list()
            model_ids = {model.id for model in models.data}
            if self.settings.groq_model not in model_ids:
                return ServiceStatus(
                    True,
                    False,
                    f"Groq is reachable, but {self.settings.groq_model} is unavailable.",
                )
            return ServiceStatus(
                True,
                True,
                f"Connected with {self.settings.groq_model}.",
            )
        except Exception as error:
            return ServiceStatus(True, False, self._safe_failure("Groq", error))

    def check_supabase(self) -> ServiceStatus:
        """Validate project/key access without querying a clinical table.

        The request targets Supabase Auth settings only. A successful result
        proves project/key reachability, not that future schemas or RLS policies
        are ready for patient data.
        """

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
        """Run both live checks and format secret-safe results for chat."""

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
            + "\n\nThe app is currently reading the synthetic JSON records. Supabase "
            "will become the clinical source only after the tables and row-level "
            "security rules are finalized. No secret values are shown here."
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
