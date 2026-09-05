"""
@fileoverview Transkriptions-Kontext - was welches Modell an Kontext annimmt

@description
Transkription wird deutlich besser, wenn das Modell weiss, worum es geht: Thema und
Anlass als Freitext, Eigennamen und Fachwoerter als Begriffsliste, erwartete Sprachen
bei mehrsprachigem Material. Genau an diesen Stellen scheitert Erkennung sonst.

Die Modelle nehmen aber unterschiedliche Felder an:

- ``keywords`` kennen nur ``gpt-transcribe`` und ``gpt-live-transcribe``.
- ``languages`` (Liste) loest bei denselben Modellen das einzelne ``language`` ab.
- ``prompt`` nimmt jedes Modell ausser ``gpt-4o-transcribe-diarize`` — dort schliessen
  sich Freitext-Kontext und Sprecher-Erkennung gegenseitig aus.

Diese Datei haelt das an einer Stelle fest und liefert zu jedem Aufruf zurueck, welche
Felder verworfen wurden und warum. Der Aufrufer meldet das; verschluckt wird nichts.

@module core.llm.transcription_context

@exports
- TranscriptionContext: Dataclass - der gewuenschte Kontext
- ContextApplication: Dataclass - zulaessige Parameter und verworfene Felder
- build_context_params: Baut die zulaessigen API-Parameter fuer ein Modell

@usedIn
- src.core.llm.providers.openai_provider: Aufbau der API-Parameter
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Modelle, die eine Begriffsliste und mehrere erwartete Sprachen annehmen.
MODELS_WITH_KEYWORDS = frozenset({"gpt-transcribe", "gpt-live-transcribe"})

# Dieselben Modelle nutzen die Liste ``languages`` statt des einzelnen ``language``.
MODELS_WITH_LANGUAGE_LIST = MODELS_WITH_KEYWORDS

# Sprecher-Erkennung und Freitext-Kontext schliessen sich aus.
MODELS_WITHOUT_PROMPT = frozenset({"gpt-4o-transcribe-diarize"})


@dataclass(frozen=True)
class TranscriptionContext:
    """Kontext zu einer Aufnahme.

    Attributes:
        language: Sprache der Aufnahme (ISO 639-1) oder "auto"
        languages: Moegliche Sprachen bei mehrsprachigem Material (ISO 639-1)
        prompt: Freitext ueber Thema, Anlass, Ort — KEINE Anweisung an das Modell
        keywords: Eigennamen, Fachwoerter, Abkuerzungen, die vorkommen koennen
    """

    language: Optional[str] = None
    languages: List[str] = field(default_factory=list)
    prompt: Optional[str] = None
    keywords: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True, wenn gar kein Kontext gesetzt ist."""
        return not (self.language or self.languages or self.prompt or self.keywords)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Kontext in ein Dictionary (z.B. fuer Cache-Schluessel)."""
        return {
            "language": self.language,
            "languages": list(self.languages),
            "prompt": self.prompt,
            "keywords": list(self.keywords),
        }


@dataclass(frozen=True)
class ContextApplication:
    """Ergebnis der Anwendung eines Kontexts auf ein Modell.

    Attributes:
        params: Die Felder, die dieses Modell annimmt
        dropped: Verworfene Felder mit Begruendung, zum Melden durch den Aufrufer
    """

    params: Dict[str, Any]
    dropped: List[str] = field(default_factory=list)


def _clean_list(values: List[str]) -> List[str]:
    """Nimmt nur nicht-leere Zeichenketten und entfernt Wiederholungen."""
    seen: List[str] = []
    for value in values:
        trimmed = value.strip() if isinstance(value, str) else ""
        if trimmed and trimmed not in seen:
            seen.append(trimmed)
    return seen


def build_context_params(model: str, context: TranscriptionContext) -> ContextApplication:
    """
    Baut die Kontext-Parameter, die das angegebene Modell annimmt.

    Args:
        model: Name des Transkriptionsmodells
        context: Der gewuenschte Kontext

    Returns:
        ContextApplication: zulaessige Parameter plus die Liste verworfener Felder
    """
    params: Dict[str, Any] = {}
    dropped: List[str] = []

    language = (context.language or "").strip()
    # "auto" heisst "nicht festlegen" und ist kein Sprachcode.
    if language.lower() == "auto":
        language = ""
    languages = _clean_list(context.languages)

    if model in MODELS_WITH_LANGUAGE_LIST:
        # Diese Modelle erwarten die Liste. Eine einzelne Sprache wird dafuer
        # uebernommen, damit der Hinweis nicht verloren geht.
        merged = languages or ([language] if language else [])
        if merged:
            params["languages"] = merged
    else:
        if language:
            params["language"] = language
        if languages:
            dropped.append(
                f"languages: '{model}' nimmt nur eine einzelne Sprache entgegen"
            )

    prompt = (context.prompt or "").strip()
    if prompt:
        if model in MODELS_WITHOUT_PROMPT:
            dropped.append(
                f"prompt: '{model}' erkennt Sprecher und nimmt dafuer keinen Freitext-Kontext"
            )
        else:
            params["prompt"] = prompt

    keywords = _clean_list(context.keywords)
    if keywords:
        if model in MODELS_WITH_KEYWORDS:
            params["keywords"] = keywords
        else:
            dropped.append(
                f"keywords: '{model}' kennt keine Begriffsliste "
                f"(nur {', '.join(sorted(MODELS_WITH_KEYWORDS))})"
            )

    return ContextApplication(params=params, dropped=dropped)
