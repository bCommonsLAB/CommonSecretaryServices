"""Tests fuer die Ticket-Ausstellung der Live-Transkription.

Geprueft wird, dass (a) die Session-Konfiguration das von der Realtime-API geforderte
Audioformat setzt, (b) Modelle ohne Sprechpausen-Erkennung diese auf null setzen,
(c) eine fehlende oder fremde Use-Case-Zuordnung laut fehlschlaegt statt still auf den
Batch-Use-Case auszuweichen, und (d) ein erfolgreicher Provider-Aufruf ein Ticket ergibt.
"""

import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from src.core.exceptions import ProcessingError
from src.core.llm.realtime_transcription import (
    RealtimeTicketRequest,
    RealtimeTranscriptionService,
)
from src.core.models.llm_config import ProviderConfig, UseCaseConfig


def _service(
    use_case: Optional[UseCaseConfig],
    provider: Optional[ProviderConfig] = None,
) -> RealtimeTranscriptionService:
    """Baut den Service mit einem vorgegebenen Konfigurationsstand."""
    config_manager = MagicMock()
    config_manager.get_use_case_config.return_value = use_case
    config_manager.get_provider_config.return_value = provider
    return RealtimeTranscriptionService(config_manager=config_manager)


_OPENAI_USE_CASE = UseCaseConfig(
    use_case="live_transcription", provider="openai", model="gpt-4o-transcribe"
)
_OPENAI_PROVIDER = ProviderConfig(name="openai", api_key="sk-test", enabled=True)


class TestSessionConfig(unittest.TestCase):
    """Prueft die Session-Konfiguration."""

    def test_uses_pcm_24k_and_server_vad(self) -> None:
        service = _service(_OPENAI_USE_CASE)
        session = service.build_session_config(
            RealtimeTicketRequest(language="de"), "gpt-4o-transcribe"
        )

        audio_input: Dict[str, Any] = session["audio"]["input"]
        self.assertEqual(session["type"], "transcription")
        self.assertEqual(audio_input["format"], {"type": "audio/pcm", "rate": 24000})
        self.assertEqual(audio_input["transcription"]["model"], "gpt-4o-transcribe")
        self.assertEqual(audio_input["transcription"]["language"], "de")
        self.assertEqual(audio_input["turn_detection"], {"type": "server_vad"})
        self.assertEqual(audio_input["noise_reduction"], {"type": "near_field"})

    def test_omits_language_when_not_given(self) -> None:
        service = _service(_OPENAI_USE_CASE)
        session = service.build_session_config(RealtimeTicketRequest(), "gpt-4o-transcribe")

        self.assertNotIn("language", session["audio"]["input"]["transcription"])

    def test_turn_detection_is_null_for_models_without_vad(self) -> None:
        service = _service(_OPENAI_USE_CASE)
        session = service.build_session_config(
            RealtimeTicketRequest(), "gpt-realtime-whisper"
        )

        self.assertIsNone(session["audio"]["input"]["turn_detection"])

    def test_keywords_and_prompt_are_passed_through(self) -> None:
        service = _service(_OPENAI_USE_CASE)
        session = service.build_session_config(
            RealtimeTicketRequest(prompt="Fachbegriffe erwarten", keywords=["Nextcloud"]),
            "gpt-4o-transcribe",
        )

        transcription = session["audio"]["input"]["transcription"]
        self.assertEqual(transcription["prompt"], "Fachbegriffe erwarten")
        self.assertEqual(transcription["keywords"], ["Nextcloud"])


class TestModelResolution(unittest.TestCase):
    """Prueft, dass Fehlkonfigurationen laut fehlschlagen."""

    def test_raises_when_use_case_not_configured(self) -> None:
        service = _service(None)

        with self.assertRaises(ProcessingError) as ctx:
            service.resolve_model()
        self.assertIn("live_transcription", str(ctx.exception))

    def test_raises_for_foreign_provider(self) -> None:
        service = _service(
            UseCaseConfig(use_case="live_transcription", provider="mistral", model="whatever")
        )

        with self.assertRaises(ProcessingError):
            service.resolve_model()

    def test_raises_when_api_key_missing(self) -> None:
        service = _service(
            _OPENAI_USE_CASE,
            ProviderConfig(name="openai", api_key="not-configured", enabled=True),
        )

        with self.assertRaises(ProcessingError):
            service.create_ticket(RealtimeTicketRequest())


class TestTicketCreation(unittest.TestCase):
    """Prueft den Provider-Aufruf."""

    def test_returns_ticket_on_success(self) -> None:
        service = _service(_OPENAI_USE_CASE, _OPENAI_PROVIDER)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"value": "ek_test", "expires_at": 1800000000}

        with patch("src.core.llm.realtime_transcription.requests.post", return_value=response) as post:
            ticket = service.create_ticket(RealtimeTicketRequest(language="de", ticket_seconds=90))

        self.assertEqual(ticket.value, "ek_test")
        self.assertEqual(ticket.model, "gpt-4o-transcribe")
        self.assertTrue(ticket.websocket_url.startswith("wss://"))
        self.assertIn("intent=transcription", ticket.websocket_url)

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["expires_after"], {"anchor": "created_at", "seconds": 90})
        self.assertEqual(payload["session"]["type"], "transcription")

    def test_clamps_ticket_lifetime(self) -> None:
        service = _service(_OPENAI_USE_CASE, _OPENAI_PROVIDER)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"value": "ek_test", "expires_at": None}

        with patch("src.core.llm.realtime_transcription.requests.post", return_value=response) as post:
            service.create_ticket(RealtimeTicketRequest(ticket_seconds=1))

        self.assertEqual(post.call_args.kwargs["json"]["expires_after"]["seconds"], 10)

    def test_raises_on_upstream_error(self) -> None:
        service = _service(_OPENAI_USE_CASE, _OPENAI_PROVIDER)
        response = MagicMock()
        response.status_code = 400
        response.text = '{"error": {"message": "unsupported model"}}'

        with patch("src.core.llm.realtime_transcription.requests.post", return_value=response):
            with self.assertRaises(ProcessingError) as ctx:
                service.create_ticket(RealtimeTicketRequest())

        self.assertIn("unsupported model", str(ctx.exception))

    def test_raises_when_response_has_no_ticket(self) -> None:
        service = _service(_OPENAI_USE_CASE, _OPENAI_PROVIDER)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"expires_at": 1800000000}

        with patch("src.core.llm.realtime_transcription.requests.post", return_value=response):
            with self.assertRaises(ProcessingError):
                service.create_ticket(RealtimeTicketRequest())


if __name__ == "__main__":
    unittest.main()
