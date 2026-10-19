"""
@fileoverview Model names - Modellnamen ohne doppeltes Provider-Präfix

@description
Die Modell-ID im LLM-Katalog ist "<provider>/<modellname>". Wird ein Modellname
mit Präfix eingegeben (z. B. "mistral/mistral-ocr-latest" oder die OpenRouter-
Schreibweise "mistralai/mistral-ocr-2512"), entstehen doppelte IDs wie
"mistral/mistral/mistral-ocr-latest", und die Anbieter-API lehnt den Namen
mit "Invalid model" ab.

normalize_model_name() entfernt solche Präfixe für Anbieter, deren API reine
Modellnamen erwartet. OpenRouter bleibt unverändert, weil dort "anbieter/modell"
der echte Modellname ist (z. B. "mistralai/mistral-small-3.2-24b-instruct").

@module core.llm.model_names
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# Zusätzliche Präfixe je Provider, die in fremden Katalogen vorkommen.
_PROVIDER_PREFIX_ALIASES: Dict[str, Tuple[str, ...]] = {
    "mistral": ("mistralai",),
}

# Provider, bei denen "anbieter/modell" der echte Modellname ist.
_PROVIDERS_WITH_VENDOR_SLUGS = frozenset({"openrouter"})

# Mistral Document-OCR (/v1/ocr): Alias auf das aktuelle OCR-Modell.
MISTRAL_OCR_FALLBACK_MODEL = "mistral-ocr-latest"


def normalize_model_name(provider: Optional[str], model_name: Optional[str]) -> str:
    """
    Modellname ohne Provider-Präfix.

    Beispiele für provider="mistral":
    "mistral/mistral-ocr-latest" -> "mistral-ocr-latest",
    "mistralai/mistral-ocr-2512" -> "mistral-ocr-2512",
    "mistral/mistral/x" -> "x".
    """
    name = (model_name or "").strip()
    prov = (provider or "").strip().lower()
    if not prov or prov in _PROVIDERS_WITH_VENDOR_SLUGS:
        return name
    prefixes = (prov,) + _PROVIDER_PREFIX_ALIASES.get(prov, ())
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if name.lower().startswith(prefix + "/"):
                name = name[len(prefix) + 1:].strip()
                changed = True
    return name
