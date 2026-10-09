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

Sprache (Teil 2): Whisper uebersetzt bei Sprachwechseln innerhalb eines Fensters,
statt zu transkribieren, und ``avg_logprob`` bleibt dabei unauffaellig. Deshalb
traegt jedes Segment zwei Meinungen: ``language`` (vom Modell je Anfrage gemeldet)
und ``text_language`` (aus dem Segmenttext, lingua).

@module core.llm.transcription_quality

@exports
- plan_transcription_request: response_format, include und Wort-Zeitmarken je Modell
- segments_from_response: TranscriptionSegment-Liste aus einer Anbieter-Antwort
- detect_text_language / with_text_language: Sprache eines Segmenttexts
- compression_ratio: gzip-Verhaeltnis eines Texts wie im Whisper-Decoder
- mean_logprob: Mittelwert der Token-Logprobs
- reported_language: vom Modell gemeldete Sprache (roh, nicht konvertiert)
- audio_duration: Dauer der Aufnahme laut Antwort

@usedIn
- src.core.llm.providers.openai_provider: Aufbau der Anfrage und der Segmente
- src.utils.transcription_utils: Rueckfall fuer rohe SDK-Antworten
"""

from dataclasses import dataclass, replace as dataclass_replace
from typing import Any, List, Optional, Sequence, Tuple
import re
import threading
import zlib

from ..models.audio import TranscriptionSegment, TranscriptionWord
from src.utils.logger import get_logger

logger = get_logger(process_id="transcription-quality")

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
    # Nur whisper-1 mit verbose_json und nur auf Wunsch: Segmente UND Woerter. Wer
    # nur ["word"] schickt, bekommt keine Segmente mehr — und damit keine Werte.
    timestamp_granularities: Optional[List[str]] = None


def plan_transcription_request(
    model: str, requested_format: Optional[str], word_timestamps: bool = False
) -> RequestPlan:
    """
    Waehlt ``response_format``, ``include`` und Zeitmarken-Granularitaet je Modell vorab.

    Frueher ging jede Anfrage als ``verbose_json`` raus und wurde bei GPT-Modellen
    nach dem Fehler als ``json`` wiederholt — die Audiodatei wurde dabei zweimal
    hochgeladen. Jetzt entscheidet das Modell vorab.

    Wort-Zeitmarken sind standardmaessig AUS. Messung 09.10.2026 am Pruef-Transkript
    (vier 5-Minuten-Stuecke, je zwei Laeufe): mit ``timestamp_granularities=["word"]``
    liefert whisper-1 bei drei von vier Stuecken 15–23 % weniger Text; in einem
    Stueck fehlten 16 von 36 Saetzen, eine Minute Rede am Stueck. Ein Transkript mit
    Luecken ist schlechter als eines ohne Wort-Zeitmarken.

    Args:
        model: Modellname
        requested_format: vom Aufrufer gewuenschtes Format oder None
        word_timestamps: Woerter mit Zeitmarken anfordern (nur whisper-1). Kostet Text.

    Returns:
        RequestPlan mit Format, ``include``-Liste und Granularitaet (je None, wenn
        nichts angefordert wird)
    """
    if requested_format in _PLAIN_FORMATS:
        return RequestPlan(response_format=str(requested_format), include=None)
    if supports_verbose_json(model):
        response_format = requested_format or "verbose_json"
        granularities = (
            ["segment", "word"] if word_timestamps and response_format == "verbose_json" else None
        )
        return RequestPlan(response_format=response_format, include=None, timestamp_granularities=granularities)
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


def reported_languages(response: Any) -> List[str]:
    """
    Alle Sprachen, die das Modell selbst gemeldet hat — roh, ohne Wiederholung.

    ``whisper-1`` meldet ``language`` als Wort („german"), ``gpt-transcribe`` eine
    Liste ``languages: [{"code": "it"}, {"code": "de"}]``. Die Liste hat KEINE
    Rangfolge: am Pruef-Transkript meldete ein ueberwiegend deutsches Stueck
    „it, de". Die Umwandlung in ISO 639-1 macht der Aufrufer. Leer, wenn das
    Modell nichts gesagt hat.
    """
    language = _get(response, "language")
    if isinstance(language, str) and language.strip():
        return [language.strip()]
    found: List[str] = []
    languages = _get(response, "languages")
    if isinstance(languages, (list, tuple)):
        for entry in languages:
            code = _get(entry, "code") if not isinstance(entry, str) else entry
            if isinstance(code, str) and code.strip() and code.strip() not in found:
                found.append(code.strip())
    return found


def reported_language(response: Any) -> Optional[str]:
    """
    Die Sprache des Modells, wenn es genau eine gemeldet hat; sonst None.

    Bei mehreren gemeldeten Sprachen gibt es keine „Hauptsprache" — die erste zu
    nehmen hiess am Pruef-Transkript, ein deutsches Stueck als italienisch zu
    fuehren und es danach komplett ins Deutsche uebersetzen zu lassen.
    """
    found = reported_languages(response)
    return found[0] if len(found) == 1 else None


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


# --- Text-Spracherkennung ------------------------------------------------------
#
# Whisper entscheidet die Sprache je Anfrage (bei uns je 300-s-Stueck) bzw. je
# 30-s-Fenster. Wechselt die Sprache darin, uebersetzt Whisper oft, statt zu
# transkribieren — und avg_logprob bleibt dabei unauffaellig (Pruef-Transkript
# 09.10.2026). Die Sprache des *Texts* je Segment ist die zweite Meinung dazu.

# Kuerzere Texte geben keine verlaessliche Sprache her: None statt raten.
MIN_TEXT_LANGUAGE_CHARS = 20

# Kandidaten fuer die Text-Spracherkennung. Eine offene Liste aller ~75 Sprachen
# liefert bei kurzen Saetzen Exoten (am Pruef-Transkript „Yoruba" fuer einen
# deutschen Satz). Diese Auswahl deckt die Sprachen ab, die der Dienst von Whisper
# kennt (_convert_to_iso_code), plus die uebrigen grossen europaeischen.
TEXT_LANGUAGE_CODES = (
    "de", "it", "en", "fr", "es", "pt", "nl", "pl", "cs", "sk", "sl", "hr", "hu",
    "ro", "ru", "uk", "el", "tr", "sv", "da", "nb", "fi", "ar", "he", "fa", "hi",
    "bn", "zh", "ja", "ko", "th", "vi", "id", "ms", "sw",
)

_detector: Any = None
_detector_lock = threading.Lock()
_detector_unavailable: bool = False


def _language_detector() -> Any:
    """Baut den lingua-Detektor einmal (thread-sicher). None, wenn lingua fehlt."""
    global _detector, _detector_unavailable
    with _detector_lock:
        if _detector is not None or _detector_unavailable:
            return _detector
        try:
            from lingua import IsoCode639_1, Language, LanguageDetectorBuilder
        except ImportError:
            # Kein stiller Default: einmal laut melden, dann text_language None.
            logger.warning(
                "lingua-language-detector ist nicht installiert — text_language bleibt leer "
                "(requirements.txt: lingua-language-detector)"
            )
            _detector_unavailable = True
            return None
        languages = [
            Language.from_iso_code_639_1(getattr(IsoCode639_1, code.upper()))
            for code in TEXT_LANGUAGE_CODES
        ]
        _detector = LanguageDetectorBuilder.from_languages(*languages).build()
        return _detector


def detect_text_language(text: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Sprache eines Segmenttexts (ISO 639-1) und ihre Wahrscheinlichkeit 0–1.

    Reine Textstatistik, kein Modellaufruf. Unter MIN_TEXT_LANGUAGE_CHARS Zeichen
    oder ohne lingua: (None, None).
    """
    cleaned = text.strip()
    if len(cleaned) < MIN_TEXT_LANGUAGE_CHARS:
        return None, None
    detector = _language_detector()
    if detector is None:
        return None, None
    values = detector.compute_language_confidence_values(cleaned)
    if not values:
        return None, None
    top = values[0]
    return top.language.iso_code_639_1.name.lower(), round(float(top.value), 3)


def with_text_language(segment: TranscriptionSegment) -> TranscriptionSegment:
    """Kopie des Segments mit ``text_language`` und ``text_language_prob``."""
    code, prob = detect_text_language(segment.text)
    return dataclass_replace(segment, text_language=code, text_language_prob=prob)


# --- Woerter -------------------------------------------------------------------


def _read_words(response: Any) -> Optional[List[TranscriptionWord]]:
    """Woerter aus ``verbose_json`` (nur mit timestamp_granularities=["word"]).

    None, wenn die Antwort keine Woerter traegt — dann fehlt ``words`` am Segment.
    """
    raw_words = _get(response, "words")
    if not isinstance(raw_words, (list, tuple)):
        return None
    words: List[TranscriptionWord] = []
    for raw in raw_words:
        word = str(_get(raw, "word", "") or "").strip()
        start = _as_float(_get(raw, "start"))
        end = _as_float(_get(raw, "end"))
        if not word or start is None or end is None:
            continue
        start = max(0.0, start)
        words.append(TranscriptionWord(word=word, start=start, end=max(end, start)))
    return words


def _assign_words(
    segments: List[TranscriptionSegment], words: List[TranscriptionWord]
) -> List[TranscriptionSegment]:
    """
    Haengt jedes Wort an das Segment, in dem es beginnt — oder, wenn es in einer
    Luecke zwischen zwei Segmenten beginnt, an das naehere der beiden.

    Whisper liefert Woerter und Segmente getrennt, beide zeitlich sortiert. Das
    letzte Wort eines Segments beginnt oft genau an dessen Ende (Pruef-Transkript:
    95 von 4741 Woertern); es gehoert zum vorigen Segment, nicht zum naechsten.
    Jedes Segment bekommt eine Liste (moeglicherweise leer), weil das Modell
    Woerter geliefert hat.
    """
    if not segments:
        return segments
    buckets: List[List[TranscriptionWord]] = [[] for _ in segments]
    index = 0
    for word in sorted(words, key=lambda w: w.start):
        while index < len(segments) - 1 and word.start >= segments[index].end:
            index += 1
        target = index
        if index > 0 and word.start < segments[index].start:
            # In der Luecke: naeher am Ende des vorigen oder am Beginn des naechsten?
            to_previous = word.start - segments[index - 1].end
            to_next = segments[index].start - word.start
            if to_previous <= to_next:
                target = index - 1
        buckets[target].append(word)
    return [dataclass_replace(segment, words=bucket) for segment, bucket in zip(segments, buckets)]


# --- Segmente ------------------------------------------------------------------


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
    language: Optional[str] = None,
    languages: Optional[List[str]] = None,
) -> Tuple[List[TranscriptionSegment], str]:
    """
    Baut die Segmente einer Anbieter-Antwort und sagt, woher die Werte stammen.

    Reihenfolge: Whisper-Segmente mit Werten (und Woertern, falls geliefert), sonst
    Saetze mit Werten aus den Token-Logprobs, sonst Saetze ohne Werte. Jedes Segment
    traegt die vom Modell fuer diese Anfrage gemeldeten Sprachen (``language`` nur bei
    genau einer, ``languages`` alle) und die aus seinem Text bestimmte
    (``text_language``).

    Args:
        response: Antwort des Anbieters (SDK-Objekt oder Dict)
        text: der Gesamttext, falls keine Segmente kommen
        end_seconds: Dauer der Anfrage (des Stuecks) in Sekunden
        title: Titel (z.B. Kapitel) fuer das erste Segment
        language: vom Modell gemeldete Sprache, wenn es genau eine war, sonst None
        languages: alle vom Modell gemeldeten Sprachen (ISO 639-1)

    Returns:
        (Segmente, quality_source)
    """
    segments, source = _build_segments(response, text=text, end_seconds=end_seconds, title=title)
    reported = list(languages) if languages else ([language] if language else None)
    return [
        with_text_language(dataclass_replace(s, language=language, languages=reported))
        for s in segments
    ], source


