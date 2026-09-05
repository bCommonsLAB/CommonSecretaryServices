"""
@fileoverview Realtime Transcription Service - kurzlebige Tickets fuer die OpenAI Realtime API

@description
Baut die Session-Konfiguration fuer eine Live-Transkription und loest beim Provider
ein ephemeres Client-Secret ("Ticket") ein. Nur das Ticket geht an den Client; der
API-Key bleibt im Dienst.

Modell und Provider kommen NICHT aus einer Konstante, sondern aus der
LLM-Konfiguration (Maske -> MongoDB, config.yaml als Fallback) fuer den Use-Case
``live_transcription``. Ist dort nichts hinterlegt, wird ein Fehler geworfen — es
gibt bewusst keinen stillen Rueckfall auf den Batch-Use-Case ``transcription``.

@module core.llm.realtime_transcription

@exports
- RealtimeTicketRequest: Dataclass - Eingabe fuer die Ticket-Ausstellung
- RealtimeTicket: Dataclass - Ausgestelltes Ticket samt Verbindungsdaten
- RealtimeTranscriptionService: Service - Session-Konfiguration und Ticket-Ausstellung

@usedIn
- src.api.routes.realtime_routes: HTTP-Endpunkt fuer Clients

@dependencies
- External: requests - HTTP-Aufruf an den Provider
- Internal: src.core.llm.config_manager - Modell-/Provider-Zuordnung je Use-Case
- Internal: src.core.exceptions - ProcessingError
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger

from .config_manager import LLMConfigManager
from .use_cases import UseCase

logger = get_logger(process_id="realtime-transcription")

# Nur OpenAI bietet die Realtime-Transkription an. Ein anderer Provider in der Maske
# ist eine Fehlkonfiguration und wird gemeldet, nicht umgangen.
SUPPORTED_PROVIDER = "openai"

DEFAULT_API_BASE_URL = "https://api.openai.com/v1"

# Pfad fuer ephemere Client-Secrets (GA-Realtime).
CLIENT_SECRET_PATH = "/realtime/client_secrets"

# Die Session ist als Transkriptions-Session im Ticket hinterlegt; der Client
# verbindet sich mit dieser Absicht.
WEBSOCKET_QUERY = "intent=transcription"

# Realtime-Sessions enden serverseitig nach 60 Minuten. Der Client rotiert vorher,
# deshalb ist die Ticket-Gueltigkeit kurz: sie begrenzt nur den Verbindungsaufbau.
DEFAULT_TICKET_SECONDS = 120
MIN_TICKET_SECONDS = 10
MAX_TICKET_SECONDS = 7200

# Modelle, die laut Provider-Vertrag keine serverseitige Sprechpausen-Erkennung
# annehmen: dort MUSS turn_detection null sein.
MODELS_WITHOUT_TURN_DETECTION = frozenset({"gpt-realtime-whisper"})

# Zeitlimit fuer den Ticket-Aufruf beim Provider.
REQUEST_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class RealtimeTicketRequest:
    """Eingabe fuer die Ticket-Ausstellung."""

    language: Optional[str] = None
    prompt: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    noise_reduction: Optional[str] = "near_field"
    ticket_seconds: int = DEFAULT_TICKET_SECONDS
    include_logprobs: bool = False


@dataclass(frozen=True)
class RealtimeTicket:
    """Ausgestelltes Ticket samt allem, was der Client zum Verbinden braucht."""

    value: str
    expires_at: Optional[int]
    model: str
    provider: str
    websocket_url: str
    session: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "expires_at": self.expires_at,
            "model": self.model,
            "provider": self.provider,
            "websocket_url": self.websocket_url,
            "session": self.session,
        }


class RealtimeTranscriptionService:
    """Stellt Tickets fuer Live-Transkriptions-Sessions aus."""

    def __init__(self, config_manager: Optional[LLMConfigManager] = None) -> None:
        self._config_manager = config_manager or LLMConfigManager()

    def resolve_model(self) -> str:
        """Liefert das in der Maske zugeordnete Modell fuer ``live_transcription``."""
        use_case_config = self._config_manager.get_use_case_config(UseCase.LIVE_TRANSCRIPTION)
        if not use_case_config:
            raise ProcessingError(
                "Fuer den Use-Case 'live_transcription' ist kein Modell zugeordnet. "
                "Bitte in der LLM-Konfiguration (Maske) ein realtime-faehiges Modell waehlen."
            )
        if use_case_config.provider != SUPPORTED_PROVIDER:
            raise ProcessingError(
                f"Live-Transkription ist nur mit Provider '{SUPPORTED_PROVIDER}' moeglich, "
                f"konfiguriert ist '{use_case_config.provider}'."
            )
        return use_case_config.model

    def build_session_config(self, request: RealtimeTicketRequest, model: str) -> Dict[str, Any]:
        """Baut die Session-Konfiguration fuer eine Transkriptions-Session."""
        transcription: Dict[str, Any] = {"model": model}
        if request.language:
            transcription["language"] = request.language
        if request.prompt:
            transcription["prompt"] = request.prompt
        if request.keywords:
            transcription["keywords"] = list(request.keywords)

        audio_input: Dict[str, Any] = {
            # Die Realtime-API nimmt ausschliesslich 24-kHz-PCM entgegen.
            "format": {"type": "audio/pcm", "rate": 24000},
            "transcription": transcription,
            "turn_detection": (
                None if model in MODELS_WITHOUT_TURN_DETECTION else {"type": "server_vad"}
            ),
        }
        if request.noise_reduction:
            audio_input["noise_reduction"] = {"type": request.noise_reduction}

        session: Dict[str, Any] = {
            "type": "transcription",
            "audio": {"input": audio_input},
        }
        if request.include_logprobs:
            session["include"] = ["item.input_audio_transcription.logprobs"]
        return session

    def create_ticket(self, request: RealtimeTicketRequest) -> RealtimeTicket:
        """Loest beim Provider ein ephemeres Client-Secret ein."""
        model = self.resolve_model()
        provider_config = self._config_manager.get_provider_config(SUPPORTED_PROVIDER)
        if not provider_config or not provider_config.enabled:
            raise ProcessingError(f"Provider '{SUPPORTED_PROVIDER}' ist nicht verfuegbar.")
        api_key = provider_config.api_key
        if not api_key or api_key == "not-configured":
            raise ProcessingError(
                f"Fuer Provider '{SUPPORTED_PROVIDER}' ist kein API-Key gesetzt "
                "(Umgebungsvariable OPENAI_API_KEY)."
            )

        seconds = max(MIN_TICKET_SECONDS, min(MAX_TICKET_SECONDS, request.ticket_seconds))
        session = self.build_session_config(request, model)
        payload: Dict[str, Any] = {
            "expires_after": {"anchor": "created_at", "seconds": seconds},
            "session": session,
        }

        base_url = (provider_config.base_url or DEFAULT_API_BASE_URL).rstrip("/")
        response = requests.post(
            f"{base_url}{CLIENT_SECRET_PATH}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            # Antworttext mitgeben (er nennt z.B. ein Modell, das keine Realtime-Session kann),
            # aber gekuerzt, damit keine ganzen Payloads im Log landen.
            raise ProcessingError(
                f"Realtime-Ticket abgelehnt (HTTP {response.status_code}): {response.text[:400]}"
            )

        data: Dict[str, Any] = response.json()
        value = data.get("value")
        if not isinstance(value, str) or not value:
            raise ProcessingError("Antwort des Providers enthaelt kein Ticket ('value').")

        expires_at = data.get("expires_at")
        logger.info(f"Realtime-Ticket ausgestellt (Modell={model}, Gueltigkeit={seconds}s)")
        return RealtimeTicket(
            value=value,
            expires_at=expires_at if isinstance(expires_at, int) else None,
            model=model,
            provider=SUPPORTED_PROVIDER,
            websocket_url=_websocket_url(base_url),
            session=session,
        )


def _websocket_url(base_url: str) -> str:
    """Leitet die WebSocket-Adresse aus der Provider-Basis-URL ab."""
    ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_base}/realtime?{WEBSOCKET_QUERY}"
