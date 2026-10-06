"""
@fileoverview Transcript Routes - POST /api/transcript/korrekturvorschlag

@description
Textschritt zwischen Transkript und Vorlage: Transkript plus Begleittexte ergeben
Vorschlaege fuer Ersetzungen (Hoerfehler bei Namen, Zahlen, Fachbegriffen) und die
Zuordnung Sprecher-Label -> Person. Nur Vorschlaege — geschrieben wird hier nichts;
das bestaetigt der Mensch im KnowledgeScout (transkript_korrigieren).

Eingabe (JSON):
    { "transkript": "...", "begleittexte": [{"name": "...", "text": "..."}], "zielsprache": "de" }

Ausgabe:
    { "status": "success", "data": { "ersetzungen": [...], "sprecher": [...], "verworfen": [...],
      "modell": "...", "tokens": 0, "dauer_ms": 0.0 } }

@module api.routes.transcript_routes

@exports
- transcript_ns: Namespace

@usedIn
- src.api.routes.__init__: registriert transcript_ns unter /transcript
"""
# pyright: reportMissingTypeStubs=false
# type: ignore
from typing import Any, Dict, List, Optional, Tuple, Union

from flask import request
from flask_restx import Namespace, Resource, fields

from src.core.exceptions import ProcessingError
from src.core.transcript.korrekturvorschlag import Begleittext
from src.core.transcript.korrekturvorschlag_service import (
    INVALID_LLM_RESPONSE,
    NO_MODEL_CONFIGURED,
    KorrekturvorschlagService,
)
from src.utils.logger import get_logger

logger = get_logger(process_id="transcript-api")

transcript_ns = Namespace("transcript", description="Textschritte am Transkript (nur Vorschlaege)")

begleittext_model = transcript_ns.model("Begleittext", {
    "name": fields.String(required=True, description="Bezeichnung, z.B. Einladung oder Folien Vortrag 1"),
    "text": fields.String(required=True, description="Volltext (Markdown oder Klartext)"),
})
request_model = transcript_ns.model("KorrekturvorschlagRequest", {
    "transkript": fields.String(required=True, description="Audio-Transkript (Markdown), optional mit Sprecher-Praefixen"),
    "begleittexte": fields.List(fields.Nested(begleittext_model), description="Einladung, Folien-Transkripte"),
    "zielsprache": fields.String(description="Sprache der Begruendungen (ISO 639-1), Default de"),
})

_ERROR_STATUS = {NO_MODEL_CONFIGURED: 503, INVALID_LLM_RESPONSE: 502, "INPUT_TOO_LARGE": 413}


def _error(code: str, message: str, status: int, details: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    return {"status": "error", "error": {"code": code, "message": message, "details": details}}, status


def parse_begleittexte(raw: Any) -> List[Begleittext]:
    """Liest die Begleittexte; Eintraege ohne Name oder Text sind ein Fehler, kein stilles Weglassen."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("begleittexte muss eine Liste von {name, text} sein")
    result: List[Begleittext] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"begleittexte[{i}] ist kein Objekt")
        name, text = str(item.get("name") or "").strip(), str(item.get("text") or "")
        if not name or not text.strip():
            raise ValueError(f"begleittexte[{i}] braucht name und text")
        result.append(Begleittext(name=name, text=text))
    return result


@transcript_ns.route("/korrekturvorschlag")
class KorrekturvorschlagEndpoint(Resource):
    """Vorschlaege fuer Ersetzungen und Sprecher-Zuordnung; schreibt nichts."""

    @transcript_ns.expect(request_model)
    @transcript_ns.doc(description=(
        "Haelt ein Transkript gegen Begleittexte und schlaegt Ersetzungen (alt genau einmal im Transkript) "
        "und Sprecher-Zuordnungen (nur Namen aus den Begleittexten) vor. beleg: einladung | folie N | "
        "selbstvorstellung | unsicher. Modell: Use-Case chat_completion."
    ))
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        transkript = payload.get("transkript")
        if not isinstance(transkript, str) or not transkript.strip():
            return _error("MISSING_TRANSKRIPT", "Feld 'transkript' mit nicht-leerem Text ist erforderlich", 400)
        try:
            begleittexte = parse_begleittexte(payload.get("begleittexte"))
        except ValueError as e:
            return _error("INVALID_BEGLEITTEXTE", str(e), 400)
        zielsprache_raw = payload.get("zielsprache")
        zielsprache = zielsprache_raw.strip() if isinstance(zielsprache_raw, str) and zielsprache_raw.strip() else "de"

        try:
            vorschlag, meta = KorrekturvorschlagService().vorschlagen(transkript, begleittexte, zielsprache)
        except ProcessingError as e:
            code = str((getattr(e, "details", None) or {}).get("error_code") or type(e).__name__)
            logger.error("Korrekturvorschlag fehlgeschlagen", error=e, code=code)
            return _error(code, str(e), _ERROR_STATUS.get(code, 400), getattr(e, "details", None))
        except Exception as e:
            logger.error("Unerwarteter Fehler beim Korrekturvorschlag", error=e)
            return _error("INTERNAL_ERROR", str(e), 500)

        logger.info("Korrekturvorschlag erstellt", ersetzungen=len(vorschlag.ersetzungen),
                    sprecher=len(vorschlag.sprecher), verworfen=len(vorschlag.verworfen), modell=meta["modell"])
        return {"status": "success", "data": {**vorschlag.to_dict(), **meta}}
