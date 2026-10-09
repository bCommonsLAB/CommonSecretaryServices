"""Tests fuer die Verlaesslichkeitswerte je Abschnitt.

Der Whisper-Decoder liefert je Segment avg_logprob, compression_ratio und
no_speech_prob; der Dienst hat sie bisher weggeworfen. Geprueft wird:

- Provider: verbose_json mit zwei Segmenten -> zwei TranscriptionSegment mit den
  Werten; json plus Token-Logprobs -> ein Segment mit Mittelwert; Antwort ohne
  beides -> ein Segment, Werte None, quality_source "none".
- Anfrage: whisper bekommt verbose_json, GPT-Modelle json plus include=logprobs,
  Sprecher-Modelle kein include; wird include abgewiesen, geht die Anfrage einmal
  ohne include raus.
- Stueck-Weg: Zeitmarken des zweiten Stuecks beginnen bei >= 60 s.
- Abschlussdaten: die Werte ueberleben den Builder unveraendert, data.language kommt mit.
"""

import asyncio
import io
import math
import time
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.api.audio_completed_data import build_audio_completed_data
from src.core.llm.providers.openai_provider import OpenAIProvider
from src.core.llm.transcription_quality import (
    MIN_TEXT_LANGUAGE_CHARS,
    compression_ratio,
    detect_text_language,
    mean_logprob,
    plan_transcription_request,
    reported_language,
    segments_from_response,
)
from src.core.models.audio import (
    AudioMetadata,
    AudioProcessingResult,
    AudioSegmentInfo,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)
from src.core.models.llm import LLMRequest
from src.processors.diarized_audio_processor import DiarizedAudioProcessor
from src.utils.transcription_utils import WhisperTranscriber

VERBOSE_JSON = SimpleNamespace(
    text="Guten Tag. Danke für die Aufmerksamkeit.",
    language="german",
    duration=12.0,
    segments=[
        SimpleNamespace(
            id=0, start=0.0, end=5.5, text=" Guten Tag.",
            avg_logprob=-0.25, compression_ratio=1.1, no_speech_prob=0.01,
        ),
        SimpleNamespace(
            id=1, start=5.5, end=12.0, text=" Danke für die Aufmerksamkeit.",
            avg_logprob=-1.4, compression_ratio=2.9, no_speech_prob=0.7,
        ),
    ],
    usage=None,
)

JSON_MIT_LOGPROBS = SimpleNamespace(
    text="welfare state welfare state welfare state",
    languages=[SimpleNamespace(code="en")],
    logprobs=[
        SimpleNamespace(token="welfare", logprob=-0.5),
        SimpleNamespace(token=" state", logprob=-1.5),
        SimpleNamespace(token=" welfare", logprob=-1.0),
    ],
    usage=SimpleNamespace(type="duration", seconds=16),
)

NUR_TEXT = SimpleNamespace(text="Nur Text.", usage=None)


class _Client:
    """Merkt sich die Aufrufe und antwortet mit einer vorgegebenen Folge."""

    def __init__(self, antworten: List[Any]) -> None:
        self.aufrufe: List[Dict[str, Any]] = []
        self._antworten = list(antworten)
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, **params: Any) -> Any:
        self.aufrufe.append(params)
        # Die Dauer muss groesser null sein, sonst ist das Rueckfall-Segment nicht konstruierbar.
        time.sleep(0.002)
        antwort = self._antworten.pop(0)
        if isinstance(antwort, Exception):
            raise antwort
        return antwort


def _provider(client: _Client) -> OpenAIProvider:
    with patch("src.core.llm.providers.openai_provider.OpenAI", return_value=client):
        return OpenAIProvider(api_key="test-key")


