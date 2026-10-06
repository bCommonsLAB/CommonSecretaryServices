"""Tests fuer das Antwortformat des Sprecher-Wegs.

Antwort des Anbieters lesen (Dict und SDK-Objekt), Labels je Stueck eindeutig, Zeiten
absolut, Absaetze je Sprecherwechsel, Sprecherliste, Cache-Schluessel mit Modus und
die API-Parameter, die der Provider fuer diarized_json schickt.
"""

import time
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

from src.core.llm.diarization import (
    SpeakerSegment,
    collect_speakers,
    label_speaker,
    merge_consecutive,
    read_diarized_segments,
    render_markdown,
)
from src.core.llm.providers.openai_provider import OpenAIProvider
from src.core.llm.transcription_context import TranscriptionContext
from src.processors.audio_cache_key import MODE_DIARIZED, MODE_PLAIN, build_audio_cache_key_base

ANTWORT: Dict[str, Any] = {
    "text": "Guten Morgen. Danke für die Einladung.",
    "language": "german",
    "segments": [
        {"speaker": "A", "start": 0.0, "end": 3.2, "text": "Guten Morgen."},
        {"speaker": "A", "start": 3.3, "end": 5.0, "text": "Schön, dass es geklappt hat."},
        {"speaker": "B", "start": 5.4, "end": 7.9, "text": "Danke für die Einladung."},
    ],
}


class TestAntwortLesen(unittest.TestCase):
    def test_reads_dict_response_with_speakers(self) -> None:
        segments = read_diarized_segments(ANTWORT)

        self.assertEqual([s.speaker for s in segments], ["Sprecher A", "Sprecher A", "Sprecher B"])
        self.assertEqual(segments[2].text, "Danke für die Einladung.")

    def test_reads_sdk_like_object(self) -> None:
        obj = SimpleNamespace(segments=[SimpleNamespace(speaker="B", start=1.0, end=2.0, text="Hallo")])

        segments = read_diarized_segments(obj)

        self.assertEqual(segments[0].speaker, "Sprecher B")

    def test_offsets_make_times_absolute(self) -> None:
        segments = read_diarized_segments(ANTWORT, chunk_index=2, chunk_count=3, offset_seconds=1200.0)

        self.assertEqual(segments[0].start, 1200.0)
        self.assertEqual(segments[2].end, 1207.9)

    def test_labels_are_unique_per_chunk(self) -> None:
        first = read_diarized_segments(ANTWORT, chunk_index=1, chunk_count=3)
        second = read_diarized_segments(ANTWORT, chunk_index=2, chunk_count=3, offset_seconds=1200.0)

        self.assertEqual(first[0].speaker, "Stück 1 Sprecher A")
        self.assertEqual(second[0].speaker, "Stück 2 Sprecher A")
        self.assertNotEqual(first[0].speaker, second[0].speaker)

    def test_single_chunk_has_no_chunk_prefix(self) -> None:
        self.assertEqual(label_speaker("A", 1, 1), "Sprecher A")

    def test_missing_segments_is_an_error_not_a_fulltext(self) -> None:
        with self.assertRaises(ValueError):
            read_diarized_segments({"text": "nur Volltext"})

    def test_missing_speaker_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            read_diarized_segments({"segments": [{"start": 0, "end": 1, "text": "x"}]})

    def test_empty_text_segments_are_skipped(self) -> None:
        segments = read_diarized_segments({"segments": [{"speaker": "A", "start": 0, "end": 1, "text": "  "}]})

        self.assertEqual(segments, [])


