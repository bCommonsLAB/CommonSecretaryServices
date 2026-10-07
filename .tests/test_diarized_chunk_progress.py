"""Jedes fertige Stueck meldet Index, Dauer und Sprecherzahl, bevor der Lauf endet."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, List, Tuple

import pytest

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
    """Fortschritt und Heartbeat gehoeren der Processor-Klasse, der Test liefert nur den Logger."""
    stub._report_chunk_done = DiarizedAudioProcessor._report_chunk_done.__get__(stub, _Stub)  # type: ignore[attr-defined]
    stub._heartbeat = DiarizedAudioProcessor._heartbeat.__get__(stub, _Stub)  # type: ignore[attr-defined]
    return stub


class _SlowProvider(_Provider):
    """Haelt die Antwort zurueck, damit der Heartbeat mehrmals feuern kann."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def transcribe_diarized(self, path: Path, model: str, context: TranscriptionContext) -> Tuple[dict[str, Any], object, List[str]]:
        time.sleep(self.delay_s)
        return super().transcribe_diarized(path, model, context)


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


def test_heartbeat_fires_while_chunk_is_pending_and_stops_afterwards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.processors.diarized_audio_processor.CHUNK_HEARTBEAT_SECONDS", 0.1)
    plans = [ChunkPlan(index=1, start_ms=0, end_ms=5000, cut_at_pause=True)]
    alive: List[Tuple[int, int, float]] = []
    done: List[int] = []
    stub = _bind(_Stub())

    async def run() -> Tuple[int, int]:
        await DiarizedAudioProcessor._transcribe_chunks(
            stub,  # type: ignore[arg-type]
            _SlowProvider(delay_s=0.5),
            "gpt-4o-transcribe-diarize",
            plans,
            [Path("chunk_1.mp3")],
            TranscriptionContext(),
            on_chunk_done=lambda index, _total, _duration_s, _speakers: done.append(index),
            on_chunk_alive=lambda index, total, elapsed_s: alive.append((index, total, elapsed_s)),
        )
        count_at_end = len(alive)
        # Nach der Antwort darf kein Lebenszeichen mehr kommen: die Task ist abgebrochen.
        await asyncio.sleep(0.35)
        return count_at_end, len(alive)

    count_at_end, count_later = asyncio.run(run())

    assert count_at_end >= 2
    assert count_later == count_at_end
    assert all(index == 1 and total == 1 for index, total, _ in alive)
    elapsed = [item[2] for item in alive]
    assert elapsed == sorted(elapsed) and elapsed[0] > 0
    assert done == [1]
    assert any("läuft noch" in message for message in stub.messages)


def test_heartbeat_error_does_not_abort_transcription(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.processors.diarized_audio_processor.CHUNK_HEARTBEAT_SECONDS", 0.1)
    plans = [ChunkPlan(index=1, start_ms=0, end_ms=1000, cut_at_pause=True)]
    stub = _bind(_Stub())

    def _boom(_index: int, _total: int, _elapsed_s: float) -> None:
        raise RuntimeError("webhook weg")

    segments, _language = asyncio.run(
        DiarizedAudioProcessor._transcribe_chunks(
            stub,  # type: ignore[arg-type]
            _SlowProvider(delay_s=0.3),
            "gpt-4o-transcribe-diarize",
            plans,
            [Path("chunk_1.mp3")],
            TranscriptionContext(),
            on_chunk_alive=_boom,
        )
    )

    assert len(segments) == 1
    assert any("nicht gemeldet" in message for message in stub.messages)


def test_no_heartbeat_without_callback() -> None:
    """Sync-Weg: ohne on_chunk_alive keine Task und keine Lebenszeichen im Log."""
    plans = [ChunkPlan(index=1, start_ms=0, end_ms=1000, cut_at_pause=True)]
    stub = _bind(_Stub())

    asyncio.run(
        DiarizedAudioProcessor._transcribe_chunks(
            stub,  # type: ignore[arg-type]
            _Provider(),
            "gpt-4o-transcribe-diarize",
            plans,
            [Path("chunk_1.mp3")],
            TranscriptionContext(),
        )
    )

    assert not any("läuft noch" in message for message in stub.messages)