class TestProviderSegmente(unittest.TestCase):
    """Die Segmente des Modells bleiben erhalten, samt Werten und Herkunft."""

    def test_verbose_json_keeps_every_segment_with_its_values(self) -> None:
        client = _Client([VERBOSE_JSON])
        result, _ = _provider(client).transcribe(b"audio", model="whisper-1", response_format="verbose_json")

        self.assertEqual(len(result.segments), 2)
        first, second = result.segments
        self.assertEqual(first.text, "Guten Tag.")
        self.assertEqual((first.start, first.end), (0.0, 5.5))
        self.assertEqual(first.avg_logprob, -0.25)
        self.assertEqual(first.compression_ratio, 1.1)
        self.assertEqual(first.no_speech_prob, 0.01)
        self.assertEqual(first.quality_source, "whisper")
        self.assertEqual(second.avg_logprob, -1.4)
        self.assertEqual(second.compression_ratio, 2.9)
        self.assertEqual(second.no_speech_prob, 0.7)
        self.assertAlmostEqual(second.confidence or 0.0, math.exp(-1.4))
        self.assertEqual(result.text, "Guten Tag. Danke für die Aufmerksamkeit.")
        self.assertEqual(result.detected_language, "de")
        self.assertEqual(result.source_language, "de")

        params = client.aufrufe[0]
        self.assertEqual(params["response_format"], "verbose_json")
        self.assertNotIn("include", params)

    def test_token_logprobs_become_one_segment_with_mean(self) -> None:
        client = _Client([JSON_MIT_LOGPROBS])
        result, _ = _provider(client).transcribe(
            b"audio", model="gpt-transcribe", language="de", response_format="verbose_json"
        )

        self.assertEqual(len(result.segments), 1)
        segment = result.segments[0]
        self.assertAlmostEqual(segment.avg_logprob or 0.0, -1.0)
        self.assertIsNotNone(segment.compression_ratio)
        self.assertIsNone(segment.no_speech_prob)
        self.assertEqual(segment.quality_source, "logprobs")
        # Ende aus usage.seconds, nicht aus der Antwortzeit.
        self.assertEqual(segment.end, 16.0)
        # Vom Modell gemeldete Sprache getrennt von der Vorgabe des Aufrufers.
        self.assertEqual(result.detected_language, "en")
        self.assertEqual(result.source_language, "de")

        params = client.aufrufe[0]
        self.assertEqual(params["response_format"], "json")
        self.assertEqual(params["include"], ["logprobs"])

    def test_response_without_values_is_one_segment_without_values(self) -> None:
        client = _Client([NUR_TEXT])
        result, _ = _provider(client).transcribe(b"audio", model="gpt-4o-transcribe-diarize", audio_duration=30.0)

        self.assertEqual(len(result.segments), 1)
        segment = result.segments[0]
        self.assertIsNone(segment.avg_logprob)
        self.assertIsNone(segment.compression_ratio)
        self.assertIsNone(segment.no_speech_prob)
        self.assertIsNone(segment.confidence)
        self.assertEqual(segment.quality_source, "none")
        self.assertEqual(segment.end, 30.0)
        self.assertIsNone(result.detected_language)
        self.assertNotIn("include", client.aufrufe[0])

    def test_rejected_include_is_retried_without_it(self) -> None:
        fehler = Exception("Error code: 400 - Logprobs are not supported for diarization models")
        client = _Client([fehler, NUR_TEXT])
        result, _ = _provider(client).transcribe(b"audio", model="unbekanntes-modell")

        self.assertEqual(len(client.aufrufe), 2)
        self.assertEqual(client.aufrufe[0]["include"], ["logprobs"])
        self.assertNotIn("include", client.aufrufe[1])
        self.assertEqual(result.segments[0].quality_source, "none")


