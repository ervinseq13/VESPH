import unittest
from unittest.mock import Mock, patch

from chat_service import answer_chat, is_connection_query
from data_store import load_demo_data
from integrations import (
    DEFAULT_GROQ_MODEL,
    IntegrationHub,
    IntegrationSettings,
)
from orchestrator.graph import build_orchestrator


class IntegrationSettingsTests(unittest.TestCase):
    def test_streamlit_secrets_take_priority_without_leaking_values(self) -> None:
        settings = IntegrationSettings.from_sources(
            {
                "LLM_API_KEY": "groq-private-value",
                "SUPABASE_URL": "https://example.supabase.co/",
                "SUPABASE_KEY": "supabase-private-value",
            },
            {"LLM_API_KEY": "environment-value"},
        )

        self.assertEqual(settings.groq_api_key, "groq-private-value")
        self.assertEqual(settings.groq_model, DEFAULT_GROQ_MODEL)
        self.assertEqual(settings.supabase_url, "https://example.supabase.co")

    def test_status_message_never_contains_secret_values(self) -> None:
        hub = IntegrationHub(
            IntegrationSettings(
                groq_api_key="groq-private-value",
                supabase_url="https://example.supabase.co",
                supabase_key="supabase-private-value",
            )
        )
        with patch.object(hub, "check_groq") as groq, patch.object(
            hub, "check_supabase"
        ) as supabase:
            groq.return_value = Mock(connected=False, detail="Needs configuration")
            supabase.return_value = Mock(connected=True, detail="Project reachable")
            message = hub.status_message()

        self.assertNotIn("groq-private-value", message)
        self.assertNotIn("supabase-private-value", message)
        self.assertIn("synthetic JSON", message)


class ChatRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load_demo_data()
        self.patient_id = self.data["patient"]["id"]
        self.graph = build_orchestrator()

    def test_connection_prompt_uses_status_route(self) -> None:
        integrations = Mock()
        integrations.status_message.return_value = "Groq and Supabase are connected."

        reply = answer_chat(
            self.graph,
            integrations,
            "Are the LLM and Supabase connections working?",
            self.data,
            self.patient_id,
            thread_id="connections",
        )

        self.assertTrue(is_connection_query("Check connections"))
        self.assertEqual(reply.agent, "System · Connection check")
        integrations.status_message.assert_called_once_with()

    def test_known_patient_route_does_not_call_groq(self) -> None:
        integrations = Mock()

        reply = answer_chat(
            self.graph,
            integrations,
            "When is my next appointment?",
            self.data,
            self.patient_id,
            thread_id="appointment",
        )

        self.assertIn("Reminder Agent", reply.agent)
        integrations.answer_with_groq.assert_not_called()

    def test_open_question_uses_groq_when_available(self) -> None:
        integrations = Mock()
        integrations.answer_with_groq.return_value = "A simple grounded explanation."
        integrations.settings.groq_model = DEFAULT_GROQ_MODEL

        reply = answer_chat(
            self.graph,
            integrations,
            "Can you explain this to me in plain language?",
            self.data,
            self.patient_id,
            thread_id="groq",
        )

        self.assertEqual(reply.message, "A simple grounded explanation.")
        self.assertIn(DEFAULT_GROQ_MODEL, reply.agent)

    def test_groq_failure_keeps_deterministic_fallback(self) -> None:
        integrations = Mock()
        integrations.answer_with_groq.return_value = None

        reply = answer_chat(
            self.graph,
            integrations,
            "Can you explain this to me in plain language?",
            self.data,
            self.patient_id,
            thread_id="fallback",
        )

        self.assertEqual(reply.agent, "Follow-up Assistant · Router")
        self.assertIn("appointments", reply.message.lower())


if __name__ == "__main__":
    unittest.main()