def _build_segments(
    response: Any, *, text: str, end_seconds: float, title: Optional[str]
) -> Tuple[List[TranscriptionSegment], str]:
    """Segmente und Herkunft der Werte, noch ohne Sprachfelder."""
    raw_segments = _get(response, "segments")
    if isinstance(raw_segments, (list, tuple)) and raw_segments:
        first = raw_segments[0]
        if _get(first, "avg_logprob") is not None or _get(first, "no_speech_prob") is not None:
            segments = _whisper_segments(raw_segments)
            if segments:
                words = _read_words(response)
                if words is not None:
                    segments = _assign_words(segments, words)
                return segments, "whisper"

    end = end_seconds if end_seconds > 0 else 0.01
    raw_logprobs = _get(response, "logprobs")
    has_logprobs = mean_logprob(raw_logprobs) is not None
    token_values = _align_tokens(text, raw_logprobs) if has_logprobs else None
    if has_logprobs and token_values is None:
        # Ohne Zuordnung keine Werte je Satz: lieber ein ehrlicher Mittelwert je Stueck.
        logger.warning("Token-Logprobs passen nicht auf den Text — ein Segment je Stueck statt je Satz")
        return [
            TranscriptionSegment(
                text=text,
                segment_id=0,
                start=0.0,
                end=end,
                title=title,
                avg_logprob=mean_logprob(raw_logprobs),
                min_logprob=_min_logprob(raw_logprobs),
                compression_ratio=compression_ratio(text),
                quality_source="logprobs",
                time_source="chunk",
            )
        ], "logprobs"

    source = "logprobs" if has_logprobs else "none"
    return _sentence_segments(text, end, title, token_values, source), source


