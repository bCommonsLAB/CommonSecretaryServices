"""
@fileoverview Verlaesslichkeit je Abschnitt - was welches Modell dazu liefert

@description
Ein Transkript ist nur etwas wert, wenn der Mensch sehen kann, wo das Modell
geraten hat. Der Whisper-Decoder liefert dafuer je Abschnitt drei Werte:

- ``avg_logprob``: mittlere Log-Wahrscheinlichkeit der Tokens (nahe 0 = sicher)
- ``compression_ratio``: gzip-Verhaeltnis des Texts (hoch = Wiederholungen, Schleife)
- ``no_speech_prob``: Wahrscheinlichkeit, dass gar nicht gesprochen wurde

Die Modelle unterscheiden sich darin, was davon ankommt (Probe 09.10.2026):

- ``whisper-1`` mit ``verbose_json``: Segmente mit allen drei Werten.
- ``gpt-transcribe``, ``gpt-4o-transcribe``, ``gpt-4o-mini-transcribe``: nur
  ``json``; mit ``include=["logprobs"]`` kommen Logprobs **je Token** fuer den
  ganzen Text. Daraus wird ein Mittelwert je Antwort, ``compression_ratio`` rechnet
  der Dienst selbst aus dem Text, ``no_speech_prob`` bleibt None.
- ``gpt-4o-transcribe-diarize``: weist ``include=["logprobs"]`` ab („Logprobs are
  not supported for diarization models"). Es gibt keine Werte.

Dieses Modul haelt die Entscheidung je Modell an einer Stelle fest, baut die
Segmente aus einer Anbieter-Antwort und sagt in ``quality_source``, woher die
Zahlen stammen. Schwellen werden hier nicht angewendet — das macht der Client
aus den Rohwerten.

@module core.llm.transcription_quality

@exports
- plan_transcription_request: response_format und include je Modell
- segments_from_response: TranscriptionSegment-Liste aus einer Anbieter-Antwort
- compression_ratio: gzip-Verhaeltnis eines Texts wie im Whisper-Decoder
- mean_logprob: Mittelwert der Token-Logprobs
- reported_language: vom Modell gemeldete Sprache (roh, nicht konvertiert)
- audio_duration: Dauer der Aufnahme laut Antwort

@usedIn
- src.core.llm.providers.openai_provider: Aufbau der Anfrage und der Segmente
- src.utils.transcription_utils: Rueckfall fuer rohe SDK-Antworten
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple
import zlib

from ..models.audio import TranscriptionSegment

# Nur Whisper kennt verbose_json und damit Segmente mit den drei Werten.
# Das gilt auch fuer "openrouter/openai/whisper-1" und aehnliche Kennungen.
def supports_verbose_json(model: str) -> bool:
    """True, wenn das Modell ``verbose_json`` mit Segmenten liefert."""
    return "whisper" in model.lower()


def supports_logprobs(model: str) -> bool:
    """True, wenn ``include=["logprobs"]`` versucht werden soll.

    Die Sprecher-Modelle weisen es ab (Probe 09.10.2026); Whisper braucht es nicht.
    Unbekannte Modelle bekommen den Versuch — wird er abgewiesen, faellt der
    Provider auf eine Anfrage ohne ``include`` zurueck.
    """
    lowered = model.lower()
    return "whisper" not in lowered and "diarize" not in lowered


# Formate, die kein JSON mit Werten tragen: wer sie ausdruecklich will, bekommt sie.
_PLAIN_FORMATS = frozenset({"text", "srt", "vtt"})


@dataclass(frozen=True)
class RequestPlan:
    """Was an die API geht, damit die Werte mitkommen."""

    response_format: str
    include: Optional[List[str]]


def plan_transcription_request(model: str, requested_format: Optional[str]) -> RequestPlan:
    """
    Waehlt ``response_format`` und ``include`` je Modell vorab.

    Frueher ging jede Anfrage als ``verbose_json`` raus und wurde bei GPT-Modellen
    nach dem Fehler als ``json`` wiederholt — die Audiodatei wurde dabei zweimal
    hochgeladen. Jetzt entscheidet das Modell vorab.

    Args:
        model: Modellname
        requested_format: vom Aufrufer gewuenschtes Format oder None

    Returns:
        RequestPlan mit Format und ``include``-Liste (None, wenn nichts angefordert wird)
    """
    if requested_format in _PLAIN_FORMATS:
        return RequestPlan(response_format=str(requested_format), include=None)
    if supports_verbose_json(model):
        return RequestPlan(response_format=requested_format or "verbose_json", include=None)
    include = ["logprobs"] if supports_logprobs(model) else None
    return RequestPlan(response_format="json", include=include)


def compression_ratio(text: str) -> Optional[float]:
    """gzip-Verhaeltnis wie im Whisper-Decoder: Textlaenge / komprimierte Laenge.

    Hoch (Erfahrungswert ueber 2.4) heisst: der Text wiederholt sich.
    Fuer leeren Text gibt es keinen Wert.
    """
    raw = text.encode("utf-8")
    if not raw:
        return None
    return len(raw) / len(zlib.compress(raw))


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Liest ein Feld aus einem Dict oder einem Objekt (SDK-Modell)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _as_float(value: Any) -> Optional[float]:
    """Zahl oder None — Strings und bool zaehlen nicht als Messwert."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def mean_logprob(logprobs: Any) -> Optional[float]:
    """Mittelwert der Token-Logprobs; None, wenn keine brauchbare Zahl dabei ist."""
    if not isinstance(logprobs, (list, tuple)):
        return None
    values: List[float] = []
    for entry in logprobs:
        value = _as_float(_get(entry, "logprob"))
        if value is not None:
            values.append(value)
    if not values:
        return None
    return sum(values) / len(values)


