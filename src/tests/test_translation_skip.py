"""Tests fuer den No-Op-Pfad in translate_text und die "auto"-Behandlung in transcribe_segments.

Hintergrund: Bei Verwendung von Transkriptions-Modellen, die response.language nicht
zurueckgeben (z.B. gpt-4o-transcribe mit response_format="json"), bleibt die erkannte
Sprache "auto". Frueher hat das eine sinnlose Uebersetzung in die Zielsprache ausgeloest
(z.B. Deutsch -> Deutsch). Siehe
docs/analysis/audio_unnecessary_translation_with_gpt4o_transcribe.md
"""

import io
import unittest
from typing import Any, List
from unittest.mock import patch

from src.core.models.audio import (
    AudioSegmentInfo,
    TranscriptionResult,
    TranscriptionSegment,
)
from src.utils.transcription_utils import WhisperTranscriber


def _make_transcriber() -> WhisperTranscriber:
    """Erzeugt eine minimale WhisperTranscriber-Instanz ohne Config-Last.

    Wir umgehen __init__ bewusst, weil der No-Op-Pfad in translate_text keine
    Instance-Attribute benoetigt und der echte Init Datei-/LLM-Konfig verlangt.
    """
    return WhisperTranscriber.__new__(WhisperTranscriber)


class TestTranslateTextNoOp(unittest.TestCase):
    """Prueft, dass translate_text bei identischen oder leeren Quellen keine LLM-Anfrage stellt."""

    def test_skips_translation_when_source_equals_target(self) -> None:
        # Gleiche Sprache -> Originaltext zurueck, kein LLM-Call
        transcriber = _make_transcriber()
        original = "Das ist ein deutscher Satz."

        result = transcriber.translate_text(
            text=original,
            source_language="de",
            target_language="de",
        )

        self.assertEqual(result.text, original)
        self.assertEqual(result.source_language, "de")
        self.assertEqual(result.target_language, "de")

    def test_skips_translation_when_source_empty(self) -> None:
        # Leere Quelle (frueheres Symptom: "Starte Uebersetzung von  nach de")
        transcriber = _make_transcriber()
        original = "Irgendein Text."

        result = transcriber.translate_text(
            text=original,
            source_language="",
            target_language="de",
        )

        self.assertEqual(result.text, original)

    def test_skips_translation_case_insensitive(self) -> None:
        # Gleicher Code in unterschiedlicher Schreibweise zaehlt als gleich
        transcriber = _make_transcriber()

        result = transcriber.translate_text(
            text="Hello",
            source_language="EN",
            target_language="en",
        )

        self.assertEqual(result.text, "Hello")


class TestTranscribeSegmentsAutoFallback(unittest.IsolatedAsyncioTestCase):
    """Prueft, dass "auto" als source_language nicht laenger eine Uebersetzung erzwingt."""

    async def test_auto_source_skips_translation(self) -> None:
        # Wir mocken transcribe_segment, sodass es einen Erfolg mit source_language="auto"
        # liefert (Symulation des gpt-4o-transcribe-Verhaltens). Erwartung: translate_text
        # wird nicht aufgerufen.
        transcriber = _make_transcriber()

        async def fake_transcribe_segment(**kwargs: Any) -> TranscriptionResult:
            seg = TranscriptionSegment(
                text="Hallo Welt", segment_id=0, start=0.0, end=1.0, title=None
            )
            return TranscriptionResult(
                text="Hallo Welt", source_language="auto", segments=[seg]
            )

        # Minimal-Segment, das nur die Schleife passieren muss (BytesIO erlaubt)
        segments: List[AudioSegmentInfo] = [
            AudioSegmentInfo(file_path=io.BytesIO(b""), start=0.0, end=1.0, duration=1.0)
        ]

        translate_called = {"count": 0}

        def fake_translate(*args: Any, **kwargs: Any) -> Any:
            translate_called["count"] += 1
            raise AssertionError("translate_text darf bei 'auto' nicht aufgerufen werden")

        with patch.object(transcriber, "transcribe_segment", side_effect=fake_transcribe_segment):
            with patch.object(transcriber, "translate_text", side_effect=fake_translate):
                result = await transcriber.transcribe_segments(
                    segments=segments,
                    source_language="auto",
                    target_language="de",
                )

        self.assertEqual(translate_called["count"], 0)
        self.assertIn("Hallo Welt", result.text)
        # Die effektive Sprache faellt auf target_language zurueck
        self.assertEqual(result.source_language, "de")

    async def test_real_translation_still_runs_for_different_languages(self) -> None:
        # Wenn die Quelle erkannt wurde und sich vom Target unterscheidet, MUSS uebersetzt werden
        transcriber = _make_transcriber()

        async def fake_transcribe_segment(**kwargs: Any) -> TranscriptionResult:
            seg = TranscriptionSegment(
                text="Hello world", segment_id=0, start=0.0, end=1.0, title=None
            )
            return TranscriptionResult(
                text="Hello world", source_language="en", segments=[seg]
            )

        segments: List[AudioSegmentInfo] = [
            AudioSegmentInfo(file_path=io.BytesIO(b""), start=0.0, end=1.0, duration=1.0)
        ]

        translate_called = {"count": 0}

        def fake_translate(**kwargs: Any) -> Any:
            translate_called["count"] += 1
            return TranscriptionResult(
                text="Hallo Welt",
                source_language=kwargs.get("source_language", ""),
                segments=[],
            )

        with patch.object(transcriber, "transcribe_segment", side_effect=fake_transcribe_segment):
            with patch.object(transcriber, "translate_text", side_effect=fake_translate):
                result = await transcriber.transcribe_segments(
                    segments=segments,
                    source_language="en",
                    target_language="de",
                )

        self.assertEqual(translate_called["count"], 1)
        self.assertIn("Hallo Welt", result.text)


if __name__ == "__main__":
    unittest.main()
