"""
@fileoverview Realtime API Routes - Endpunkte fuer die Live-Transkription

@description
Stellt Clients ein kurzlebiges Ticket fuer eine Live-Transkriptions-Session aus.
Der Audiostrom laeuft anschliessend direkt vom Client zum Provider; dieser Dienst
bleibt die einzige Stelle, die den API-Key kennt und Modell/Session-Vorgaben setzt.

Endpunkte:
- POST /api/realtime/transcription-session: Ticket fuer eine Live-Session
- POST /api/realtime/usage: Verbrauchsmeldung des Clients (Kostenauswertung)

@module api.routes.realtime_routes

@exports
- realtime_ns: Namespace - Flask-RESTX Namespace fuer Realtime-Endpunkte

@usedIn
- src.api.routes.__init__: Registriert realtime_ns

@dependencies
- External: flask, flask_restx
- Internal: src.core.llm.realtime_transcription - Ticket-Ausstellung
- Internal: src.core.exceptions - ProcessingError
"""
# pyright: reportMissingTypeStubs=false
from typing import Any, Dict, List, Tuple, Union

from flask import request
from flask_restx import Namespace, Resource, fields  # type: ignore

from src.core.exceptions import ProcessingError
from src.core.llm.realtime_transcription import (
    DEFAULT_TICKET_SECONDS,
    RealtimeTicketRequest,
    RealtimeTranscriptionService,
)
from src.utils.logger import get_logger

logger = get_logger(process_id="realtime-api")

realtime_ns = Namespace("realtime", description="Live-Transkription (Realtime-Sessions)")

session_request_model = realtime_ns.model("RealtimeSessionRequest", {
    "language": fields.String(description="Sprache des Sprechers (ISO 639-1). Leer/'auto' = automatisch."),
    "prompt": fields.String(description="Optionaler Hinweistext zur Fuehrung der Erkennung"),
    "keywords": fields.List(fields.String, description="Optionale Begriffe (Namen, Fachwoerter)"),
    "ticket_seconds": fields.Integer(description=f"Gueltigkeit des Tickets in Sekunden (Default {DEFAULT_TICKET_SECONDS})"),
})

_ERROR_STATUS = {
    "NO_MODEL_CONFIGURED": 503,
    "UPSTREAM_REJECTED": 502,
}


def _error(code: str, message: str, status: int) -> Tuple[Dict[str, Any], int]:
    """Baut eine Fehlerantwort im hausueblichen Format."""
    return {"status": "error", "error": {"code": code, "message": message}}, status


def _as_str_list(value: Any) -> List[str]:
    """Nimmt nur echte Strings aus einer Liste an — alles andere wird verworfen."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


@realtime_ns.route("/transcription-session")  # type: ignore
class TranscriptionSessionEndpoint(Resource):
    """Stellt ein Ticket fuer eine Live-Transkriptions-Session aus."""

    @realtime_ns.expect(session_request_model)  # type: ignore
    @realtime_ns.doc(description=(  # type: ignore
        "Gibt ein kurzlebiges Ticket zurueck, mit dem sich ein Client direkt mit dem "
        "Realtime-Endpunkt des Providers verbindet. Modell und Provider stammen aus der "
        "LLM-Konfiguration (Use-Case 'live_transcription')."
    ))
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}

        language_raw = payload.get("language")
        language = language_raw.strip() if isinstance(language_raw, str) else ""
        # 'auto' ist die hausuebliche Schreibweise fuer "nicht festlegen".
        if language.lower() in {"", "auto"}:
            language = ""

        prompt_raw = payload.get("prompt")
        prompt = prompt_raw.strip() if isinstance(prompt_raw, str) else ""

        ticket_seconds_raw = payload.get("ticket_seconds")
        ticket_seconds = (
            ticket_seconds_raw if isinstance(ticket_seconds_raw, int) else DEFAULT_TICKET_SECONDS
        )

        ticket_request = RealtimeTicketRequest(
            language=language or None,
            prompt=prompt or None,
            keywords=_as_str_list(payload.get("keywords")),
            ticket_seconds=ticket_seconds,
        )

        try:
            ticket = RealtimeTranscriptionService().create_ticket(ticket_request)
        except ProcessingError as e:
            message = str(e)
            code = "UPSTREAM_REJECTED" if "abgelehnt" in message else "NO_MODEL_CONFIGURED"
            logger.error(f"Realtime-Ticket nicht ausgestellt: {message}")
            return _error(code, message, _ERROR_STATUS[code])
        except Exception as e:
            logger.error(f"Unerwarteter Fehler bei der Ticket-Ausstellung: {str(e)}")
            return _error("INTERNAL_ERROR", str(e), 500)

        return {"status": "success", "data": ticket.to_dict()}


@realtime_ns.route("/usage")  # type: ignore
class RealtimeUsageEndpoint(Resource):
    """Nimmt die vom Client gemeldete Nutzung einer Live-Session entgegen."""

    @realtime_ns.doc(description=(  # type: ignore
        "Meldet Dauer und Token-Verbrauch einer beendeten Live-Session. Noetig, weil der "
        "Audiostrom nicht ueber diesen Dienst laeuft und der Verbrauch sonst unsichtbar bliebe."
    ))
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}

        model = payload.get("model")
        if not isinstance(model, str) or not model.strip():
            return _error("MISSING_MODEL", "Feld 'model' fehlt.", 400)

        audio_seconds = payload.get("audio_seconds")
        input_tokens = payload.get("input_tokens")
        output_tokens = payload.get("output_tokens")
        sessions = payload.get("sessions")

        logger.info(
            "Realtime-Nutzung gemeldet",
            model=model,
            audio_seconds=audio_seconds if isinstance(audio_seconds, (int, float)) else None,
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            sessions=sessions if isinstance(sessions, int) else None,
        )
        return {"status": "success", "data": {"recorded": True}}
