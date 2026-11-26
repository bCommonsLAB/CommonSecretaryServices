"""
Tests fuer RAGProcessor._chunk_markdown (src/processors/rag_processor.py).

Befund 26.11.2026 (KnowledgeScout, Story-Modus): Ein Transkript mit langen Absaetzen (ein Absatz je
Sprecherwechsel, weit ueber chunk_size) kam mit EINEM WORT JE ABSATZ im Index an. Der Rest eines zu
langen Absatzes wurde als Wortliste weitergereicht und spaeter mit Leerzeilen statt Leerzeichen
verbunden; die Laenge zaehlte dabei ein Zeichen je Wortgrenze statt zwei, der Chunk wurde zu gross.
"""
from __future__ import annotations

from typing import List

from src.processors.rag_processor import RAGProcessor


def _processor(chunk_size: int = 100, chunk_overlap: int = 20) -> RAGProcessor:
    """Nur die Chunk-Logik: ohne Initialisierung (kein Voyage-Schluessel, keine Datenbank)."""
    processor = RAGProcessor.__new__(RAGProcessor)
    processor.chunk_size = chunk_size
    processor.chunk_overlap = chunk_overlap
    return processor


def _woerter(anzahl: int, wort: str = "wort") -> str:
    return " ".join(f"{wort}{nummer}" for nummer in range(anzahl))


def test_langer_absatz_bleibt_fliesstext_auch_im_rest() -> None:
    absatz = "**Sprecher A:** " + _woerter(60)  # rund 440 Zeichen, vier Chunks zu je 100
    chunks = _processor()._chunk_markdown(absatz, "doc")
    assert len(chunks) > 2
    for chunk in chunks:
        assert "\n" not in chunk.text
        assert len(chunk.text) <= 100
    # Kein Wort geht verloren, keines doppelt, die Reihenfolge bleibt.
    assert " ".join(chunk.text for chunk in chunks).split() == absatz.split()


def test_rest_des_langen_absatzes_und_folgeabsatz_sind_durch_eine_leerzeile_getrennt() -> None:
    lang = _woerter(30)  # rund 200 Zeichen
    text = f"{lang}\n\nKurzer Absatz danach."
    chunks = _processor()._chunk_markdown(text, "doc")
    letzter = chunks[-1].text
    assert letzter.endswith("\n\nKurzer Absatz danach.")
    rest, folge = letzter.split("\n\n")
    assert folge == "Kurzer Absatz danach."
    assert "\n" not in rest
    woerter: List[str] = " ".join(chunk.text for chunk in chunks).split()
    assert woerter == text.split()


def test_kurze_absaetze_unveraendert() -> None:
    text = "# Titel\n\nErster Absatz.\n\nZweiter Absatz."
    chunks = _processor(chunk_size=1000, chunk_overlap=200)._chunk_markdown(text, "doc")
    assert [chunk.text for chunk in chunks] == ["# Titel\n\n\n\nErster Absatz.\n\nZweiter Absatz."]
    assert chunks[0].heading_context == "Titel"


def test_gleiche_eingabe_gleiche_chunks() -> None:
    text = "**Sprecher A:** " + _woerter(80) + "\n\n**Sprecher B:** " + _woerter(50, "anderes")
    eins = [(c.chunk_index, c.text) for c in _processor()._chunk_markdown(text, "doc")]
    zwei = [(c.chunk_index, c.text) for c in _processor()._chunk_markdown(text, "doc")]
    assert eins == zwei
