"""
@fileoverview JSON-Antwortmodus - Soll das Modell im JSON-Modus angefragt werden?

@description
Erste Reparaturstufe gegen ungültiges LLM-JSON: Das Modell wird, wo der Provider
das kann, mit ``response_format = {"type": "json_object"}`` angefragt (OpenAI-
kompatibel; OpenRouter reicht es an Gemini als ``response_mime_type`` weiter).
Damit liefert das Modell deutlich seltener unmaskierte Anführungszeichen in
langen Werten (Befund 05.11.2026, Vorlage ``chatverlauf-de``).

Konfiguration (``config.yaml``, Abschnitt ``llm_config.json_response_mode``):

    json_response_mode:
      enabled: true            # Vorgabe an
      models:                  # je Modell überstimmen
        google/gemini-2.5-flash: true
        some/odd-model: false

Umgebungsvariable ``LLM_JSON_RESPONSE_MODE=off`` (oder ``0``/``false``) schaltet den
Modus für die ganze Installation aus, ohne config.yaml anzufassen.

Provider, die ``response_format`` nicht an die API durchreichen (Mistral), bekommen
kein JSON-Modus-Flag; die Reparaturstufen in ``json_validation`` greifen trotzdem.

@module core.llm.json_mode

@exports
- json_response_mode_enabled: Entscheidung je Modell und Provider
- response_format_kwargs: Die kwargs für chat_completion
- JSON_RESPONSE_MODE_ENV: Name der Umgebungsvariablen
- PROVIDERS_WITH_RESPONSE_FORMAT: Provider, die response_format durchreichen
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

JSON_RESPONSE_MODE_ENV = "LLM_JSON_RESPONSE_MODE"

# Provider, deren chat_completion ``response_format`` an eine OpenAI-kompatible API
# weitergibt. Mistral ignoriert zusätzliche kwargs; Voyage hat keinen Chat.
PROVIDERS_WITH_RESPONSE_FORMAT: frozenset[str] = frozenset({"openrouter", "openai", "ollama"})

_OFF_VALUES: frozenset[str] = frozenset({"0", "false", "off", "no", "nein", "aus"})


def _normalize_model(model: str) -> str:
    """Modellkennung ohne führendes 'provider/' aus der Use-Case-Konfiguration."""
    return model.strip().lower()


def _model_override(models_cfg: Any, model: str) -> Optional[bool]:
    """Sucht einen Eintrag je Modell; akzeptiert 'google/x' wie 'openrouter/google/x'."""
    if not isinstance(models_cfg, Mapping):
        return None
    wanted = _normalize_model(model)
    for key, value in models_cfg.items():
        key_norm = _normalize_model(str(key))
        if key_norm == wanted or wanted.endswith("/" + key_norm) or key_norm.endswith("/" + wanted):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() not in _OFF_VALUES
    return None


def _load_section() -> Mapping[str, Any]:
    """Liest ``llm_config.json_response_mode`` aus der zentralen Konfiguration."""
    try:
        from src.core.config import Config

        section: Any = Config().get("llm_config.json_response_mode", {})
    except Exception:
        return {}
    return section if isinstance(section, Mapping) else {}


def json_response_mode_enabled(
    model: str,
    provider_name: Optional[str],
    config_section: Optional[Mapping[str, Any]] = None,
) -> bool:
    """
    Entscheidet, ob die Anfrage an ``model`` beim Provider ``provider_name`` im
    JSON-Antwortmodus laufen soll.

    Reihenfolge: Umgebungsvariable (nur zum Abschalten) > Eintrag je Modell >
    ``enabled`` (Vorgabe True). Provider ohne ``response_format``-Durchreichung
    liefern immer False.

    Args:
        model: Modellkennung, z. B. ``google/gemini-2.5-flash``
        provider_name: Providername, z. B. ``openrouter``; None = unbekannt
        config_section: Abschnitt ``llm_config.json_response_mode``; None = aus config.yaml
    """
    if (os.getenv(JSON_RESPONSE_MODE_ENV) or "").strip().lower() in _OFF_VALUES:
        return False
    if provider_name is None or provider_name.strip().lower() not in PROVIDERS_WITH_RESPONSE_FORMAT:
        return False

    section = config_section if config_section is not None else _load_section()
    override = _model_override(section.get("models"), model) if model else None
    if override is not None:
        return override
    enabled: Any = section.get("enabled", True)
    if isinstance(enabled, str):
        return enabled.strip().lower() not in _OFF_VALUES
    return bool(enabled)


def response_format_kwargs() -> Dict[str, Any]:
    """Die zusätzlichen kwargs für ``chat_completion`` im JSON-Antwortmodus."""
    return {"response_format": {"type": "json_object"}}


def looks_like_response_format_rejection(error: BaseException) -> bool:
    """
    Erkennt die Ablehnung des JSON-Modus durch Provider oder Modell, damit der
    Aufrufer genau einmal ohne ``response_format`` wiederholen kann.
    """
    text = str(error).lower()
    return "response_format" in text or "json_object" in text or "json mode" in text
