"""
Kosten für Mistral Document-OCR.

Mistral rechnet OCR nach Seiten, nicht nach Token.
Preis laut Vorgabe: 1 USD je 1000 Seiten.
Voyage-Embeddings bleiben kostenlos (kein Eintrag hier).
"""

from typing import Any, Mapping, Sequence, cast

# Fester Satz. Keine Provider-Response mit USD-Feld.
MISTRAL_OCR_USD_PER_1000_PAGES: float = 1.0


def extract_mistral_ocr_pages(ocr_json: Any) -> int:
    """
    Liest die abgerechnete Seitenanzahl aus einer Mistral-OCR-Antwort.

    Vorrang: usage_info.pages_processed (das ist die Billing-Größe).
    Fallback: Länge von pages.
    """
    if not isinstance(ocr_json, dict):
        return 0
    payload = cast(Mapping[str, object], ocr_json)
    usage_raw = payload.get("usage_info")
    if isinstance(usage_raw, dict):
        usage = cast(Mapping[str, object], usage_raw)
        pages = _as_positive_int(usage.get("pages_processed"))
        if pages > 0:
            return pages
    pages_raw = payload.get("pages")
    if isinstance(pages_raw, list):
        page_seq = cast(Sequence[object], pages_raw)
        return len(page_seq)
    return 0


def estimate_mistral_ocr_cost(pages: int) -> float:
    """
    USD für eine OCR-Anfrage.

    1 USD / 1000 Seiten. 0 bei ungültiger oder leerer Seitenanzahl.
    """
    if pages <= 0:
        return 0.0
    return float(pages) * (MISTRAL_OCR_USD_PER_1000_PAGES / 1000.0)


def _as_positive_int(raw: object) -> int:
    """Int aus API-Feld. 0 wenn das Feld fehlt oder ungültig ist."""
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0
