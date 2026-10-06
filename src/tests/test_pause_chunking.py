"""Tests fuer die Stueckplanung an Sprechpausen (Sprecher-Weg).

Geprueft wird, dass kurze Aufnahmen ganz bleiben, lange an einer Pause vor der
20-Minuten-Marke geschnitten werden, ohne Pause hart geschnitten wird, kein Stueck
die Anbieter-Grenze ueberschreitet und die Nummern je Stueck eindeutig sind.
"""

import unittest
from typing import List, Sequence, Tuple

from src.utils.pause_chunking import (
    HARD_LIMIT_MS,
    MAX_CHUNK_MS,
    MIN_CHUNK_MS,
    SEARCH_WINDOW_MS,
    plan_chunks,
)

MINUTE = 60 * 1000


def _finder(silences: Sequence[Tuple[int, int]]):
    """Stille-Suche ueber eine feste Liste, wie sie pydub liefern wuerde."""

    def find(window_start: int, window_end: int) -> List[Tuple[int, int]]:
        return [(s, e) for s, e in silences if e > window_start and s < window_end]

    return find


class TestKurzeAufnahme(unittest.TestCase):
    def test_under_twenty_minutes_is_one_chunk(self) -> None:
        chunks = plan_chunks(15 * MINUTE, _finder([(5 * MINUTE, 5 * MINUTE + 800)]))

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0].start_ms, chunks[0].end_ms), (0, 15 * MINUTE))
        self.assertEqual(chunks[0].index, 1)

    def test_exactly_twenty_minutes_is_one_chunk(self) -> None:
        chunks = plan_chunks(MAX_CHUNK_MS, _finder([]))

        self.assertEqual(len(chunks), 1)


class TestSchnittAnPause(unittest.TestCase):
    def test_cut_lands_in_the_pause_before_the_limit(self) -> None:
        # 48-Minuten-Diskussion (Prueffall): Pausen bei 18:30 und 37:00.
        pause_a = (18 * MINUTE + 30_000, 18 * MINUTE + 31_200)
        pause_b = (37 * MINUTE, 37 * MINUTE + 900)
        chunks = plan_chunks(48 * MINUTE, _finder([pause_a, pause_b]))

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].end_ms, (pause_a[0] + pause_a[1]) // 2)
        self.assertEqual(chunks[1].start_ms, chunks[0].end_ms)
        self.assertEqual(chunks[1].end_ms, (pause_b[0] + pause_b[1]) // 2)
        self.assertEqual(chunks[2].end_ms, 48 * MINUTE)
        self.assertTrue(all(c.cut_at_pause for c in chunks))

    def test_longest_pause_in_window_wins(self) -> None:
        short = (18 * MINUTE, 18 * MINUTE + 700)
        long = (17 * MINUTE + 30_000, 17 * MINUTE + 32_000)
        chunks = plan_chunks(30 * MINUTE, _finder([short, long]))

        self.assertEqual(chunks[0].end_ms, (long[0] + long[1]) // 2)

    def test_pause_outside_search_window_is_ignored(self) -> None:
        early = (5 * MINUTE, 5 * MINUTE + 3000)
        chunks = plan_chunks(30 * MINUTE, _finder([early]))

        # Keine Pause im Fenster [17:00, 20:00] -> harter Schnitt bei 20:00.
        self.assertEqual(chunks[0].end_ms, MAX_CHUNK_MS)
        self.assertFalse(chunks[0].cut_at_pause)
        self.assertEqual(MAX_CHUNK_MS - SEARCH_WINDOW_MS, 17 * MINUTE)


class TestGrenzen(unittest.TestCase):
    def test_hard_cut_without_any_pause(self) -> None:
        chunks = plan_chunks(133 * MINUTE, _finder([]))  # 2 h 13 min, Prueffall gesamt

        self.assertEqual(len(chunks), 7)
        self.assertTrue(all(c.duration_ms <= MAX_CHUNK_MS for c in chunks))
        self.assertEqual(sum(c.duration_ms for c in chunks), 133 * MINUTE)

    def test_no_chunk_exceeds_provider_limit(self) -> None:
        chunks = plan_chunks(5 * 60 * MINUTE, _finder([]))

        self.assertTrue(all(c.duration_ms <= HARD_LIMIT_MS for c in chunks))

    def test_chunk_indices_are_unique_and_sequential(self) -> None:
        chunks = plan_chunks(70 * MINUTE, _finder([]))

        self.assertEqual([c.index for c in chunks], [1, 2, 3, 4])

    def test_minimum_chunk_length_is_respected(self) -> None:
        # Eine Pause direkt am Anfang darf nicht zu einem Splitter fuehren.
        chunks = plan_chunks(25 * MINUTE, _finder([(10_000, 12_000)]), max_chunk_ms=MAX_CHUNK_MS, search_window_ms=MAX_CHUNK_MS)

        self.assertTrue(all(c.duration_ms >= MIN_CHUNK_MS for c in chunks[:-1]))

    def test_rejects_chunk_size_above_provider_limit(self) -> None:
        with self.assertRaises(ValueError):
            plan_chunks(60 * MINUTE, _finder([]), max_chunk_ms=HARD_LIMIT_MS + 1)

    def test_rejects_empty_recording(self) -> None:
        with self.assertRaises(ValueError):
            plan_chunks(0, _finder([]))


if __name__ == "__main__":
    unittest.main()