class TestSpracheUndWoerter(unittest.TestCase):
    """Teil 2: Sprache je Segment (Modell und Text) und Wort-Zeitmarken."""

    def _verbose_mit_woertern(self) -> SimpleNamespace:
        return SimpleNamespace(
            text="…",
            language="german",
            duration=12.0,
            segments=[
                SimpleNamespace(start=0.0, end=5.0, text=" Jährlich werden Schafe und Ziegen erhoben.",
                                avg_logprob=-0.2, compression_ratio=1.1, no_speech_prob=0.01),
                SimpleNamespace(start=5.0, end=12.0, text=" Ogni anno le uova e le zuccherie vengono intervistate.",
                                avg_logprob=-0.7, compression_ratio=1.4, no_speech_prob=0.79),
            ],
            words=[
                SimpleNamespace(word="Jährlich", start=0.1, end=0.6),
                SimpleNamespace(word="werden", start=0.6, end=0.9),
                SimpleNamespace(word="Ogni", start=5.2, end=5.5),
                SimpleNamespace(word="anno", start=5.5, end=5.8),
                SimpleNamespace(word="Nachzügler", start=12.5, end=12.9),
            ],
            usage=None,
        )

    def test_segments_carry_model_language_text_language_and_words(self) -> None:
        client = _Client([self._verbose_mit_woertern()])
        result, _ = _provider(client).transcribe(
            b"audio", model="whisper-1", response_format="verbose_json", word_timestamps=True
        )

        first, second = result.segments
        # Modell-Sprache gilt fuer die ganze Anfrage, die Text-Sprache je Segment.
        self.assertEqual((first.language, second.language), ("de", "de"))
        self.assertEqual(first.text_language, "de")
        self.assertEqual(second.text_language, "it")
        self.assertIsNotNone(second.text_language_prob)
        assert first.words is not None and second.words is not None
        self.assertEqual([w.word for w in first.words], ["Jährlich", "werden"])
        # Woerter nach dem letzten Segment haengen am letzten Segment.
        self.assertEqual([w.word for w in second.words], ["Ogni", "anno", "Nachzügler"])
        self.assertEqual(client.aufrufe[0]["timestamp_granularities"], ["segment", "word"])

    def test_word_timestamps_are_off_by_default(self) -> None:
        # Messung 09.10.: mit Wort-Zeitmarken laesst whisper-1 bis zu 23 % Text weg.
        client = _Client([VERBOSE_JSON])
        result, _ = _provider(client).transcribe(b"audio", model="whisper-1", response_format="verbose_json")
        self.assertNotIn("timestamp_granularities", client.aufrufe[0])
        self.assertNotIn("words", result.segments[0].to_dict())
        self.assertEqual(result.segments[0].language, "de")

    def test_word_in_gap_goes_to_nearer_segment(self) -> None:
        response = {
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "per favore", "avg_logprob": -0.1, "compression_ratio": 1.0, "no_speech_prob": 0.0},
                {"start": 20.0, "end": 25.0, "text": "Siamo stati", "avg_logprob": -0.1, "compression_ratio": 1.0, "no_speech_prob": 0.0},
            ],
            "words": [
                {"word": "per", "start": 4.0, "end": 4.5},
                {"word": "favore", "start": 5.0, "end": 5.4},
                {"word": "Siamo", "start": 19.0, "end": 19.5},
                {"word": "stati", "start": 20.1, "end": 20.5},
            ],
        }
        segments, _ = segments_from_response(response, text="", end_seconds=25.0)
        assert segments[0].words is not None and segments[1].words is not None
        self.assertEqual([w.word for w in segments[0].words], ["per", "favore"])
        self.assertEqual([w.word for w in segments[1].words], ["Siamo", "stati"])

    def test_short_text_has_no_text_language(self) -> None:
        segments, _ = segments_from_response(
            {"text": "Grazie.", "logprobs": [{"logprob": -0.1}]}, text="Grazie.", end_seconds=3.0, language="it"
        )
        self.assertIsNone(segments[0].text_language)
        self.assertIsNone(segments[0].text_language_prob)
        self.assertEqual(segments[0].language, "it")

    def test_detect_text_language_threshold(self) -> None:
        self.assertEqual(detect_text_language("x" * (MIN_TEXT_LANGUAGE_CHARS - 1)), (None, None))
        code, prob = detect_text_language("Also ich fasse jetzt kurz auf Italienisch zusammen.")
        self.assertEqual(code, "de")
        assert prob is not None
        self.assertGreater(prob, 0.5)

    def test_models_without_words_have_no_words_key(self) -> None:
        client = _Client([JSON_MIT_LOGPROBS])
        result, _ = _provider(client).transcribe(b"audio", model="gpt-transcribe")
        self.assertNotIn("words", result.segments[0].to_dict())
        self.assertNotIn("timestamp_granularities", client.aufrufe[0])

    def test_words_survive_dict_roundtrip(self) -> None:
        segment = TranscriptionSegment(
            "Hallo Welt", 0, 1.0, 2.0, language="de", words=[TranscriptionWord("Hallo", 1.0, 1.4)]
        )
        again = TranscriptionSegment.from_dict(segment.to_dict())
        self.assertEqual(again.words, [TranscriptionWord("Hallo", 1.0, 1.4)])
        self.assertEqual(again.language, "de")


