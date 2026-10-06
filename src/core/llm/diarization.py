"""
@fileoverview Sprecher-Erkennung - Antwort lesen, Labels vergeben, Absaetze bauen

@description
Der Anbieter liefert mit ``response_format=diarized_json`` Segmente mit ``speaker``,
``start``, ``end`` und ``text``. Drei Dinge sind dabei zu tun, und alle drei sind hier
als reine Funktionen gesammelt:

1. Die Antwort lesen — tolerant gegenueber SDK-Objekten und rohen Dicts.
2. Labels je Stueck eindeutig benennen. Sprecher-Kennungen gelten nur innerhalb
   EINER Anfrage: „A" in Stueck 1 ist nicht zwingend „A" in Stueck 2. Deshalb heisst
   es bei mehreren Stuecken „Stueck 1 Sprecher A"; die Zuordnung ueber Stueckgrenzen
   uebernimmt der Korrektur-Schritt mit dem Menschen (kein Raten im Dienst).
3. Aufeinanderfolgende Segmente desselben Sprechers zu einem Absatz zusammenfassen
   und als Markdown mit Praefix je Absatz ausgeben.

@module core.llm.diarization

@exports
- SpeakerSegment: Dataclass - ein Segment mit Sprecher und Zeit (Sekunden, absolut)
- read_diarized_segments: Liest Segmente aus einer Anbieter-Antwort
- label_speaker: Baut das lesbare Label
- merge_consecutive: Fasst Folge-Segmente desselben Sprechers zusammen
- render_markdown: Markdown mit **Label:** je Absatz
- collect_speakers: Alle Labels in Reihenfolge des ersten Auftretens
"""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence


@dataclass(frozen=True)
class SpeakerSegment:
    """Ein Segment mit Sprecher. Zeiten in Sekunden, absolut zur ganzen Aufnahme."""

    speaker: str
    start: float
    end: float
    text: str


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Liest ein Feld aus einem Dict oder einem Objekt (SDK-Modell)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def label_speaker(raw: Any, chunk_index: int, chunk_count: int) -> str:
    """
    Baut das lesbare Label fuer eine Anbieter-Kennung.

    ``A`` wird zu ``Sprecher A``; bei mehreren Stuecken zu ``Stueck 2 Sprecher A``.
    Eine fehlende Kennung ist ein Datenfehler und wird nicht stillschweigend zu
    ``Sprecher ?``.
    """
    name = str(raw).strip() if raw is not None else ""
    if not name:
        raise ValueError("Segment ohne Sprecher-Kennung in der Anbieter-Antwort")
    label = f"Sprecher {name}"
    if chunk_count > 1:
        label = f"Stück {chunk_index} {label}"
    return label


def read_diarized_segments(
    response: Any,
    chunk_index: int = 1,
    chunk_count: int = 1,
    offset_seconds: float = 0.0,
) -> List[SpeakerSegment]:
    """
    Liest die Segmente einer ``diarized_json``-Antwort.

    Args:
        response: Antwort des Anbieters (SDK-Objekt oder Dict) mit ``segments``
        chunk_index: Nummer des Stuecks ab 1
        chunk_count: Anzahl aller Stuecke (entscheidet ueber das Label-Praefix)
        offset_seconds: Beginn des Stuecks in der ganzen Aufnahme

    Raises:
        ValueError: wenn die Antwort keine Segmentliste traegt — dann war es kein
            ``diarized_json`` und wir melden das statt einen Volltext unterzuschieben
    """
    raw_segments = _get(response, "segments")
    if not isinstance(raw_segments, (list, tuple)):
        raise ValueError(
            "Anbieter-Antwort ohne 'segments' — Sprecher-Erkennung braucht response_format=diarized_json"
        )

    segments: List[SpeakerSegment] = []
    for raw in raw_segments:
        text = str(_get(raw, "text", "") or "").strip()
        if not text:
            continue
        start = float(_get(raw, "start", 0.0) or 0.0) + offset_seconds
        end = float(_get(raw, "end", 0.0) or 0.0) + offset_seconds
        segments.append(
            SpeakerSegment(
                speaker=label_speaker(_get(raw, "speaker"), chunk_index, chunk_count),
                start=start,
                end=max(end, start),
                text=text,
            )
        )
    return segments


def merge_consecutive(segments: Sequence[SpeakerSegment]) -> List[SpeakerSegment]:
    """Fasst aufeinanderfolgende Segmente desselben Sprechers zu einem Absatz zusammen."""
    merged: List[SpeakerSegment] = []
    for segment in segments:
        previous: Optional[SpeakerSegment] = merged[-1] if merged else None
        if previous is not None and previous.speaker == segment.speaker:
            merged[-1] = SpeakerSegment(
                speaker=previous.speaker,
                start=previous.start,
                end=max(previous.end, segment.end),
                text=f"{previous.text} {segment.text}".strip(),
            )
        else:
            merged.append(segment)
    return merged


def render_markdown(segments: Sequence[SpeakerSegment]) -> str:
    """Ein Absatz je Sprecherwechsel, Praefix fett, Leerzeile dazwischen."""
    return "\n\n".join(f"**{s.speaker}:** {s.text}" for s in merge_consecutive(segments))


def collect_speakers(segments: Sequence[SpeakerSegment]) -> List[str]:
    """Alle Labels in Reihenfolge des ersten Auftretens, ohne Wiederholung."""
    seen: List[str] = []
    for segment in segments:
        if segment.speaker not in seen:
            seen.append(segment.speaker)
    return seen