class TestAbsaetze(unittest.TestCase):
    def test_consecutive_same_speaker_merges(self) -> None:
        merged = merge_consecutive(read_diarized_segments(ANTWORT))

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].text, "Guten Morgen. Schön, dass es geklappt hat.")
        self.assertEqual((merged[0].start, merged[0].end), (0.0, 5.0))

    def test_markdown_has_prefix_per_paragraph(self) -> None:
        markdown = render_markdown(read_diarized_segments(ANTWORT))

        self.assertEqual(
            markdown,
            "**Sprecher A:** Guten Morgen. Schön, dass es geklappt hat.\n\n**Sprecher B:** Danke für die Einladung.",
        )

    def test_speakers_in_order_of_first_appearance(self) -> None:
        segments = [SpeakerSegment("Sprecher B", 0, 1, "x"), SpeakerSegment("Sprecher A", 1, 2, "y"), SpeakerSegment("Sprecher B", 2, 3, "z")]

        self.assertEqual(collect_speakers(segments), ["Sprecher B", "Sprecher A"])


class TestCacheSchluessel(unittest.TestCase):
    def test_mode_changes_the_key(self) -> None:
        info = {"original_filename": "diskussion.mp3"}
        plain = build_audio_cache_key_base("/tmp/a.mp3", info, mode=MODE_PLAIN)
        diarized = build_audio_cache_key_base("/tmp/a.mp3", info, mode=MODE_DIARIZED)

        self.assertNotEqual(plain, diarized)
        self.assertIn("|mode=diarized", diarized)
        # Der normale Weg bleibt rueckwaertskompatibel: kein Modus im Schluessel.
        self.assertNotIn("mode=", plain)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_audio_cache_key_base("/tmp/a.mp3", mode="irgendwas")

    def test_context_is_part_of_the_key(self) -> None:
        with_context = build_audio_cache_key_base("/tmp/a.mp3", transcription_context=TranscriptionContext(language="de"), mode=MODE_DIARIZED)
        without = build_audio_cache_key_base("/tmp/a.mp3", mode=MODE_DIARIZED)

        self.assertNotEqual(with_context, without)


class _AufgezeichneterClient:
    def __init__(self) -> None:
        self.aufrufe: List[Dict[str, Any]] = []
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, **params: Any) -> Any:
        self.aufrufe.append(params)
        time.sleep(0.002)
        return SimpleNamespace(text="Guten Tag.", language="german", usage=None, segments=[])


class TestProviderParameter(unittest.TestCase):
    def _provider(self, client: _AufgezeichneterClient) -> OpenAIProvider:
        with patch("src.core.llm.providers.openai_provider.OpenAI", return_value=client):
            return OpenAIProvider(api_key="test-key")

    def test_sends_diarized_json_and_auto_chunking(self) -> None:
        client = _AufgezeichneterClient()
        provider = self._provider(client)

        _response, request, dropped = provider.transcribe_diarized(
            b"audio", model="gpt-4o-transcribe-diarize", context=TranscriptionContext(language="de")
        )

        params = client.aufrufe[0]
        self.assertEqual(params["response_format"], "diarized_json")
        self.assertEqual(params["chunking_strategy"], "auto")
        self.assertEqual(params["language"], "de")
        self.assertEqual(request.purpose, "diarized_transcription")
        self.assertEqual(dropped, [])

    def test_prompt_and_keywords_are_dropped_and_reported(self) -> None:
        client = _AufgezeichneterClient()
        provider = self._provider(client)

        _response, _request, dropped = provider.transcribe_diarized(
            b"audio", model="gpt-4o-transcribe-diarize",
            context=TranscriptionContext(prompt="Journalistenschulung", keywords=["Dachverband"]),
        )

        params = client.aufrufe[0]
        self.assertNotIn("prompt", params)
        self.assertNotIn("keywords", params)
        self.assertNotIn("extra_body", params)
        self.assertEqual(len(dropped), 2)
        self.assertTrue(any("prompt" in d for d in dropped))
        self.assertTrue(any("keywords" in d for d in dropped))

    def test_auto_language_is_not_sent(self) -> None:
        client = _AufgezeichneterClient()
        provider = self._provider(client)

        provider.transcribe_diarized(b"audio", model="gpt-4o-transcribe-diarize", context=TranscriptionContext(language="auto"))

        self.assertNotIn("language", client.aufrufe[0])


if __name__ == "__main__":
    unittest.main()
