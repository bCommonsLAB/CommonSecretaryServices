"""
Hilfsfunktionen zum Lesen von Token- und Kostenfeldern aus Provider-Responses.

OpenRouter legt `usage.cost` (USD) an das Usage-Objekt. Je nach SDK-Version
liegt das Feld am Objekt, in `model_extra` oder in einem Dict.
"""

from typing import Any, Optional


def extract_usage_cost(usage: Any) -> float:
    """
    Liest den Kostenbetrag aus einem Usage-Objekt.

    Args:
        usage: OpenRouter/OpenAI-Usage (Objekt oder Dict) oder None.

    Returns:
        Kosten in USD. 0.0 wenn das Feld fehlt oder ungültig ist.
    """
    raw: Any = _read_usage_field(usage, "cost")
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if value < 0.0:
        return 0.0
    return value


def extract_usage_tokens(usage: Any) -> int:
    """
    Liest total_tokens aus einem Usage-Objekt.

    Returns:
        Token-Anzahl, 0 wenn das Feld fehlt.
    """
    raw: Any = _read_usage_field(usage, "total_tokens")
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _read_usage_field(usage: Any, field_name: str) -> Optional[Any]:
    """Liest ein Feld defensiv aus Objekt, Dict oder Pydantic-model_extra."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(field_name)
    value = getattr(usage, field_name, None)
    if value is not None:
        return value
    extra = getattr(usage, "model_extra", None)
    if isinstance(extra, dict):
        return extra.get(field_name)
    return None
