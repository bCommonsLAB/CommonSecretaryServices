"""
XXL Model Metadata Helpers

Dieses Modul enthält kleine, testbare Helferfunktionen zum Auslesen von
Modell-Metadaten (insbesondere Kontextfenster/Context-Length) aus MongoDB.

Motivation:
- Für XXL-Text-Zusammenfassungen müssen Chunk-Größen an das Kontextfenster
  des gewählten Modells angepasst werden.
- Das Kontextfenster wird bei uns in MongoDB unter `llm_models.metadata.context_length`
  gepflegt (z.B. aus OpenRouter-Model-API oder manuell via Dashboard).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class ModelContextInfo:
    """
    Kontext-Informationen eines LLM-Modells.

    Attributes:
        model_id: Vollständige Modell-ID im Format `{provider}/{model_name}`
        context_length_tokens: Kontextfenster in Tokens (wenn bekannt)
        source: Woher die Info stammt (z.B. "mongodb", "fallback")
    """

    model_id: str
    context_length_tokens: Optional[int]
    source: str

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id darf nicht leer sein")
        if self.context_length_tokens is not None and self.context_length_tokens <= 0:
            raise ValueError("context_length_tokens muss > 0 sein, wenn gesetzt")
        if not self.source.strip():
            raise ValueError("source darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "context_length_tokens": self.context_length_tokens,
            "source": self.source,
        }


def extract_context_length_tokens_from_metadata(metadata: Dict[str, Any]) -> Optional[int]:
    """
    Extrahiert das Kontextfenster aus `LLMModel.metadata`.

    Erwartetes Feld:
    - `context_length`: int (Tokens)

    Robustheit:
    - akzeptiert int oder numerische Strings
    - gibt None zurück, wenn nicht vorhanden oder ungültig
    """

    raw = metadata.get("context_length")
    if raw is None:
        return None

    if isinstance(raw, int):
        return raw if raw > 0 else None

    if isinstance(raw, str):
        raw_s = raw.strip()
        if not raw_s:
            return None
        try:
            val = int(raw_s)
            return val if val > 0 else None
        except Exception:
            return None

    # andere Typen ignorieren
    return None






