# pyright: reportUnnecessaryIsInstance=false
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True, slots=True)
class TextChunk:
    """
    Ein Text-Chunk basierend auf Zeichen-Offsets.

    - `start`/`end` sind Offsets im Originaltext (Python-Slicing-Konvention: [start:end]).
    - `index` ist die fortlaufende Chunk-Nummer (0-basiert).
    """

    index: int
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        # Validierung: kurze, klare Regeln.
        if self.index < 0:
            raise ValueError("index muss >= 0 sein")
        if self.start < 0:
            raise ValueError("start muss >= 0 sein")
        if self.end < 0:
            raise ValueError("end muss >= 0 sein")
        if self.end < self.start:
            raise ValueError("end muss >= start sein")
        # `text` ist bereits als `str` typisiert; zusätzliche isinstance-Checks sind redundant.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TextChunk:
        return cls(
            index=int(data["index"]),
            start=int(data["start"]),
            end=int(data["end"]),
            text=str(data["text"]),
        )


def chunk_text_by_chars(*, text: str, chunk_size_chars: int, overlap_chars: int) -> List[TextChunk]:
    """
    Zerlegt einen Text in überlappende Chunks anhand von Zeichen.

    Beispiel:
    - chunk_size_chars=10, overlap_chars=2
      => Fenster: [0:10], [8:18], [16:...]

    Design-Entscheidung:
    - Overlap wird als fixer Zeichen-Overlap umgesetzt (keine Tokenisierung).
    - Bei leerem Text liefern wir [].
    """
    if not text:
        return []
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars muss > 0 sein")
    if overlap_chars < 0:
        raise ValueError("overlap_chars muss >= 0 sein")
    if overlap_chars >= chunk_size_chars:
        raise ValueError("overlap_chars muss < chunk_size_chars sein")

    step = chunk_size_chars - overlap_chars
    chunks: List[TextChunk] = []
    start = 0
    idx = 0
    n = len(text)

    while start < n:
        end = min(start + chunk_size_chars, n)
        chunks.append(TextChunk(index=idx, start=start, end=end, text=text[start:end]))
        idx += 1
        if end >= n:
            break
        start += step  # pyright: ignore[reportUnnecessaryIsInstance]

    return chunks


