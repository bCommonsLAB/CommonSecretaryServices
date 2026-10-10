"""Tests fuer Auftrag F: Transkription ohne nachtraegliche Uebersetzung.

Meldet das Modell fuer ein Stueck genau eine Sprache, die von ``target_language``
abweicht, liess der Dienst den Text dieses Stuecks uebersetzen. Am Pruef-Transkript
(de/it gemischt) war ``transcription.text`` dadurch stellenweise Uebersetzung, ohne
dass der Client es sah.

Geprueft wird:
- Regel: translate=false uebersetzt nie; eine Sprache aus ``languages`` auch nicht
- Stueck-Weg: Vermerk ``translated_chunks`` nur fuer tatsaechlich uebersetzte Stuecke
- Cache-Schluessel trennt translate=false vom Bestand, ohne alte Schluessel zu aendern
- Vermerk ueberlebt to_dict/from_dict und den Webhook-Builder
- Job-Parameter ``translate`` kommt beim Processor an, auch als False
- Log-Zeile beim Aufteilen klingt nicht mehr nach Fehler oder Aufforderung
"""

import asyncio
import io
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.api.audio_completed_data import build_audio_completed_data
from src.core.llm.transcription_context import TranscriptionContext
from src.core.models.audio import (
    AudioMetadata,
    AudioProcessingResult,
    AudioSegmentInfo,
    ChunkTranslation,
    TranscriptionResult,
    TranscriptionSegment,
)
from src.core.models.llm import LLMRequest
from src.processors.audio_cache_key import build_audio_cache_key_base
from src.processors.audio_processor import describe_split
from src.utils.transcription_utils import WhisperTranscriber, translation_decision


class TestRegel(unittest.TestCase):
    def test_same_language_is_never_translated(self) -> None:
        self.assertEqual(translation_decision("de", "de", True, []), (False, "Quelle gleich Ziel"))

    def test_switch_off_wins(self) -> None:
        self.assertEqual(translation_decision("it", "de", False, []), (False, "translate=false"))

    def test_expected_language_is_kept(self) -> None:
        translate, reason = translation_decision("it", "de", True, ["de", "it"])
        self.assertFalse(translate)
        self.assertIn("languages", reason)

    def test_unexpected_language_is_translated_as_before(self) -> None:
        self.assertEqual(translation_decision("sv", "de", True, ["de", "it"])[0], True)
        self.assertEqual(translation_decision("it", "de", True, [])[0], True)


class _Provider:
    """Stueck 1 deutsch, Stueck 2 rein italienisch (das Modell meldet nur 'it')."""

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio_data: Any, model: str, language: Optional[str], context: Any, **kwargs: Any) -> Any:
        self.calls += 1
        italian = self.calls == 2
        text = "Ci sono stati vari punti." if italian else "Guten Tag zusammen."
        code = "it" if italian else "de"
        result = TranscriptionResult(
            text=text,
            source_language=code,
            segments=[TranscriptionSegment(text, 0, 0.0, 60.0, language=code)],
            detected_language=code,
        )
        return result, LLMRequest(model=model, purpose="transcription", tokens=5, duration=1.0, processor="Test")


def _transcriber(translations: List[Dict[str, str]]) -> WhisperTranscriber:
    transcriber = object.__new__(WhisperTranscriber)
    setattr(transcriber, "provider", _Provider())
    transcriber.model = "gpt-transcribe"
    transcriber._logger = None
    setattr(transcriber, "create_llm_request", lambda **kwargs: None)

    def fake_translate(text: str, source_language: str, target_language: str, **_kwargs: Any) -> Any:
        translations.append({"text": text, "from": source_language, "to": target_language})
        return SimpleNamespace(text="Es gab mehrere Punkte.")

    setattr(transcriber, "translate_text", fake_translate)
    return transcriber


def _run(translate: bool = True, languages: Optional[List[str]] = None) -> tuple[TranscriptionResult, List[Dict[str, str]]]:
    translations: List[Dict[str, str]] = []
    chunks = [
        AudioSegmentInfo(file_path=io.BytesIO(b"a"), start=0.0, end=60.0, duration=60.0),
        AudioSegmentInfo(file_path=io.BytesIO(b"b"), start=60.0, end=120.0, duration=60.0),
    ]
    context = TranscriptionContext(languages=languages or [])
    result = asyncio.run(
        _transcriber(translations).transcribe_segments(
            segments=chunks,
            source_language="auto",
            target_language="de",
            transcription_context=context,
            translate=translate,
        )
    )
    return result, translations


