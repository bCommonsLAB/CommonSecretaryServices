"""
@fileoverview Stueckplanung an Sprechpausen - schneidet lange Aufnahmen fuer die Sprecher-Erkennung

@description
Der Sprecher-Weg (/audio/process-diarized) darf je Anfrage hoechstens 25 MB und 1500 s
schicken (Anbieter-Grenze, Stand 06.10.2026). Wir schneiden deshalb Stuecke bis
20 Minuten — und zwar an Sprechpausen statt hart nach Zeit, damit kein Satz und kein
Sprecherwechsel mitten im Wort zerteilt wird.

Die Planung ist bewusst REIN: Sie bekommt die Gesamtdauer und eine Funktion, die
Stillen in einem Zeitfenster liefert, und gibt Stueckgrenzen zurueck. Die eigentliche
Stille-Erkennung (pydub) liegt beim Aufrufer, damit die Logik ohne Audiodaten
testbar ist.

@module utils.pause_chunking

@exports
- MAX_CHUNK_MS, HARD_LIMIT_MS, SEARCH_WINDOW_MS, MIN_CHUNK_MS: Konstanten
- ChunkPlan: Dataclass - ein geplantes Stueck
- plan_chunks: Plant die Stueckgrenzen
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Sequence, Tuple

# 20 Minuten je Stueck: deutlich unter der Anbieter-Grenze, aber lang genug, damit
# die Sprecher-Labels moeglichst selten neu vergeben werden.
MAX_CHUNK_MS = 20 * 60 * 1000
# Anbieter-Grenze je Anfrage (OpenAI, 06.10.2026). Wird nie ueberschritten.
HARD_LIMIT_MS = 1500 * 1000
# Wie weit vor der 20-Minuten-Marke wir nach einer Pause suchen.
SEARCH_WINDOW_MS = 3 * 60 * 1000
# Kein Stueck kuerzer als eine Minute — ein Splitter am Ende hilft niemandem.
MIN_CHUNK_MS = 60 * 1000

# Liefert Stillen als (start_ms, end_ms) innerhalb des angefragten Fensters.
SilenceFinder = Callable[[int, int], Sequence[Tuple[int, int]]]

# Sprechpause: mindestens so lang und so viel leiser als der Durchschnitt des Fensters.
MIN_SILENCE_MS = 600
SILENCE_BELOW_AVERAGE_DB = 16
SILENCE_SEEK_STEP_MS = 50

# Stufen von streng nach locker. Die strenge Stufe findet echte Pausen in ruhigen
# Aufnahmen; in Diskussionen mit Raumgeraeusch fand sie am Pruef-Transkript
# (49 Min., 9 Suchfenster zu 60 s) nur in einem Fenster etwas. Erst wenn eine Stufe
# im Fenster nichts findet, kommt die naechste — mit der lockersten fanden sich
# Pausen in allen neun Fenstern (Messung 09.10.2026).
SILENCE_LEVELS: Tuple[Tuple[int, int], ...] = (
    (MIN_SILENCE_MS, SILENCE_BELOW_AVERAGE_DB),
    (500, 12),
    (300, 10),
)


def pydub_silence_finder(audio: Any) -> SilenceFinder:
    """
    Stille-Suche mit pydub, nur im angefragten Fenster (nicht ueber die ganze Datei).

    Gemeinsam fuer den normalen Weg (Stuecke um 4–5 Minuten) und den Sprecher-Weg
    (Stuecke bis 20 Minuten). Die Schwelle richtet sich nach der Lautstaerke des
    Fensters, damit leise und laute Aufnahmen gleich behandelt werden; die Stufen
    in SILENCE_LEVELS werden der Reihe nach probiert.
    """
    from pydub.silence import detect_silence

    def find(window_start: int, window_end: int) -> List[Tuple[int, int]]:
        window: Any = audio[window_start:window_end]
        loudness = getattr(window, "dBFS", None)
        if loudness is None or loudness == float("-inf"):
            return []
        for min_silence_ms, below_db in SILENCE_LEVELS:
            found = detect_silence(
                window,
                min_silence_len=min_silence_ms,
                silence_thresh=loudness - below_db,
                seek_step=SILENCE_SEEK_STEP_MS,
            )
            if found:
                return [(window_start + int(s), window_start + int(e)) for s, e in found]
        return []

    return find


@dataclass(frozen=True)
class ChunkPlan:
    """Ein geplantes Stueck.

    Attributes:
        index: Laufende Nummer ab 1 (Stueck 1, Stueck 2, ...)
        start_ms: Beginn in Millisekunden
        end_ms: Ende in Millisekunden (exklusiv)
        cut_at_pause: True, wenn das Ende an einer Sprechpause liegt; False bei
            hartem Schnitt, weil im Suchfenster keine Pause war
    """

    index: int
    start_ms: int
    end_ms: int
    cut_at_pause: bool

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def _pick_cut(silences: Sequence[Tuple[int, int]], window_start: int, window_end: int) -> int | None:
    """Waehlt die laengste Stille im Fenster; bei Gleichstand die spaetere."""
    best: Tuple[int, int] | None = None
    for start, end in silences:
        clipped = (max(start, window_start), min(end, window_end))
        if clipped[1] <= clipped[0]:
            continue
        if best is None or (clipped[1] - clipped[0]) >= (best[1] - best[0]):
            best = clipped
    if best is None:
        return None
    return (best[0] + best[1]) // 2


def plan_chunks(
    total_ms: int,
    find_silences: SilenceFinder,
    max_chunk_ms: int = MAX_CHUNK_MS,
    search_window_ms: int = SEARCH_WINDOW_MS,
    min_chunk_ms: int = MIN_CHUNK_MS,
) -> List[ChunkPlan]:
    """
    Plant die Stueckgrenzen einer Aufnahme.

    Args:
        total_ms: Gesamtdauer der Aufnahme
        find_silences: Liefert Stillen (start_ms, end_ms) in einem Fenster
        max_chunk_ms: Hoechstdauer je Stueck (Default 20 Minuten)
        search_window_ms: Suchfenster vor der Hoechstdauer
        min_chunk_ms: Mindestdauer je Stueck

    Returns:
        Liste der Stuecke in zeitlicher Reihenfolge; ein einziges Stueck, wenn die
        Aufnahme kuerzer als max_chunk_ms ist.

    Raises:
        ValueError: bei unsinnigen Parametern oder einer Hoechstdauer ueber der
            Anbieter-Grenze
    """
    if total_ms <= 0:
        raise ValueError("Die Aufnahme hat keine Dauer")
    if max_chunk_ms > HARD_LIMIT_MS:
        raise ValueError(
            f"Stuecke duerfen hoechstens {HARD_LIMIT_MS // 1000} s lang sein (Anbieter-Grenze), "
            f"verlangt: {max_chunk_ms // 1000} s"
        )
    if min_chunk_ms <= 0 or min_chunk_ms >= max_chunk_ms:
        raise ValueError("min_chunk_ms muss zwischen 0 und max_chunk_ms liegen")

    chunks: List[ChunkPlan] = []
    start = 0
    while total_ms - start > max_chunk_ms:
        target = start + max_chunk_ms
        window_start = max(start + min_chunk_ms, target - search_window_ms)
        cut = _pick_cut(find_silences(window_start, target), window_start, target)
        if cut is None:
            chunks.append(ChunkPlan(len(chunks) + 1, start, target, cut_at_pause=False))
            start = target
        else:
            chunks.append(ChunkPlan(len(chunks) + 1, start, cut, cut_at_pause=True))
            start = cut
    chunks.append(ChunkPlan(len(chunks) + 1, start, total_ms, cut_at_pause=True))
    return chunks
