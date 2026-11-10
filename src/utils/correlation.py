"""
Korrelations-Header fuer die Metrik (request_metrics).

Der Aufrufer (z. B. KnowledgeScout) darf Kennungen mitschicken, damit sich ein
Metrik-Eintrag seiner eigenen Anfrage zuordnen laesst. Dasselbe Muster wie bei
der Bildanalyse (image_analyzer_routes.py): optionale ``X-...-Id``-Header, rein
informativ, fehlen sie, bleibt das Feld leer.

Gespeichert werden NUR Kennungen, nie Inhalte: Werte muessen wie eine Kennung
aussehen (siehe _ID_PATTERN). Alles andere wird verworfen und geloggt, damit
ueber diesen Weg kein Freitext in die Metrik gelangt.
"""

import re
from typing import Dict, Mapping, Optional

# Header-Name -> Feldname am Metrik-Eintrag (request_metrics.correlation.<feld>).
CORRELATION_HEADER_FIELDS: Dict[str, str] = {
    # Bestehend (Bildanalyse / external-jobs-worker):
    "X-Job-Id": "job_id",
    "X-Source-Item-Id": "source_item_id",
    "X-Worker-Id": "worker_id",
    "X-Start-Request-Id": "start_request_id",
    # Neu (Story-Modus / Chat): Frage, Library und laufender Chat.
    "X-Query-Id": "query_id",
    "X-Library-Id": "library_id",
    "X-Chat-Id": "chat_id",
}

# Kennungen: UUIDs, Mongo-Ids, Slugs. Kein Leerraum, kein Freitext.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


def is_valid_correlation_id(value: str) -> bool:
    """True, wenn der Wert wie eine Kennung aussieht (max. 128 Zeichen)."""
    return bool(_ID_PATTERN.match(value))


def correlation_from_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """
    Liest die Korrelations-Header und gibt die gueltigen als Feld -> Wert zurueck.

    Args:
        headers: Request-Header (Werkzeug-Header sind case-insensitiv).

    Returns:
        Nur gesendete UND gueltige Kennungen. Ungueltige fehlen im Ergebnis;
        ``rejected_correlation_headers`` nennt sie.
    """
    result: Dict[str, str] = {}
    for header, field_name in CORRELATION_HEADER_FIELDS.items():
        raw: Optional[str] = headers.get(header)
        if raw is None:
            continue
        value = raw.strip()
        if value and is_valid_correlation_id(value):
            result[field_name] = value
    return result


def rejected_correlation_headers(headers: Mapping[str, str]) -> list[str]:
    """Namen der gesendeten Korrelations-Header, deren Wert verworfen wurde."""
    rejected: list[str] = []
    for header in CORRELATION_HEADER_FIELDS:
        raw: Optional[str] = headers.get(header)
        if raw is None:
            continue
        if not is_valid_correlation_id(raw.strip()):
            rejected.append(header)
    return rejected