class TestStueckWeg(unittest.TestCase):
    def test_default_translates_the_italian_chunk_and_says_so(self) -> None:
        result, translations = _run()
        self.assertEqual(len(translations), 1)
        self.assertIn("Es gab mehrere Punkte.", result.text)
        self.assertEqual(
            result.translated_chunks,
            [ChunkTranslation(index=2, start=60.0, end=120.0, source_language="it", target_language="de")],
        )
        # Die Segmente behalten den Originaltext.
        self.assertEqual(result.segments[1].text, "Ci sono stati vari punti.")

    def test_translate_false_keeps_original_text(self) -> None:
        result, translations = _run(translate=False)
        self.assertEqual(translations, [])
        self.assertIn("Ci sono stati vari punti.", result.text)
        self.assertEqual(result.translated_chunks, [])

    def test_expected_languages_keep_original_text(self) -> None:
        result, translations = _run(languages=["de", "it"])
        self.assertEqual(translations, [])
        self.assertIn("Ci sono stati vari punti.", result.text)
        self.assertEqual(result.translated_chunks, [])


class TestCacheSchluessel(unittest.TestCase):
    def test_translate_false_gets_its_own_key_and_default_is_unchanged(self) -> None:
        default = build_audio_cache_key_base("a.mp3", {"original_filename": "a.mp3"}, target_language="de")
        explicit = build_audio_cache_key_base("a.mp3", {"original_filename": "a.mp3"}, target_language="de", translate=True)
        off = build_audio_cache_key_base("a.mp3", {"original_filename": "a.mp3"}, target_language="de", translate=False)
        self.assertEqual(default, "a.mp3|lang=de")
        self.assertEqual(explicit, default)
        self.assertEqual(off, "a.mp3|lang=de|translate=0")


class TestVermerkImErgebnis(unittest.TestCase):
    def test_translated_chunks_survive_dict_and_builder(self) -> None:
        note = ChunkTranslation(index=3, start=600.0, end=889.5, source_language="it", target_language="de")
        result = AudioProcessingResult(
            transcription=TranscriptionResult(
                text="…", source_language="de",
                segments=[TranscriptionSegment("Ciao a tutti", 0, 600.0, 610.0)],
                translated_chunks=[note],
            ),
            metadata=AudioMetadata(duration=900.0, process_dir="x"),
        )
        data = result.to_dict()
        expected = [{"index": 3, "start": 600.0, "end": 889.5, "source_language": "it", "target_language": "de"}]
        self.assertEqual(data["translated_chunks"], expected)
        self.assertEqual(AudioProcessingResult.from_dict(data).transcription.translated_chunks, [note])
        self.assertEqual(build_audio_completed_data({"data": data})["translated_chunks"], expected)

    def test_old_cache_entries_without_note_read_as_empty(self) -> None:
        old = {"text": "Hallo", "source_language": "de", "segments": []}
        self.assertEqual(TranscriptionResult.from_dict(old).translated_chunks, [])


class TestJobParameter(unittest.TestCase):
    def test_translate_false_from_job_reaches_the_processor(self) -> None:
        from src.core.processing.handlers import audio_handler

        seen: Dict[str, Any] = {}

        class _Processor:
            def __init__(self, *_a: Any, **_k: Any) -> None: ...

            async def process(self, **kwargs: Any) -> Any:
                seen.update(kwargs)
                return SimpleNamespace(
                    status="success",
                    to_dict=lambda: {"status": "success", "data": {"transcription": {"text": "T"}}},
                )

        class _Repo:
            def update_job_status(self, **_k: Any) -> bool:
                return True

            def add_log_entry(self, *_a: Any) -> bool:
                return True

        class _Params:
            filename = "C:/tmp/test.wav"
            source_language = "auto"
            target_language = "de"
            template = None
            use_cache = False
            context: Dict[str, Any] = {}
            webhook: Dict[str, Any] = {}
            extra = {"translate": False, "transcription_context": {"languages": ["de", "it"]}}

        class _Job:
            job_id = "job-f"
            parameters = _Params()

        original = audio_handler.AudioProcessor
        setattr(audio_handler, "AudioProcessor", _Processor)
        try:
            asyncio.run(audio_handler.handle_audio_job(_Job(), _Repo(), object()))  # type: ignore[arg-type]
        finally:
            setattr(audio_handler, "AudioProcessor", original)

        self.assertIs(seen["translate"], False)
        self.assertEqual(seen["transcription_context"].languages, ["de", "it"])


class TestLogZeile(unittest.TestCase):
    def test_split_message_is_neither_an_error_nor_an_instruction(self) -> None:
        whole = describe_split(None, 49.51, pieces=11, cuts_at_pause=10)
        self.assertEqual(
            whole,
            "Lange Aufnahme (49,5 Min.): der Dienst teilt sie automatisch in 11 Stücke "
            "(10 von 10 Schnitten an Sprechpausen), kein Eingriff nötig",
        )
        chapter = describe_split(2, 12.0, pieces=3, cuts_at_pause=1)
        self.assertTrue(chapter.startswith("Kapitel 2 (12,0 Min.): der Dienst teilt es automatisch"))
        self.assertNotIn("zu lang", whole + chapter)


if __name__ == "__main__":
    unittest.main()
