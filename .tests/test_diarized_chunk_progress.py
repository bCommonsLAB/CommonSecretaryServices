"""Jedes fertige Stueck meldet Index, Dauer und Sprecherzahl, bevor der Lauf endet."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List, Tuple

from src.core.llm.transcription_context import TranscriptionContext
from src.processors.diarized_audio_processor import DiarizedAudioProcessor
from src.utils.pause_chunking import ChunkPlan


class _Provider:
    def transcribe_diarized(self, path: Path, model: str, context: TranscriptionContext) -> Tuple[dict[str, Any], object, List[str]]:
        # path entscheidet den Sprecher, damit zwei Stuecke verschiedene Labels haben.
        speaker = "A" if path.name.endswith("1.mp3") else "B"
        return (
            {
                "language": "german",
                "segments": [{"speaker": speaker, "start": 0.0, "end": 1.2, "text": "Hallo"}],
            },
            object(),
            [],
        )

    def _convert_to_iso_code(self, language: str) -> str:
        return "de" if language == "german" else language


def _bind(stub: _Stub) -> _Stub:
    """Die Fortschrittsmethode gehoert der Processor-Klasse, der Test liefert nur den Logger."""
    stub._report_chunk_done = DiarizedAudioProcessor._report_chunk_done.__get__(stub, _Stub)  # type: ignore[attr-defined]
    return stub


class _Stub:
    def __init__(self) -> None:
        self.messages: List[str] = []
        self.requests: List[Any] = []

    def add_llm_requests(self, requests: Any) -> None:
        self.requests.append(requests)

    @property
    def logger(self) -> "_Stub":
        return self

    def info(self, message: str, **_kwargs: Any) -> None:
        self.messages.append(message)

    def warning(self, message: str, **_kwargs: Any) -> None:
        self.messages.append(message)


def test_each_finished_chunk_reports_index_duration_and_speakers() -> None:
    plans = [
        ChunkPlan(index=1, start_ms=0, end_ms=5000, cut_at_pause=True),
        ChunkPlan(index=2, start_ms=5000, end_ms=9000, cut_at_pause=False),
    ]
    notes: List[Tuple[int, int, float, int]] = []
    stub = _bind(_Stub())

    segments, language = asyncio.run(
        DiarizedAudioProcessor._transcribe_chunks(
            stub,  # type: ignore[arg-type]
            _Provider(),
            "gpt-4o-transcribe-diarize",
            plans,
            [Path("chunk_1.mp3"), Path("chunk_2.mp3")],
            TranscriptionContext(),
            on_chunk_done=lambda index, total, duration_s, speaker_count: notes.append(
                (index, total, duration_s, speaker_count)
            ),
        )
    )

    assert sorted(notes) == [(1, 2, 5.0, 1), (2, 2, 4.0, 1)]
    assert language == "de"
    assert len(segments) == 2
    assert len(stub.requests) == 2
    assert any("Stück 1/2 transkribiert" in message for message in stub.messages)


def test_callback_error_does_not_abort_transcription() -> None:
    plans = [ChunkPlan(index=1, start_ms=0, end_ms=1000, cut_at_pause=True)]

    def _boom(_index: int, _total: int, _duration_s: float, _speaker_count: int) -> None:
        raise RuntimeError("webhook weg")

    segments, language = asyncio.run(
        DiarizedAudioProcessor._transcribe_chunks(
            _bind(_Stub()),  # type: ignore[arg-type]
            _Provider(),
            "gpt-4o-transcribe-diarize",
            plans,
            [Path("chunk_1.mp3")],
            TranscriptionContext(),
            on_chunk_done=_boom,
        )
    )

    assert language == "de"
    assert len(segments) == 1
