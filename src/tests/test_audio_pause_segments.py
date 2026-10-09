"""Tests fuer den Schnitt langer Aufnahmen im normalen Audio-Weg.

Vorher wurde jedes Kapitel in gleich lange Teile von hoechstens 5 Minuten zerlegt,
mitten im Satz. Jetzt schneidet der Dienst an der laengsten Sprechpause zwischen
4 und 5 Minuten (Konfiguration ``segment_duration`` / ``segment_search_window``),
ohne Pause hart bei 5 Minuten. Die Zeiten der Stuecke beziehen sich auf die ganze
Datei, auch wenn Kapitel vorgegeben sind (vorher relativ zum Kapitel).
"""

import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Tuple, cast
from unittest.mock import patch

from src.core.models.audio import AudioSegmentInfo, Chapter
from src.processors.audio_processor import AudioProcessor


class _FakeAudio:
    """Gerade genug pydub: Laenge in ms, Ausschnitt, Export."""

    def __init__(self, length_ms: int) -> None:
        self._length = length_ms

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, item: slice) -> "_FakeAudio":
        start = item.start or 0
        stop = self._length if item.stop is None else min(item.stop, self._length)
        return _FakeAudio(max(0, stop - start))

    def export(self, path: str, format: str, parameters: List[str]) -> None:
        Path(path).write_bytes(b"x")


class _Log:
    def info(self, *args: Any, **kwargs: Any) -> None: ...
    def debug(self, *args: Any, **kwargs: Any) -> None: ...
    def error(self, *args: Any, **kwargs: Any) -> None: ...


def _processor() -> AudioProcessor:
    processor = object.__new__(AudioProcessor)
    setattr(processor, "segment_duration", 300)
    setattr(processor, "segment_search_window", 60)
    setattr(processor, "max_segments", 100)
    setattr(processor, "export_format", "mp3")
    setattr(processor, "logger", _Log())
    return processor


def _silences_at(*pauses_ms: Tuple[int, int]) -> Any:
    """Stille-Suche, die feste Pausen (relativ zum Kapitel) im Fenster liefert."""
    def factory(_audio: Any) -> Any:
        def find(window_start: int, window_end: int) -> List[Tuple[int, int]]:
            return [(s, e) for s, e in pauses_ms if s < window_end and e > window_start]
        return find
    return factory


def _pieces(result: Any) -> List[AudioSegmentInfo]:
    return [segment for chapter in result for segment in chapter.segments]


class TestSchnittAnSprechpausen(unittest.TestCase):
    def test_cuts_at_pauses_between_four_and_five_minutes(self) -> None:
        # 11 Minuten; Pausen bei 4:30 und 9:20, eine Pause bei 2:00 liegt ausserhalb des Fensters.
        finder = _silences_at((120_000, 121_000), (270_000, 271_000), (560_000, 561_000))
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.processors.audio_processor.pydub_silence_finder", finder
        ):
            result = _processor().get_audio_segments(cast(Any, _FakeAudio(660_000)), Path(tmp))

        pieces = _pieces(result)
        self.assertEqual([(p.start, p.end) for p in pieces], [(0.0, 270.5), (270.5, 560.5), (560.5, 660.0)])

    def test_without_pause_cuts_hard_at_five_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.processors.audio_processor.pydub_silence_finder", _silences_at()
        ):
            result = _processor().get_audio_segments(cast(Any, _FakeAudio(400_000)), Path(tmp))
        self.assertEqual([(p.start, p.end) for p in _pieces(result)], [(0.0, 300.0), (300.0, 400.0)])

    def test_chapter_times_are_absolute(self) -> None:
        chapters = [
            {"title": "Einleitung", "start_ms": 0, "end_ms": 120_000},
            {"title": "Diskussion", "start_ms": 120_000, "end_ms": 520_000},
        ]
        # Pause im zweiten Kapitel bei 4:40 (relativ zum Kapitel).
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.processors.audio_processor.pydub_silence_finder", _silences_at((280_000, 281_000))
        ):
            result = _processor().get_audio_segments(cast(Any, _FakeAudio(520_000)), Path(tmp), chapters=chapters)

        chapters_out = cast(List[Chapter], result)
        self.assertIsInstance(chapters_out[0], Chapter)
        self.assertEqual([(p.start, p.end) for p in chapters_out[0].segments], [(0.0, 120.0)])
        # Kapitel 2 beginnt bei 120 s; Schnitt bei 120 + 280.5 s.
        self.assertEqual([(p.start, p.end) for p in chapters_out[1].segments], [(120.0, 400.5), (400.5, 520.0)])


class TestStufenDerPausensuche(unittest.TestCase):
    """Eine Pause in lauter Umgebung: nur 13 dB leiser als die Rede, 800 ms lang."""

    def test_relaxed_level_finds_pause_the_strict_level_misses(self) -> None:
        from pydub.generators import Sine
        from pydub.silence import detect_silence
        from src.utils.pause_chunking import pydub_silence_finder

        speech = Sine(220).to_audio_segment(duration=10_000).apply_gain(-20)
        murmur = Sine(220).to_audio_segment(duration=800).apply_gain(-33)
        audio = speech + murmur + speech

        strict = detect_silence(audio, min_silence_len=600, silence_thresh=audio.dBFS - 16, seek_step=50)
        self.assertEqual(strict, [])

        found = pydub_silence_finder(audio)(0, len(audio))
        self.assertEqual(len(found), 1)
        start, end = found[0]
        self.assertTrue(9_900 <= start <= 10_100 and 10_700 <= end <= 10_900, found)


if __name__ == "__main__":
    unittest.main()