class TestAnfrageplan(unittest.TestCase):
    def test_whisper_gets_verbose_json_without_include(self) -> None:
        plan = plan_transcription_request("whisper-1", "verbose_json")
        self.assertEqual((plan.response_format, plan.include), ("verbose_json", None))
        self.assertIsNone(plan.timestamp_granularities)

    def test_word_timestamps_only_on_request_and_only_for_whisper(self) -> None:
        self.assertEqual(
            plan_transcription_request("whisper-1", None, word_timestamps=True).timestamp_granularities,
            ["segment", "word"],
        )
        self.assertIsNone(plan_transcription_request("gpt-transcribe", None, word_timestamps=True).timestamp_granularities)

    def test_gpt_models_get_json_with_logprobs(self) -> None:
        for model in ("gpt-transcribe", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"):
            plan = plan_transcription_request(model, "verbose_json")
            self.assertEqual((plan.response_format, plan.include), ("json", ["logprobs"]), model)

    def test_diarize_model_gets_no_include(self) -> None:
        plan = plan_transcription_request("gpt-4o-transcribe-diarize", None)
        self.assertEqual((plan.response_format, plan.include), ("json", None))

    def test_plain_formats_are_passed_through(self) -> None:
        plan = plan_transcription_request("gpt-transcribe", "srt")
        self.assertEqual((plan.response_format, plan.include), ("srt", None))


class TestRechenhilfen(unittest.TestCase):
    def test_compression_ratio_rises_with_repetition(self) -> None:
        normal = compression_ratio("Heute sprechen wir über den Sozialstaat und das Jahr 2015.")
        schleife = compression_ratio(" ".join(["welfare state"] * 20))
        self.assertIsNotNone(normal)
        self.assertIsNotNone(schleife)
        assert normal is not None and schleife is not None
        self.assertGreater(schleife, 2.4)
        self.assertLess(normal, 2.4)
        self.assertIsNone(compression_ratio(""))

    def test_mean_logprob_ignores_entries_without_number(self) -> None:
        self.assertAlmostEqual(mean_logprob([{"logprob": -1.0}, {"logprob": None}, {"token": "x"}, {"logprob": -3.0}]) or 0.0, -2.0)
        self.assertIsNone(mean_logprob([]))
        self.assertIsNone(mean_logprob(None))

    def test_reported_language_reads_both_shapes(self) -> None:
        self.assertEqual(reported_language({"language": "german"}), "german")
        self.assertEqual(reported_language({"languages": [{"code": "it"}]}), "it")
        self.assertIsNone(reported_language({"text": "nur Text"}))

    def test_segments_from_response_skips_empty_whisper_segments(self) -> None:
        response = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "   ", "avg_logprob": -0.1, "compression_ratio": 1.0, "no_speech_prob": 0.0},
                {"start": 1.0, "end": 1.0, "text": "Hallo", "avg_logprob": -0.1, "compression_ratio": 1.0, "no_speech_prob": 0.0},
            ]
        }
        segments, source = segments_from_response(response, text="Hallo", end_seconds=1.0)
        self.assertEqual(source, "whisper")
        self.assertEqual(len(segments), 1)
        self.assertGreater(segments[0].end, segments[0].start)


