"""
@fileoverview Audio-Abschlussdaten - gemeinsamer data-Block fuer Webhook und SSE

@description
Webhook (`audio_handler`) und SSE (`sse.py`) sollen denselben flachen data-Block
schicken. Der Sprecher-Weg legt speakers, segments und dropped_context schon in
structured_data["data"]. Diese Funktion kopiert sie, wenn sie da sind.

Fehlt der Block, bleibt nur der Text. Leere Listen werden nicht erfunden:
ein normaler Transkript-Job hat keine Sprecherfelder, und das ist etwas anderes
als eine leere Sprecherliste.

@module api.audio_completed_data
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Union

from src.core.models.job_models import Job

# Genau dieser Satz steht im Job-Log, wenn der Block fehlt.
MISSING_SPEAKER_DATA_LOG = "Webhook ohne Sprecherdaten: structured_data fehlt"

# Schluessel, die nur mitwandern, wenn der Processor sie gesetzt hat.
# ``segments`` tragen je Abschnitt die Verlaesslichkeitswerte (avg_logprob,
# compression_ratio, no_speech_prob, quality_source) unveraendert; ``language`` ist
# die vom Modell erkannte Sprache (None, wenn das Modell keine meldete).
_OPTIONAL_KEYS = (
    "speakers",
    "segments",
    "language",
    "dropped_context",
    "detected_language",
    "duration",
    "llm_model",
    "chunk_count",
    "from_cache",
)


def build_audio_completed_data(
    source: Union[Job, Dict[str, Any]],
    *,
    fallback_text: Optional[str] = None,
    on_missing: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Baut den data-Block fuer den Audio-Abschluss.

    Args:
        source: Job (liest results.structured_data) oder das to_dict() der Response.
        fallback_text: Text, wenn der Block keinen eigenen Text hat. Bei einem Job
            ohne diesen Parameter gilt results.markdown_content.
        on_missing: Wird einmal aufgerufen, wenn structured_data oder data fehlt.
            Der Handler schreibt damit den Job-Log. SSE reicht eine Warnung.

    Returns:
        Flacher data-Block. Ohne Quellblock nur transcription.text.
    """
    structured, text_fallback = _unwrap(source, fallback_text)
    data = _data_block(structured)
    if data is None:
        # Kein stiller Default: der Aufrufer protokolliert, wir erfinden keine Felder.
        if on_missing is not None:
            on_missing(MISSING_SPEAKER_DATA_LOG)
        return {"transcription": {"text": text_fallback}}

    text = _text_of(data)
    if text is None:
        text = text_fallback
    output = data.get("output_text")
    # output_text ist der Vertrag fuer KnowledgeScout, auch wenn der normale Weg
    # nur transcription.text gespeichert hat.
    output_text: str = output if isinstance(output, str) else text
    payload: Dict[str, Any] = {
        "transcription": {"text": text},
        "output_text": output_text,
    }
    for key in _OPTIONAL_KEYS:
        if key in data:
            payload[key] = data[key]
    return payload


def _unwrap(
    source: Union[Job, Dict[str, Any]],
    fallback_text: Optional[str],
) -> tuple[Optional[Dict[str, Any]], str]:
    """Trennt Job und Dict. Der Text-Fallback ist immer ein String."""
    if isinstance(source, Job):
        text = fallback_text
        results = source.results
        if text is None and results is not None and isinstance(results.markdown_content, str):
            text = results.markdown_content
        structured = results.structured_data if results is not None else None
        block = structured if isinstance(structured, dict) else None
        return block, text if isinstance(text, str) else ""

    # Nach dem Job-Zweig bleibt nur das Response-Dict (Union Job | Dict).
    return source, fallback_text if isinstance(fallback_text, str) else ""


def _data_block(structured: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Liest den data-Block. Ein Dict ohne data und ohne Text gilt als fehlend.

    Liegt "data" vor, muss es ein Dict sein. Sonst ist der Block kaputt und
    wird wie ein fehlender Block behandelt, nicht wie ein leeres Ergebnis.
    Ein bereits flacher Block (Tests, direkter Aufruf) hat transcription oder
    output_text auf der obersten Ebene.
    """
    if not isinstance(structured, dict):
        return None
    if "data" in structured:
        raw: Any = structured.get("data")
        return raw if isinstance(raw, dict) else None
    if any(key in structured for key in ("transcription", "output_text", "speakers")):
        return structured
    return None


def _text_of(data: Dict[str, Any]) -> Optional[str]:
    """Text aus transcription.text, sonst aus output_text. Andere Typen zaehlen nicht."""
    transcription: Any = data.get("transcription")
    if isinstance(transcription, dict):
        text: Any = transcription.get("text")
        if isinstance(text, str):
            return text
    output: Any = data.get("output_text")
    if isinstance(output, str):
        return output
    return None
