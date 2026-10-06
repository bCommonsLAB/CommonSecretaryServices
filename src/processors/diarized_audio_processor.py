"""
@fileoverview Diarized Audio Processor - Datei-Transkription mit Sprecher-Erkennung

@description
Verarbeitet eine Audiodatei fuer ``POST /audio/process-diarized``:

1. Modell und Provider aus der Maske (Use-Case ``diarized_transcription``).
2. Cache pruefen — der Schluessel kennt den Modus, damit der Sprecher-Weg nie das
   Ergebnis des normalen Wegs bekommt.
3. Stuecke bis 20 Minuten, an Sprechpausen geschnitten (``utils.pause_chunking``);
   je Stueck hoechstens 25 MB und 1500 s, sonst Fehler statt stillem Verlust.
4. Je Stueck ``transcribe_diarized`` beim Provider (bis zu 3 parallel), Labels je
   Stueck eindeutig („Stueck 1 Sprecher A"), Zeiten absolut.
5. Absaetze mit Praefix je Sprecherwechsel als ``output_text``; ``segments`` und
   ``speakers`` dazu.

Kontext: ``prompt`` und ``keywords`` nimmt das Sprecher-Modell nicht. Sie werden als
``dropped_context`` gemeldet, nicht verschluckt. Keine Stimmproben, keine
Uebersetzung — die Zuordnung ueber Stueckgrenzen macht der Korrektur-Schritt.

@module processors.diarized_audio_processor

@exports
- DiarizedAudioProcessor: Processor fuer den Sprecher-Weg
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.exceptions import ProcessingError
from src.core.llm.diarization import (
    SpeakerSegment,
    collect_speakers,
    read_diarized_segments,
    render_markdown,
)
from src.core.llm.diarized_transcription import DiarizedTranscriptionService
from src.core.llm.transcription_context import TranscriptionContext, build_context_params
from src.core.models.audio import (
    AudioMetadata,
    AudioProcessingResult,
    TranscriptionResult,
    TranscriptionSegment,
)
from src.core.models.base import BaseResponse
from src.core.models.enums import ProcessorType
from src.processors.audio_cache_key import MODE_DIARIZED
from src.processors.audio_processor import AudioProcessor, AudioSegmentProtocol
from src.utils.pause_chunking import ChunkPlan, HARD_LIMIT_MS, plan_chunks

# Anbieter-Grenze je Anfrage (OpenAI, 06.10.2026).
MAX_REQUEST_BYTES = 25 * 1024 * 1024
# Hoechstens so viele Stuecke gleichzeitig beim Anbieter.
PARALLEL_CHUNKS = 3
# Ein 20-Minuten-Stueck braucht beim Anbieter mehrere Minuten.
CHUNK_TIMEOUT_SECONDS = 900.0
# Sprechpause: mindestens so lang und so viel leiser als der Durchschnitt des Fensters.
MIN_SILENCE_MS = 600
SILENCE_BELOW_AVERAGE_DB = 16
SILENCE_SEEK_STEP_MS = 50


class DiarizedAudioProcessor(AudioProcessor):
    """Datei-Transkription mit Sprecher-Erkennung. Teilt Cache und Konfiguration mit AudioProcessor."""

    def _silence_finder(self, audio: AudioSegmentProtocol):
        """Liefert die Stille-Suche fuer die Stueckplanung (pydub, nur im Fenster)."""
        from pydub.silence import detect_silence  # type: ignore

        def find(window_start: int, window_end: int) -> List[Tuple[int, int]]:
            window: Any = audio[window_start:window_end]
            loudness = getattr(window, "dBFS", None)
            if loudness is None or loudness == float("-inf"):
                return []
            found = detect_silence(
                window,
                min_silence_len=MIN_SILENCE_MS,
                silence_thresh=loudness - SILENCE_BELOW_AVERAGE_DB,
                seek_step=SILENCE_SEEK_STEP_MS,
            )
            return [(window_start + int(s), window_start + int(e)) for s, e in found]

        return find

    def _export_chunks(
        self, audio: AudioSegmentProtocol, plans: Sequence[ChunkPlan], process_dir: Path
    ) -> List[Path]:
        """Schreibt die Stuecke als Mono-16-kHz-Dateien und prueft die Anbieter-Grenzen."""
        chunk_dir = process_dir / "diarized"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        paths: List[Path] = []
        for plan in plans:
            if plan.duration_ms > HARD_LIMIT_MS:
                raise ProcessingError(
                    f"Stück {plan.index} ist {plan.duration_ms // 1000} s lang — erlaubt sind "
                    f"höchstens {HARD_LIMIT_MS // 1000} s je Anfrage",
                    details={"error_code": "CHUNK_TOO_LONG", "chunk": plan.index},
                )
            path = chunk_dir / f"chunk_{plan.index}.{self.export_format}"
            piece: Any = audio[plan.start_ms:plan.end_ms]
            piece.export(str(path), format=self.export_format, parameters=["-ac", "1", "-ar", "16000"])
            size = path.stat().st_size
            if size > MAX_REQUEST_BYTES:
                raise ProcessingError(
                    f"Stück {plan.index} ist {size // (1024 * 1024)} MB groß — erlaubt sind "
                    f"höchstens {MAX_REQUEST_BYTES // (1024 * 1024)} MB je Anfrage",
                    details={"error_code": "CHUNK_TOO_LARGE", "chunk": plan.index, "bytes": size},
                )
            paths.append(path)
            self.logger.info(
                f"Stück {plan.index}/{len(plans)} exportiert",
                start_s=plan.start_ms / 1000.0,
                end_s=plan.end_ms / 1000.0,
                cut_at_pause=plan.cut_at_pause,
                bytes=size,
            )
        return paths

    async def _transcribe_chunks(
        self,
        provider: Any,
        model: str,
        plans: Sequence[ChunkPlan],
        paths: Sequence[Path],
        context: TranscriptionContext,
    ) -> Tuple[List[SpeakerSegment], Optional[str]]:
        """Transkribiert alle Stuecke (bis zu PARALLEL_CHUNKS gleichzeitig), in Reihenfolge."""
        gate = asyncio.Semaphore(PARALLEL_CHUNKS)

        async def one(plan: ChunkPlan, path: Path) -> Tuple[Any, Any]:
            async with gate:
                return await asyncio.wait_for(
                    asyncio.to_thread(provider.transcribe_diarized, path, model, context),
                    timeout=CHUNK_TIMEOUT_SECONDS,
                )

        try:
            results = await asyncio.gather(*(one(p, f) for p, f in zip(plans, paths)))
        except asyncio.TimeoutError as e:
            raise ProcessingError(
                f"Sprecher-Transkription: ein Stück hat nach {int(CHUNK_TIMEOUT_SECONDS)} s nicht geantwortet",
                details={"error_code": "CHUNK_TIMEOUT"},
            ) from e

        segments: List[SpeakerSegment] = []
        detected: Optional[str] = None
        for plan, (response, llm_request, _dropped) in zip(plans, results):
            self.add_llm_requests([llm_request])
            segments.extend(
                read_diarized_segments(
                    response,
                    chunk_index=plan.index,
                    chunk_count=len(plans),
                    offset_seconds=plan.start_ms / 1000.0,
                )
            )
            language = getattr(response, "language", None) if not isinstance(response, dict) else response.get("language")
            if isinstance(language, str) and language.strip() and detected is None:
                detected = provider._convert_to_iso_code(language) if hasattr(provider, "_convert_to_iso_code") else language
        return segments, detected

    def _to_result(
        self, segments: Sequence[SpeakerSegment], language: str, duration_s: float, process_dir: Path, audio: Any
    ) -> AudioProcessingResult:
        """Baut das cachebare Ergebnis; der Text ist das Markdown mit Praefixen."""
        markdown = render_markdown(segments)
        if not markdown.strip():
            raise ProcessingError(
                "Sprecher-Transkription ohne Text — der Anbieter hat keine Segmente geliefert",
                details={"error_code": "EMPTY_TRANSCRIPTION"},
            )
        transcription_segments = [
            TranscriptionSegment(
                text=s.text,
                segment_id=i,
                start=s.start,
                end=s.end if s.end > s.start else s.start + 0.01,
                speaker=s.speaker,
            )
            for i, s in enumerate(segments)
        ]
        return AudioProcessingResult(
            transcription=TranscriptionResult(text=markdown, source_language=language, segments=transcription_segments),
            metadata=AudioMetadata(
                duration=duration_s,
                process_dir=str(process_dir),
                format=self.export_format,
                channels=getattr(audio, "channels", 1) or 1,
            ),
            process_id=self.process_id,
        )

    @staticmethod
    def _to_data(result: AudioProcessingResult, model: str, dropped: List[str], chunk_count: int, from_cache: bool) -> Dict[str, Any]:
        """Flache Antwort fuer Clients (output_text, speakers, segments) plus das verschachtelte Transkript."""
        segments = [
            {"speaker": s.speaker, "start": s.start, "end": s.end, "text": s.text}
            for s in result.transcription.segments
        ]
        speakers = collect_speakers([SpeakerSegment(s["speaker"] or "", s["start"], s["end"], s["text"]) for s in segments])
        return {
            "output_text": result.transcription.text,
            "original_text": result.transcription.text,
            "speakers": speakers,
            "segments": segments,
            "detected_language": result.transcription.source_language,
            "duration": result.metadata.duration,
            "llm_model": model,
            "chunk_count": chunk_count,
            "dropped_context": dropped,
            "transcription": result.transcription.to_dict(),
            "process_id": result.process_id,
            "from_cache": from_cache,
        }

    async def process_diarized(
        self,
        audio_source: str,
        source_info: Optional[Dict[str, Any]] = None,
        source_language: Optional[str] = None,
        use_cache: bool = True,
        transcription_context: Optional[TranscriptionContext] = None,
    ) -> BaseResponse:
        """
        Transkribiert eine Datei mit Sprecher-Erkennung.

        Raises:
            ProcessingError: ohne Modell in der Maske, bei Anbieter-Grenzen, bei
                leerer Antwort oder Fehlern des Anbieters — nie ein Fehlertext als Ergebnis
        """
        source_info = source_info or {}
        base_context = transcription_context or TranscriptionContext()
        context = TranscriptionContext(
            language=base_context.language or source_language or "auto",
            languages=base_context.languages,
            prompt=base_context.prompt,
            keywords=base_context.keywords,
        )

        provider, model = DiarizedTranscriptionService(self.llm_config_manager_or_new()).resolve()
        dropped = list(build_context_params(model, context).dropped)
        for note in dropped:
            self.logger.warning(f"Sprecher-Transkription: Kontext verworfen — {note}")

        cache_key = self._create_cache_key(
            audio_path=str(audio_source), source_info=source_info,
            transcription_context=context, mode=MODE_DIARIZED,
        )
        request_info = {
            "audio_source": str(audio_source), "source_info": source_info,
            "source_language": context.language, "use_cache": use_cache, "mode": MODE_DIARIZED,
        }
        if use_cache and self.is_cache_enabled():
            hit, cached = self.get_from_cache(cache_key)
            if hit and cached is not None:
                return self.create_response(
                    processor_name=ProcessorType.AUDIO.value,
                    result=self._to_data(cached, model, dropped, chunk_count=0, from_cache=True),
                    request_info=request_info, response_class=BaseResponse,
                    from_cache=True, cache_key=cache_key,
                )

        audio = self._process_audio_file(str(audio_source))
        if audio is None:
            raise ProcessingError("Audio konnte nicht geladen werden", details={"error_code": "FILE_ERROR"})
        process_dir = self.get_process_dir(str(audio_source), source_info.get("original_filename"))
        plans = plan_chunks(len(audio), self._silence_finder(audio))
        paths = self._export_chunks(audio, plans, process_dir)
        try:
            segments, detected = await self._transcribe_chunks(provider, model, plans, paths, context)
        finally:
            for path in paths:
                self._safe_delete(path)

        language = detected or (context.language if context.language and context.language != "auto" else "auto")
        result = self._to_result(segments, language, len(audio) / 1000.0, process_dir, audio)
        if use_cache:
            self.save_to_cache(cache_key, result)
        return self.create_response(
            processor_name=ProcessorType.AUDIO.value,
            result=self._to_data(result, model, dropped, chunk_count=len(plans), from_cache=False),
            request_info=request_info, response_class=BaseResponse,
            from_cache=False, cache_key=cache_key,
        )

    def llm_config_manager_or_new(self) -> Any:
        """Nutzt den Config-Manager des Transcribers, falls vorhanden (gleiche Sicht auf die Maske)."""
        transcriber = getattr(self, "transcriber", None)
        manager = getattr(transcriber, "llm_config_manager", None)
        return manager