def reported_language(response: Any) -> Optional[str]:
    """
    Sprache, die das Modell selbst gemeldet hat — roh, so wie sie ankam.

    ``whisper-1`` meldet ``language`` als Wort („german"), ``gpt-transcribe`` eine
    Liste ``languages: [{"code": "de"}]``. Beides wird gelesen; die Umwandlung in
    ISO 639-1 macht der Aufrufer. None, wenn das Modell nichts gesagt hat.
    """
    language = _get(response, "language")
    if isinstance(language, str) and language.strip():
        return language.strip()
    languages = _get(response, "languages")
    if isinstance(languages, (list, tuple)):
        for entry in languages:
            code = _get(entry, "code") if not isinstance(entry, str) else entry
            if isinstance(code, str) and code.strip():
                return code.strip()
    return None


def audio_duration(response: Any) -> Optional[float]:
    """Dauer der Aufnahme in Sekunden laut Antwort, oder None.

    ``verbose_json`` traegt ``duration``; Modelle mit Dauer-Abrechnung melden
    ``usage.seconds``. Token-Abrechnung sagt nichts ueber die Dauer.
    """
    duration = _as_float(_get(response, "duration"))
    if duration is not None and duration > 0:
        return duration
    usage = _get(response, "usage")
    if usage is not None and _get(usage, "type") == "duration":
        seconds = _as_float(_get(usage, "seconds"))
        if seconds is not None and seconds > 0:
            return seconds
    return None


def _whisper_segments(raw_segments: Sequence[Any]) -> List[TranscriptionSegment]:
    """Segmente aus ``verbose_json``: Zeiten und die drei Werte je Abschnitt."""
    segments: List[TranscriptionSegment] = []
    for raw in raw_segments:
        text = str(_get(raw, "text", "") or "").strip()
        if not text:
            continue
        start = max(0.0, _as_float(_get(raw, "start")) or 0.0)
        end = _as_float(_get(raw, "end"))
        if end is None or end <= start:
            # Whisper kann start == end liefern; ein Segment braucht eine Dauer.
            end = start + 0.01
        segments.append(
            TranscriptionSegment(
                text=text,
                segment_id=len(segments),
                start=start,
                end=end,
                avg_logprob=_as_float(_get(raw, "avg_logprob")),
                compression_ratio=_as_float(_get(raw, "compression_ratio")),
                no_speech_prob=_as_float(_get(raw, "no_speech_prob")),
                quality_source="whisper",
            )
        )
    return segments


def segments_from_response(
    response: Any,
    *,
    text: str,
    end_seconds: float,
    title: Optional[str] = None,
) -> Tuple[List[TranscriptionSegment], str]:
    """
    Baut die Segmente einer Anbieter-Antwort und sagt, woher die Werte stammen.

    Reihenfolge: Whisper-Segmente mit Werten, sonst ein Segment aus den
    Token-Logprobs, sonst ein Segment ohne Werte.

    Args:
        response: Antwort des Anbieters (SDK-Objekt oder Dict)
        text: der Gesamttext, falls keine Segmente kommen
        end_seconds: Ende des einzelnen Segments, wenn die Antwort keine Zeiten traegt
        title: Titel (z.B. Kapitel) fuer das einzelne Segment

    Returns:
        (Segmente, quality_source)
    """
    raw_segments = _get(response, "segments")
    if isinstance(raw_segments, (list, tuple)) and raw_segments:
        first = raw_segments[0]
        if _get(first, "avg_logprob") is not None or _get(first, "no_speech_prob") is not None:
            segments = _whisper_segments(raw_segments)
            if segments:
                return segments, "whisper"

    end = end_seconds if end_seconds > 0 else 0.01
    average = mean_logprob(_get(response, "logprobs"))
    if average is not None:
        return [
            TranscriptionSegment(
                text=text,
                segment_id=0,
                start=0.0,
                end=end,
                title=title,
                avg_logprob=average,
                compression_ratio=compression_ratio(text),
                no_speech_prob=None,
                quality_source="logprobs",
            )
        ], "logprobs"

    return [
        TranscriptionSegment(text=text, segment_id=0, start=0.0, end=end, title=title, quality_source="none")
    ], "none"