class TestSegmentModell(unittest.TestCase):
    def test_confidence_is_derived_from_avg_logprob_and_clipped(self) -> None:
        self.assertAlmostEqual(TranscriptionSegment("x", 0, 0.0, 1.0, avg_logprob=-0.5).confidence or 0.0, math.exp(-0.5))
        self.assertEqual(TranscriptionSegment("x", 0, 0.0, 1.0, avg_logprob=0.3).confidence, 1.0)
        self.assertIsNone(TranscriptionSegment("x", 0, 0.0, 1.0).confidence)

    def test_unknown_quality_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TranscriptionSegment("x", 0, 0.0, 1.0, quality_source="geraten")

    def test_from_dict_accepts_old_cache_entries_and_unknown_keys(self) -> None:
        alt = {"text": "Hallo", "segment_id": 0, "start": 0.0, "end": 1.0, "speaker": None, "confidence": 1.0, "title": None}
        self.assertEqual(TranscriptionSegment.from_dict(alt).confidence, 1.0)
        neu = dict(alt, avg_logprob=-0.2, quality_source="whisper", zukunft="egal")
        self.assertEqual(TranscriptionSegment.from_dict(neu).quality_source, "whisper")

    def test_to_dict_carries_values_and_result_exposes_them_flat(self) -> None:
        segment = TranscriptionSegment("Hallo", 0, 0.0, 1.0, avg_logprob=-0.2, compression_ratio=1.3, no_speech_prob=0.05, quality_source="whisper")
        result = AudioProcessingResult(
            transcription=TranscriptionResult(text="Hallo", source_language="de", segments=[segment], detected_language="de"),
            metadata=AudioMetadata(duration=1.0, process_dir="x"),
        )
        data = result.to_dict()
        self.assertEqual(data["language"], "de")
        self.assertEqual(data["segments"][0]["avg_logprob"], -0.2)
        self.assertEqual(data["segments"][0]["quality_source"], "whisper")
        self.assertEqual(data["segments"], data["transcription"]["segments"])
        # Rueckweg aus dem Cache verliert nichts.
        wieder = AudioProcessingResult.from_dict(data)
        self.assertEqual(wieder.transcription.segments[0].no_speech_prob, 0.05)
        self.assertEqual(wieder.transcription.detected_language, "de")


class _StueckProvider:
    """Provider-Attrappe: je Aufruf ein Ergebnis mit Segmenten relativ zum Stueck."""

    def __init__(self) -> None:
        self.aufrufe: List[Dict[str, Any]] = []

    def transcribe(self, audio_data: Any, model: str, language: Optional[str], context: Any, **kwargs: Any) -> Any:
        self.aufrufe.append(kwargs)
        n = len(self.aufrufe)
        # Wie der Provider: Sprache je Anfrage (Stueck 1 deutsch, Stueck 2 italienisch),
        # Zeiten und Woerter relativ zum Stueck.
        chunk_language = "de" if n == 1 else "it"
        segments = [
            TranscriptionSegment(
                f"Satz {n}a", 0, 0.0, 20.0, avg_logprob=-0.3, quality_source="whisper",
                language=chunk_language, words=[TranscriptionWord("Satz", 0.5, 0.9)],
            ),
            TranscriptionSegment(
                f"Satz {n}b", 1, 20.0, 60.0, avg_logprob=-1.2, quality_source="whisper",
                language=chunk_language, words=[TranscriptionWord("Satz", 21.0, 21.4)],
            ),
        ]
        result = TranscriptionResult(
            text=f"Satz {n}a Satz {n}b", source_language="de", segments=segments,
            detected_language="de" if n == 1 else "it",
        )
        return result, LLMRequest(model=model, purpose="transcription", tokens=10, duration=5.0, processor="Test")


def _transcriber(provider: Any) -> WhisperTranscriber:
    transcriber = object.__new__(WhisperTranscriber)
    transcriber.provider = provider
    transcriber.model = "whisper-1"
    transcriber._logger = None
    # LLM-Tracking braucht hier keinen Processor; setattr statt Zuweisung, damit mypy die Signatur nicht vergleicht.
    setattr(transcriber, "create_llm_request", lambda **kwargs: None)
    return transcriber