# --- Saetze --------------------------------------------------------------------
#
# gpt-transcribe liefert je Anfrage nur einen Textblock (bei uns 4–5 Minuten) und
# Logprobs je Token, aber keine Zeiten. Damit KnowledgeScout einzelne Saetze
# markieren kann, teilt der Dienst den Text in Saetze und haengt an jeden die Werte
# seiner Tokens. Die Zeit jedes Satzes ist nach seiner Position im Text geschaetzt
# (time_source "estimated"): Sprechtempo als gleichmaessig angenommen.

# Satzende: . ! ? gefolgt von Leerraum. „…" nicht — gpt-transcribe setzt es fuer
# unverstaendliche Stellen mitten im Satz.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
# Kuerzere Bruchstuecke („z.", „Ja.") haengen am vorigen Satz.
MIN_SENTENCE_CHARS = 12


def split_sentences(text: str) -> List[Tuple[int, int]]:
    """Satzgrenzen als (start, end) Zeichenpositionen, ohne Leerraum an den Raendern."""
    spans: List[Tuple[int, int]] = []
    position = 0
    for match in _SENTENCE_BREAK.finditer(text):
        spans.append((position, match.start()))
        position = match.end()
    spans.append((position, len(text)))
    spans = [(s, e) for s, e in spans if text[s:e].strip()]
    merged: List[Tuple[int, int]] = []
    for start, end in spans:
        if merged and (end - start < MIN_SENTENCE_CHARS or merged[-1][1] - merged[-1][0] < MIN_SENTENCE_CHARS):
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _align_tokens(text: str, logprobs: Any) -> Optional[List[Tuple[int, float]]]:
    """
    Ordnet jedem Token seine Zeichenposition im Text zu: [(position, logprob), ...].

    Die Tokens ergeben den Text fast genau; am Pruef-Transkript fehlten nur
    vereinzelt Leerzeichen (Token „provincia.Ad", Text „provincia. Ad"). Deshalb
    darf die Suche ein paar Zeichen Leerraum ueberspringen. Passt ein Token gar
    nicht, gibt es None statt einer falschen Zuordnung.
    """
    if not isinstance(logprobs, (list, tuple)):
        return None
    aligned: List[Tuple[int, float]] = []
    position = 0
    for entry in logprobs:
        token = str(_get(entry, "token", "") or "")
        value = _as_float(_get(entry, "logprob"))
        if not token:
            continue
        index = text.find(token, position, position + len(token) + 3)
        if index < 0:
            stripped = token.strip()
            if not stripped:
                continue
            index = text.find(stripped, position, position + len(token) + 3)
            if index < 0:
                return None
            token = stripped
        if value is not None:
            aligned.append((index, value))
        position = index + len(token)
    return aligned


def _min_logprob(logprobs: Any) -> Optional[float]:
    """Schlechtester Token-Logprob, oder None."""
    if not isinstance(logprobs, (list, tuple)):
        return None
    values = [v for v in (_as_float(_get(e, "logprob")) for e in logprobs) if v is not None]
    return min(values) if values else None


def _sentence_segments(
    text: str,
    end_seconds: float,
    title: Optional[str],
    token_values: Optional[List[Tuple[int, float]]],
    source: str,
) -> List[TranscriptionSegment]:
    """Ein Segment je Satz; Werte aus den Tokens des Satzes, Zeit nach Textposition."""
    spans = split_sentences(text) or [(0, len(text))]
    length = max(len(text), 1)
    single = len(spans) == 1
    segments: List[TranscriptionSegment] = []
    for start_char, end_char in spans:
        sentence = text[start_char:end_char].strip()
        values = [v for pos, v in (token_values or []) if start_char <= pos < end_char]
        start = 0.0 if single else end_seconds * start_char / length
        end = end_seconds if single else end_seconds * end_char / length
        segments.append(
            TranscriptionSegment(
                text=sentence,
                segment_id=len(segments),
                start=start,
                end=max(end, start + 0.01),
                title=title if not segments else None,
                avg_logprob=(sum(values) / len(values)) if values else None,
                min_logprob=min(values) if values else None,
                compression_ratio=compression_ratio(sentence) if source == "logprobs" else None,
                no_speech_prob=None,
                quality_source=source if values or source == "none" else "none",
                time_source="chunk" if single else "estimated",
            )
        )
    return segments