class TestStueckWegSpracheUndWoerter(unittest.TestCase):
    """Auftrag Teil 2: Sprache je Stueck und Woerter ueberleben den Stueck-Weg."""

    def test_language_per_chunk_and_word_offsets(self) -> None:
        chunks = [
            AudioSegmentInfo(file_path=io.BytesIO(b"a"), start=0.0, end=60.0, duration=60.0),
            AudioSegmentInfo(file_path=io.BytesIO(b"b"), start=60.0, end=120.0, duration=60.0),
        ]
        result = asyncio.run(
            _transcriber(_StueckProvider()).transcribe_segments(segments=chunks, source_language="auto", target_language="de")
        )

        self.assertEqual([s.language for s in result.segments], ["de", "de", "it", "it"])
        second_chunk_word = result.segments[2].words
        assert second_chunk_word is not None
        self.assertEqual((second_chunk_word[0].start, second_chunk_word[0].end), (60.5, 60.9))
        self.assertEqual(result.segments[3].to_dict()["words"], [{"word": "Satz", "start": 81.0, "end": 81.4}])


class TestStueckWeg(unittest.TestCase):
    def test_second_chunk_segments_start_at_or_after_sixty_seconds(self) -> None:
        provider = _StueckProvider()
        chunks = [
            AudioSegmentInfo(file_path=io.BytesIO(b"a"), start=0.0, end=60.0, duration=60.0),
            AudioSegmentInfo(file_path=io.BytesIO(b"b"), start=60.0, end=120.0, duration=60.0),
        ]
        result = asyncio.run(
            _transcriber(provider).transcribe_segments(segments=chunks, source_language="de", target_language="de")
        )

        self.assertEqual(len(result.segments), 4)
        self.assertEqual([s.segment_id for s in result.segments], [0, 1, 2, 3])
        self.assertTrue(all(s.start >= 60.0 for s in result.segments[2:]))
        self.assertEqual(result.segments[2].start, 60.0)
        self.assertEqual(result.segments[3].end, 120.0)
        self.assertEqual(result.segments[3].avg_logprob, -1.2)
        self.assertEqual(result.segments[3].quality_source, "whisper")
        # Der Provider erfaehrt die Stueckdauer fuer den Fall ohne Zeiten in der Antwort.
        self.assertEqual(provider.aufrufe[0]["audio_duration"], 60.0)
        # Erkannte Sprache: je ein Stueck "de" und "it" -> die zuerst gemeldete gewinnt.
        self.assertEqual(result.detected_language, "de")


class TestAbschlussdaten(unittest.TestCase):
    def test_segment_values_survive_the_builder_unchanged(self) -> None:
        segment = {
            "text": "welfare state welfare state", "segment_id": 3, "start": 100.0, "end": 104.0,
            "speaker": None, "confidence": 0.2, "title": None,
            "avg_logprob": -1.6, "compression_ratio": 2.7, "no_speech_prob": 0.65, "quality_source": "whisper",
        }
        data = build_audio_completed_data({
            "data": {
                "transcription": {"text": "…", "source_language": "de", "segments": [segment]},
                "segments": [segment],
                "language": "de",
            }
        })
        self.assertEqual(data["segments"], [segment])
        self.assertEqual(data["language"], "de")

    def test_diarized_data_marks_segments_as_without_values(self) -> None:
        result = AudioProcessingResult(
            transcription=TranscriptionResult(
                text="**Sprecher A:** Hallo", source_language="de",
                segments=[TranscriptionSegment("Hallo", 0, 0.0, 1.0, speaker="Sprecher A")],
                detected_language=None,
            ),
            metadata=AudioMetadata(duration=1.0, process_dir="x"),
        )
        data = DiarizedAudioProcessor._to_data(result, "gpt-4o-transcribe-diarize", [], chunk_count=1, from_cache=False)
        segment = data["segments"][0]
        self.assertEqual(segment["speaker"], "Sprecher A")
        self.assertEqual(segment["quality_source"], "none")
        self.assertIsNone(segment["avg_logprob"])
        self.assertIsNone(data["language"])
        self.assertEqual(data["speakers"], ["Sprecher A"])


if __name__ == "__main__":
    unittest.main()
