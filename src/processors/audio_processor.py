"""Audio Processor für die Verarbeitung von Audio-Dateien."""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Protocol, cast, Sequence, TYPE_CHECKING, IO
from types import TracebackType
import time
import hashlib
import json
import traceback
import tempfile
import gc
import uuid
import math
import requests
from datetime import datetime
from dataclasses import dataclass

from core.models.transformer import TransformationResult
from src.processors.base_processor import BaseProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.types.pydub_types import AudioSegmentProtocol
from src.core.config import Config
from src.processors.transformer_processor import TransformerProcessor
from src.processors.metadata_processor import MetadataProcessor
from src.core.models.base import (
    BaseResponse,
    ProcessingStatus,
    RequestInfo,
    ProcessInfo,
    ErrorInfo,
    ProcessingLogger
)
from src.core.models.metadata import MetadataResponse
from src.core.models.audio import AudioProcessingError
from src.core.models.llm import LLModel

if TYPE_CHECKING:
    from .transformer_processor import TransformationResult

try:
    from pydub import AudioSegment  # type: ignore
except ImportError:
    AudioSegment = None

# Typ-Alias für AudioSegment
AudioSegmentType = AudioSegmentProtocol

@dataclass
class AudioSegmentInfo:
    """Information über ein Audio-Segment."""
    file_path: Path
    title: Optional[str] = None

@dataclass
class ChapterInfo:
    """Information über ein Kapitel."""
    title: str
    segments: Sequence[AudioSegmentInfo]

@dataclass
class AudioMetadata:
    """Metadaten einer Audio-Datei."""
    duration: float
    process_dir: str
    args: Dict[str, Any]

@dataclass
class TranscriptionSegment:
    """Ein Segment einer Transkription."""
    text: str
    segment_id: int
    title: Optional[str] = None

@dataclass
class TranscriptionResult:
    """Ergebnis einer Transkription."""
    text: str
    detected_language: Optional[str]
    segments: Sequence[TranscriptionSegment]
    llms: Sequence[LLModel]

class WhisperTranscriberProtocol(Protocol):
    """Protocol für WhisperTranscriber."""
    def transcribe_segments(
        self,
        segments: Sequence[Union[AudioSegmentInfo, ChapterInfo]],
        logger: ProcessingLogger,
        target_language: Optional[str] = None
    ) -> TranscriptionResult: ...

class MetadataProcessorProtocol(Protocol):
    """Protocol für MetadataProcessor."""
    async def extract_metadata(
        self,
        binary_data: Union[str, Path, bytes],
        content: str,
        context: Optional[Dict[str, Any]] = None
    ) -> MetadataResponse: ...

class TransformerProcessorProtocol(Protocol):
    """Protocol für TransformerProcessor."""
    model: str
    llms: List[LLModel]
    
    def transform(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None
    ) -> 'TransformationResult': ...
    
    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None
    ) -> 'TransformationResult': ...

@dataclass
class AudioProcessingResult:
    """Ergebnis der Audio-Verarbeitung."""
    transcription: TranscriptionResult
    metadata: AudioMetadata
    process_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "transcription": {
                "text": self.transcription.text,
                "detected_language": self.transcription.detected_language,
                "segments": [
                    {
                        "text": s.text,
                        "segment_id": s.segment_id,
                        "title": s.title
                    } for s in self.transcription.segments
                ],
                "llms": [
                    {
                        "model": m.model,
                        "duration": m.duration,
                        "tokens": m.tokens
                    } for m in self.transcription.llms
                ]
            },
            "metadata": {
                "duration": self.metadata.duration,
                "process_dir": self.metadata.process_dir,
                "args": self.metadata.args
            },
            "process_id": self.process_id
        }

@dataclass(frozen=True, init=False)
class AudioResponse(BaseResponse):
    """Standardisierte Response für Audio-Verarbeitung."""
    data: AudioProcessingResult

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: AudioProcessingResult,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die AudioResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)

    def __post_init__(self) -> None:
        """Validiert die Response-Daten."""
        super().__post_init__()

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

class AudioProcessor(BaseProcessor):
    """Audio Processor für die Verarbeitung von Audio-Dateien.
    
    Diese Klasse verarbeitet Audio-Dateien, segmentiert sie bei Bedarf und führt Transkription/Übersetzung durch.
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        max_file_size (int): Maximale Dateigröße in Bytes (Default: 100MB)
        segment_duration (int): Dauer der Audio-Segmente in Sekunden
        export_format (str): Format für exportierte Audio-Dateien
        temp_file_suffix (str): Suffix für temporäre Dateien
        temp_dir (Path): Verzeichnis für temporäre Dateien
        logger (ProcessingLogger): Logger für die Verarbeitung
    """
    
    logger: ProcessingLogger  # Explizite Typ-Annotation für logger
    temp_dir: Path  # Explizite Typ-Annotation für temp_dir
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None) -> None:
        """Initialisiert den AudioProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Konfiguration laden
        config = Config()
        # temp_dir wird vom BaseProcessor verwaltet
        self.max_file_size = config.get('max_file_size', 100 * 1024 * 1024)  # 100MB
        self.segment_duration = config.get('segment_duration', 300)  # 5 Minuten
        self.export_format = config.get('export_format', 'wav')
        self.temp_file_suffix = f".{self.export_format}"
        
        # Prozessoren initialisieren
        self.transformer: TransformerProcessorProtocol = cast(TransformerProcessorProtocol, 
            TransformerProcessor(resource_calculator, process_id))
        self.transcriber: WhisperTranscriberProtocol = cast(WhisperTranscriberProtocol,
            WhisperTranscriber({"process_id": process_id}))
        # logger und temp_dir werden vom BaseProcessor verwaltet
        
        self.resource_calculator: ResourceCalculator = resource_calculator
        
        # Zeitmessung
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.duration: Optional[float] = None

    @property
    def process_info(self) -> ProcessInfo:
        """Gibt die Prozess-Informationen zurück."""
        return ProcessInfo(
            id=self.process_id,
            main_processor="audio",
            started=self.start_time.isoformat() if self.start_time else datetime.now().isoformat(),
            duration=self.duration if self.duration else None,
            completed=self.end_time.isoformat() if self.end_time else None
        )

    def measure_operation(self, operation_name: str):
        """Context Manager für die Zeitmessung von Operationen."""
        class OperationTimer:
            def __init__(self, processor: 'AudioProcessor', name: str):
                self.processor: AudioProcessor = processor
                self.name: str = name
                self.start_time: Optional[datetime] = None

            def __enter__(self) -> "OperationTimer":
                self.start_time = datetime.now()
                self.processor.logger.info(f"Starte Operation: {self.name}")
                return self

            def __exit__(self, exc_type: Optional[type[BaseException]], exc_value: Optional[BaseException], traceback: Optional[TracebackType]) -> Optional[bool]:
                end_time: datetime = datetime.now()
                if self.start_time:
                    duration: float = (end_time - self.start_time).total_seconds()
                    self.processor.logger.info(
                        f"Operation beendet: {self.name}",
                        duration=duration
                    )
                    if exc_type and exc_value:
                        # Konvertiere BaseException zu Exception für den Logger
                        error = Exception(str(exc_value))
                        self.processor.logger.error(
                            f"Fehler in Operation {self.name}",
                            error=error,
                            duration=duration
                        )
                return None

        return OperationTimer(self, operation_name)

    def _safe_delete(self, file_path: Union[str, Path]) -> None:
        """Löscht eine Datei sicher und ignoriert Fehler wenn die Datei nicht gelöscht werden kann.
        
        Args:
            file_path: Pfad zur Datei die gelöscht werden soll
        """
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
        except Exception as e:
            self.logger.warning("Konnte temporäre Datei nicht löschen", error=e)

    def _safe_delete_dir(self, dir_path: Union[str, Path]) -> None:
        """Löscht ein Verzeichnis rekursiv und sicher.
        
        Args:
            dir_path: Pfad zum Verzeichnis das gelöscht werden soll
        """
        try:
            path = Path(dir_path)
            if path.exists():
                shutil.rmtree(str(path))
        except Exception as e:
            self.logger.warning("Konnte Verzeichnis nicht löschen", error=e)

    def cleanup_cache(self, max_age_days: int = 7, delete_transcripts: bool = False) -> None:
        """Löscht alte Cache-Verzeichnisse die älter als max_age_days sind.
        
        Args:
            max_age_days: Maximales Alter in Tagen, nach dem ein Cache-Verzeichnis gelöscht wird
            delete_transcripts: Wenn True, werden auch die Transkriptionen gelöscht, sonst nur die Segmente
        """
        try:
            now: float = time.time()
            if not self.temp_dir.exists():
                return
                
            for dir_path in self.temp_dir.glob("*"):
                if dir_path.is_dir():
                    dir_age: float = now - dir_path.stat().st_mtime
                    if dir_age > (max_age_days * 24 * 60 * 60):
                        if delete_transcripts:
                            # Lösche das komplette Verzeichnis
                            self._safe_delete_dir(dir_path)
                            self.logger.info("Cache-Verzeichnis komplett gelöscht", 
                                           extra={"dir": str(dir_path), "age_days": dir_age/(24*60*60)})
                        else:
                            # Lösche nur die Segment-Dateien
                            for segment_file in dir_path.glob("segment_*.txt"):
                                self._safe_delete(segment_file)
                            for segment_file in dir_path.glob(f"segment_*.{self.export_format}"):
                                self._safe_delete(segment_file)
                            self.logger.info("Cache-Segmente und deren Transkriptionen gelöscht", 
                                           extra={"dir": str(dir_path), "age_days": dir_age/(24*60*60)})
        except Exception as e:
            self.logger.error(f"Fehler beim Cache-Cleanup: {str(e)}")

    def delete_cache(self, filename: str, delete_transcript: bool = False) -> None:
        """Löscht das Cache-Verzeichnis für eine bestimmte Datei."""
        try:
            # Berechne den Hash des Dateinamens
            filename_hash: str = hashlib.md5(filename.encode()).hexdigest()
            if not self.temp_dir.exists():
                return
                
            process_dir: Path = self.temp_dir / filename_hash
            
            if process_dir.exists():
                if delete_transcript:
                    # Lösche das komplette Verzeichnis
                    self._safe_delete_dir(process_dir)
                    self.logger.info("Cache komplett gelöscht", 
                                   extra={"dir": str(process_dir)})
                else:
                    # Lösche nur die Segment-Dateien
                    for segment_file in process_dir.glob("segment_*.txt"):
                        self._safe_delete(segment_file)
                    for segment_file in process_dir.glob(f"segment_*.{self.export_format}"):
                        self._safe_delete(segment_file)
                    self.logger.info("Cache-Segmente gelöscht", 
                                   extra={"dir": str(process_dir)})
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen des Caches: {str(e)}")

    def _load_audio_from_url(self, url: str) -> Path:
        """Lädt eine Audio-Datei von einer URL herunter."""
        temp_file: IO[bytes] = tempfile.NamedTemporaryFile(suffix=self.temp_file_suffix, delete=False)
        response: requests.Response = requests.get(url, stream=True)
        response.raise_for_status()
        
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.close()
        return Path(temp_file.name)

    def _load_audio_from_bytes(self, audio_data: bytes) -> Path:
        """Speichert Audio-Bytes in einer temporären Datei."""
        temp_file = tempfile.NamedTemporaryFile(suffix=self.temp_file_suffix, delete=False)
        temp_file.write(audio_data)
        temp_file.close()
        return Path(temp_file.name)

    def get_process_dir(self, audio_path: str, original_filename: Optional[str] = None, video_id: Optional[str] = None) -> Path:
        """Erstellt ein Verzeichnis für die Verarbeitung basierend auf dem Dateinamen."""
        # Wenn es ein temporärer Pfad ist, versuche den originalen Dateinamen aus source_info zu verwenden
        if video_id:
            process_dir = self.temp_dir / video_id
        elif original_filename:
            path_hash: str = hashlib.md5(str(original_filename).encode()).hexdigest()
            process_dir: Path = self.temp_dir / path_hash
        else:
            path_hash = hashlib.md5(str(audio_path).encode()).hexdigest()
            process_dir = self.temp_dir / path_hash
            
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir

    def process_audio_file(self, file_path: Union[str, Path]) -> Optional[AudioSegmentType]:
        """Verarbeitet eine Audio-Datei und gibt ein AudioSegment zurück.
        
        Args:
            file_path: Pfad zur Audio-Datei
            
        Returns:
            Optional[AudioSegmentType]: Das verarbeitete AudioSegment oder None bei Fehler
            
        Raises:
            ProcessingError: Wenn die Datei nicht verarbeitet werden kann
        """
        try:
            if AudioSegment is None:
                raise ProcessingError("AudioSegment ist nicht verfügbar")
                
            audio = AudioSegment.from_file(str(file_path))  # type: ignore
            
            # Verwende Any für die dynamischen Attribute
            audio_any: Any = audio
            self.logger.info(
                "Audio geladen",
                channels=audio_any.channels,
                sample_width=audio_any.sample_width,
                frame_rate=audio_any.frame_rate
            )
            return audio  # type: ignore
        except Exception as e:
            self.logger.error("Fehler beim Laden der Audio-Datei", error=e)
            raise ProcessingError(f"Fehler beim Laden der Audio-Datei: {str(e)}")

    def _format_duration(self, seconds: float) -> str:
        """Formatiert Sekunden in ein lesbares Format (H:MM:SS).
        
        Args:
            seconds (float): Zeit in Sekunden
            
        Returns:
            str: Formatierte Zeit im Format H:MM:SS (ohne führende Nullen bei Stunden)
        """
        hours = int(seconds) // 3600
        minutes = (int(seconds) % 3600) // 60
        seconds = int(seconds) % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

    def _sanitize_filename(self, filename: str) -> str:
        """Bereinigt einen Dateinamen von ungültigen Zeichen.
        
        Args:
            filename (str): Der zu bereinigende Dateiname
            
        Returns:
            str: Der bereinigte Dateiname
        """
        # Ersetze Backslashes und andere problematische Zeichen
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        original = filename
        for char in invalid_chars:
            filename = filename.replace(char, '-')
        
        if original != filename:
            self.logger.debug("Dateiname bereinigt",
                            original=original,
                            sanitized=filename)
        return filename

    def _check_segment_size(self, segment: AudioSegmentType, format: str = 'mp3') -> int:
        """Prüft die Größe eines Audio-Segments.
        
        Args:
            segment: Das zu prüfende AudioSegment
            format: Das Export-Format
            
        Returns:
            int: Größe in Bytes
        """
        # Erstelle einen zufälligen Dateinamen im process_dir
        temp_filename = f'temp_segment_{uuid.uuid4()}.{format}'
        temp_path = self.temp_dir / temp_filename
        
        try:
            # Exportiere direkt in unser temp_dir
            segment.export(str(temp_path), format=format)  # type: ignore
            size = os.path.getsize(temp_path)
            self.logger.debug("Segment-Größe geprüft",
                            duration_seconds=len(segment)/1000.0,
                            size_bytes=size)
            return size
        finally:
            # Aufräumen
            if temp_path.exists():
                temp_path.unlink()

    def _split_large_segment(self, segment: AudioSegmentType, max_size: int = 25*1024*1024) -> List[AudioSegmentType]:
        """Teilt ein Segment in kleinere Teile auf, wenn es zu groß ist.
        
        Args:
            segment: Das aufzuteilende Segment
            max_size: Maximale Größe in Bytes (Default: 25MB)
            
        Returns:
            List[AudioSegmentType]: Liste der Teilsegmente
        """
        try:
            segments: List[AudioSegmentType] = []
            duration = len(segment)
            
            # Reduziere die maximale Größe um 20% als Sicherheitspuffer
            target_size = int(max_size * 0.9)  # Erhöht von 0.9 auf 0.8 für mehr Sicherheit
            
            # Schätze die Bytes pro Millisekunde basierend auf der Gesamtgröße
            total_size = self._check_segment_size(segment)
            bytes_per_ms = total_size / duration
            
            # Berechne die optimale Segmentdauer (maximal 10 Minuten)
            target_duration = min(
                int((target_size / bytes_per_ms)),
                10 * 60 * 1000  # 10 Minuten in ms
            )
            
            self.logger.info("Teile großes Segment auf",
                           total_duration=duration/1000,
                           total_size_mb=total_size/(1024*1024),
                           target_duration=target_duration/1000,
                           bytes_per_second=bytes_per_ms*1000)
            
            # Teile das Segment in Stücke auf
            current_position = 0
            part_number = 1
            
            while current_position < duration:
                end_position: int = min(current_position + target_duration, duration)
                part: AudioSegmentProtocol = segment[current_position:end_position]
                
                # Prüfe die tatsächliche Größe
                actual_size = self._check_segment_size(part)
                
                # Wenn das Teil immer noch zu groß ist, halbiere die Dauer und versuche erneut
                retry_count = 0
                while actual_size > max_size and retry_count < 5:
                    target_duration = target_duration // 2
                    end_position = min(current_position + target_duration, duration)
                    part = segment[current_position:end_position]
                    actual_size: int = self._check_segment_size(part)
                    retry_count += 1
                    
                    self.logger.warning(f"Segment Teil {part_number} zu groß, verkleinere",
                                    original_size_mb=actual_size/(1024*1024),
                                    new_duration=target_duration/1000,
                                    retry=retry_count)
                
                if actual_size > max_size:
                    self.logger.error(f"Segment Teil {part_number} konnte nicht ausreichend verkleinert werden",
                                    final_size_mb=actual_size/(1024*1024),
                                    max_size_mb=max_size/(1024*1024))
                    raise ValueError(f"Segment konnte nicht unter {max_size/(1024*1024)}MB verkleinert werden")
                
                segments.append(part)
                current_position = end_position
                
                self.logger.info(f"Segment Teil {part_number} erstellt",
                               duration_sec=len(part)/1000.0,
                               size_mb=actual_size/(1024*1024),
                               start_sec=current_position/1000,
                               end_sec=end_position/1000)
                
                part_number += 1
            
            return segments
            
        except Exception as e:
            self.logger.error("Fehler beim Aufteilen des Segments", error=e)
            raise
        finally:
            # Speicher freigeben
            gc.collect()

    def _create_standard_segments(
        self,
        audio: AudioSegmentType,
        process_dir: Path,
        skip_segments: Optional[List[int]] = None
    ) -> List[AudioSegmentInfo]:
        """Erstellt Standard-Segmente basierend auf der konfigurierten Segmentlänge.
        
        Args:
            audio: Das zu segmentierende Audio
            process_dir: Verzeichnis für die Segmente
            skip_segments: Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            List[AudioSegmentInfo]: Liste der Audio-Segmente mit Metadaten
        """
        duration = len(audio)
        segments: List[AudioSegmentInfo] = []
        skip_list = skip_segments if skip_segments is not None else []

        # Wenn Audio kürzer als Segmentdauer, erstelle nur ein Segment
        if duration <= self.segment_duration * 1000:
            segment_path = process_dir / f"full.{self.export_format}"
            audio.export(str(segment_path), format=self.export_format)  # type: ignore
            segments.append(AudioSegmentInfo(
                    file_path=segment_path,
                    title=None
                ))
            return segments

        # Teile in gleichmäßige Segmente auf
        segment_count = (duration // (self.segment_duration * 1000)) + 1
        for i in range(segment_count):
            if i in skip_list:
                self.logger.info(f"Überspringe bereits verarbeitetes Segment {i}")
                continue
                
            start = i * self.segment_duration * 1000
            end = min((i + 1) * self.segment_duration * 1000, duration)
            
            segment = audio[start:end]  # type: ignore
            segment_path = process_dir / f"segment_{i+1}.{self.export_format}"
            
            segment.export(str(segment_path), format=self.export_format)  # type: ignore
            segments.append(AudioSegmentInfo(
                file_path=segment_path,
                title=None
            ))
            
            self.logger.debug(f"Segment {i+1}/{segment_count} erstellt",
                            duration=len(segment)/1000.0,
                            segment_path=str(segment_path))
                
        return segments

    def _split_by_duration(self, audio: AudioSegmentType, max_duration_minutes: int) -> List[AudioSegmentInfo]:
        """Teilt ein AudioSegment in Segmente basierend auf einer maximalen Dauer.
        
        Args:
            audio: Das zu teilende AudioSegment
            max_duration_minutes: Maximale Dauer eines Segments in Minuten
            
        Returns:
            List[AudioSegmentInfo]: Liste der erstellten Segmente
        """
        segments: List[AudioSegmentInfo] = []
        duration_ms = len(audio)
        max_duration_ms = max_duration_minutes * 60 * 1000
        
        if duration_ms <= max_duration_ms:
            # Wenn die Datei klein genug ist, kein Splitting notwendig
            segment_path = self.temp_dir / f"segment_0{self.temp_file_suffix}"
            audio.export(str(segment_path), format=self.export_format)
            segments.append(AudioSegmentInfo(file_path=segment_path))
            return segments
            
        num_segments = math.ceil(duration_ms / max_duration_ms)
        self.logger.info(f"Teile Audio in {num_segments} Segmente")
        
        for i in range(num_segments):
            start_ms = i * max_duration_ms
            end_ms = min((i + 1) * max_duration_ms, duration_ms)
            
            segment = audio[start_ms:end_ms]
            segment_path = self.temp_dir / f"segment_{i}{self.temp_file_suffix}"
            segment.export(str(segment_path), format=self.export_format)
            
            segments.append(AudioSegmentInfo(
                file_path=segment_path,
                title=f"Segment {i+1}"
            ))
            
        return segments

    def _create_chapter_segments(self, audio: AudioSegmentType, chapters: List[Dict[str, Any]], max_duration_minutes: int) -> List[ChapterInfo]:
        """Erstellt Audio-Segmente basierend auf Kapitelinformationen.
        
        Args:
            audio: Das zu teilende AudioSegment
            chapters: Liste der Kapitelinformationen
            max_duration_minutes: Maximale Dauer eines Segments in Minuten
            
        Returns:
            List[ChapterInfo]: Liste der erstellten Kapitel mit ihren Segmenten
        """
        chapter_segments: List[ChapterInfo] = []
        
        for chapter in chapters:
            start_ms = chapter.get('start_ms', 0)
            end_ms = chapter.get('end_ms', len(audio))
            title = chapter.get('title', 'Unbenanntes Kapitel')
            
            chapter_audio = audio[start_ms:end_ms]
            segments = self._split_by_duration(chapter_audio, max_duration_minutes)
            
            chapter_segments.append(ChapterInfo(
                title=title,
                segments=segments
            ))
            
        return chapter_segments

    def get_audio_segments(
        self,
        audio: AudioSegmentType,
        process_dir: Path,
        chapters: Optional[List[Dict[str, Any]]] = None,
        skip_segments: Optional[List[int]] = None
    ) -> Union[List[AudioSegmentInfo], List[ChapterInfo]]:
        """Teilt Audio in Segmente auf.
        
        Args:
            audio: Das zu segmentierende Audio
            process_dir: Verzeichnis für die Segmente
            chapters: Liste der Kapitel mit Start- und Endzeiten
            skip_segments: Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            Union[List[AudioSegmentInfo], List[ChapterInfo]]: Liste der Segmente oder Kapitel
        """
        try:
            # Wähle die passende Segmentierungsmethode
            if chapters:
                segments_or_chapters = self._create_chapter_segments(audio, chapters, 5)
            else:
                segments_or_chapters = self._create_standard_segments(audio, process_dir, skip_segments)

            # Speichere segment_infos im process_dir
            try:
                segment_info_path = process_dir / "segment_infos.json"
                segment_info_data: List[Dict[str, Any]] = []
                
                if isinstance(segments_or_chapters[0], ChapterInfo):
                    # Für Kapitel-basierte Segmentierung
                    chapter_segments = cast(List[ChapterInfo], segments_or_chapters)
                    segment_info_data = [
                        {
                            "title": chapter.title,
                            "segments": [
                                {
                                    "file_path": str(segment.file_path.relative_to(process_dir)),
                                    "title": None  # Titel ist jetzt im Chapter
                                }
                                for segment in chapter.segments
                            ]
                        }
                        for chapter in chapter_segments
                    ]
                else:
                    # Für Standard-Segmentierung
                    standard_segments = cast(List[AudioSegmentInfo], segments_or_chapters)
                    segment_info_data = [
                        {
                            "file_path": str(segment.file_path.relative_to(process_dir)),
                            "title": segment.title
                        }
                        for segment in standard_segments
                    ]
                
                with open(segment_info_path, 'w', encoding='utf-8') as f:
                    json.dump(segment_info_data, f, indent=2, ensure_ascii=False)
                
                self.logger.info("Segment-Informationen gespeichert",
                               segment_count=len(segments_or_chapters),
                               file=str(segment_info_path))
            except Exception as e:
                self.logger.warning("Konnte Segment-Informationen nicht speichern", error=e)
            
            return segments_or_chapters

        except Exception as e:
            self.logger.error("Fehler bei der Segmentierung", error=e)
            raise

    def _read_existing_transcript(self, process_dir: Path) -> Optional[TranscriptionResult]:
        """Liest eine existierende Transkriptionsdatei im JSON-Format.
        
        Args:
            process_dir (Path): Verzeichnis mit der Transkriptionsdatei
            
        Returns:
            Optional[TranscriptionResult]: Das validierte TranscriptionResult oder None wenn keine Datei existiert
        """
        transcript_file = process_dir / "segments_transcript.txt"
        if not transcript_file.exists():
            self.logger.info("Keine existierende Transkription gefunden ", process_dir=str(process_dir))
            return None
            
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.logger.info("Existierende Transkription gefunden", transcript_file=str(transcript_file))
                
                # Erstelle ein LLModel für die Whisper-Nutzung
                whisper_model = LLModel(
                    model="whisper-1",
                    duration=data.get('duration', 0.0),
                    tokens=data.get('token_count', 0)
                )
                
                # Erstelle TranscriptionSegments aus den Segmentdaten
                segments: List[TranscriptionSegment] = []
                for i, segment_data in enumerate(data.get('segments', [])):
                    segment = TranscriptionSegment(
                        text=segment_data.get('text', ''),
                        segment_id=i,  # Füge segment_id hinzu
                        title=segment_data.get('title')  # Füge auch title hinzu für Vollständigkeit
                    )
                    segments.append(segment)
                
                return TranscriptionResult(
                    text=data.get('text', ''),
                    detected_language=data.get('detected_language'),
                    segments=segments,
                    llms=[whisper_model]
                )
                
        except Exception as e:
            self.logger.warning(f"Fehler beim Lesen der existierenden Transkription: {str(e)}")
        return None

    async def process(
        self,
        audio_source: Union[str, Path, bytes],
        source_info: Optional[Dict[str, Any]] = None,
        chapters: Optional[List[Dict[str, Any]]] = None,
        target_language: Optional[str] = None,
        template: Optional[str] = None,
        skip_segments: Optional[List[int]] = None
    ) -> AudioResponse:
        """
        Verarbeitet eine Audio-Datei.
        
        Args:
            audio_source: Kann sein:
                - bytes: Binäre Audio-Daten
                - str: URL oder lokaler Dateipfad
                - Path: Lokaler Dateipfad
            source_info: Zusätzliche Informationen über die Quelle
            chapters: Liste der Kapitel mit Start- und Endzeiten
            target_language: Zielsprache (ISO 639-1 code)
            template: Name der zu verwendenden Vorlage
            skip_segments: Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            AudioResponse: Typisiertes Ergebnis der Audio-Verarbeitung
            
        Raises:
            ProcessingError: Bei Fehlern in der Verarbeitung
        """
        temp_file_path = None
        audio = None
        source_info = source_info or {}
        chapters = chapters or []
        skip_segments = skip_segments or []
        
        try:
            self.logger.info("2. Starte Audio-Verarbeitung")

            with self.measure_operation('audio_processing'):
                if isinstance(audio_source, bytes):
                    temp_file_path = self._load_audio_from_bytes(audio_source)
                else:
                    audio_path = str(audio_source)
                    if audio_path.startswith(('http://', 'https://')):
                        temp_file_path = self._load_audio_from_url(audio_path)
                    else:
                        temp_file_path = Path(audio_path)

                process_dir = self.get_process_dir(
                    str(temp_file_path),
                    source_info.get('original_filename'),
                    source_info.get('video_id')
                )
                
                # Prüfe auf existierende Transkription
                transcription_result = self._read_existing_transcript(process_dir)
                
                if transcription_result:
                    self.logger.info("Existierende Transkription gefunden")
                else:
                    audio = self.process_audio_file(str(temp_file_path))
                    
                    if not audio:
                        raise ProcessingError("Audio konnte nicht verarbeitet werden")

                    segment_infos = self.get_audio_segments(audio, process_dir, chapters, skip_segments)

                    # Transkription durchführen
                    self.logger.info(f"Verarbeite {len(segment_infos)} Segmente")
                    transcription_result = self.transcriber.transcribe_segments(
                        segment_infos, 
                        self.logger, 
                        target_language=target_language
                    )

                # Übersetze den kompletten Text wenn nötig
                detected_language: str | None = transcription_result.detected_language
                original_text: str = transcription_result.text
                duration = source_info.get('duration', 0)

                # Metadaten extrahieren
                metadata_processor = MetadataProcessor(self.resource_calculator, self.process_id)
                metadata_result: MetadataResponse = await metadata_processor.extract_metadata(
                    binary_data=temp_file_path,
                    content=original_text,
                    context=source_info
                )

                if template:
                    self.logger.info(f"3. Text transformation mit Vorlage wird ausgeführt {template}")
                    transformation_result: TransformationResult = self.transformer.transformByTemplate(
                        source_text=transcription_result.text,
                        source_language=target_language or detected_language or 'de',
                        target_language=target_language or detected_language or 'de',
                        context=source_info,
                        template=template
                    )
                    # Token Count aus der Transformation hinzufügen
                    transcription_result = TranscriptionResult(
                        text=transformation_result.text,
                        detected_language=transcription_result.detected_language,
                        segments=transcription_result.segments,
                        llms=list(transcription_result.llms) + list(transformation_result.llms)  # Explizite Listen-Konvertierung
                    )

                elif detected_language and target_language and detected_language != target_language:
                    self.logger.info(f"4. Übersetze/Text-Zusammenfassung wird ausgeführt ({detected_language} -> {target_language})")
                    transformation_result = self.transformer.transform(
                        source_text=transcription_result.text,
                        source_language=detected_language,
                        target_language=target_language,
                        context=source_info
                    )
                    
                    # Token Count aus der Transformation hinzufügen
                    transcription_result = TranscriptionResult(
                        text=transformation_result.text,
                        detected_language=transcription_result.detected_language,
                        segments=transcription_result.segments,
                        llms=list(transcription_result.llms) + list(transformation_result.llms)  # Explizite Listen-Konvertierung
                    )

                # Erstelle das finale Ergebnis
                metadata = AudioMetadata(
                    duration=duration,
                    process_dir=str(process_dir),
                    args={
                        "target_language": target_language,
                        "template": template,
                        "original_text": original_text,  # Speichere Original-Text für spätere Verwendung
                        "metadata": metadata_result.to_dict()  # Füge extrahierte Metadaten hinzu
                    }
                )
                
                result = AudioProcessingResult(
                    transcription=transcription_result,
                    metadata=metadata,
                    process_id=self.process_id  # Füge process_id hinzu
                )

                # Speichere das Ergebnis
                self._save_result(result, process_dir)
                
                request_data = {
                    'source_url': str(temp_file_path) if temp_file_path else None,
                    'original_filename': source_info.get('original_filename'),
                    'video_id': source_info.get('video_id'),
                    'duration': duration,
                    'target_language': target_language,
                    'template': template
                }
                
                response = self._create_response(result, request_data)
                return response

        except Exception as e:
            self._handle_error(e, "audio_processing")
            raise
            
    def _save_result(self, result: AudioProcessingResult, process_dir: Path) -> None:
        """
        Speichert das Verarbeitungsergebnis.
        
        Args:
            result (AudioProcessingResult): Das zu speichernde Ergebnis
            process_dir (Path): Verzeichnis für die Speicherung
        """
        try:
            # Speichere die komplette Transkription
            transcript_file = process_dir / "complete_transcript.txt"
            with open(transcript_file, 'w', encoding='utf-8') as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
                
            self.logger.info("Ergebnis gespeichert", file=str(transcript_file))
            
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern des Ergebnisses: {str(e)}")
            raise ProcessingError(f"Speichern des Ergebnisses fehlgeschlagen: {str(e)}")

    def _handle_error(self, error: Exception, stage: str) -> None:
        """Standardisierte Fehlerbehandlung."""
        error_code = 'AUDIO_PROCESSING_ERROR'
        if isinstance(error, AudioProcessingError):
            error_code = error.error_code
            
        # Spezifische Error-Codes basierend auf der Stage
        stage_error_mapping = {
            'file_processing': 'FILE_ERROR',
            'transcription': 'TRANSCRIPTION_ERROR',
            'transformation': 'TRANSFORMATION_ERROR',
            'segmentation': 'SEGMENT_ERROR',
            'cache_management': 'CACHE_ERROR'
        }
        
        if stage in stage_error_mapping:
            error_code = stage_error_mapping[stage]
            
        error_info = ErrorInfo(
            code=error_code,
            message=str(error),
            details={
                'error_type': type(error).__name__,
                'stage': stage,
                'traceback': traceback.format_exc(),
                'process_id': self.process_id
            }
        )
        
        if self.logger:
            self.logger.error(
                "Fehler bei der Audio-Verarbeitung",
                error=error,
                error_code=error_code,
                stage=stage,
                process_id=self.process_id
            )
        
        raise AudioProcessingError(
            message=str(error),
            error_code=error_code,
            details=error_info.details
        )

    def _track_llm_usage(
        self,
        model: str,
        tokens: int,
        duration: float,
        purpose: str = "audio_processing"
    ) -> None:
        """Standardisiertes LLM-Tracking."""
        try:
            if not model:
                raise ValueError("model darf nicht leer sein")
            if tokens <= 0:
                raise ValueError("tokens muss positiv sein")
            if duration < 0:
                raise ValueError("duration muss nicht-negativ sein")
                
            if hasattr(self.resource_calculator, 'track_usage'):
                self.resource_calculator.track_usage(
                    tokens=tokens,
                    model=model,
                    duration=duration
                )
            
            if self.logger:
                self.logger.info(
                    "LLM-Nutzung getrackt",
                    model=model,
                    tokens=tokens,
                    duration=duration,
                    purpose=purpose,
                    process_id=self.process_id
                )
        except Exception as e:
            if self.logger:
                self.logger.warning(
                    "LLM-Tracking fehlgeschlagen",
                    error=e,
                    model=model,
                    tokens=tokens,
                    duration=duration,
                    process_id=self.process_id
                )

    def _create_response(
        self,
        result: AudioProcessingResult,
        request_info: Dict[str, Any]
    ) -> AudioResponse:
        """Erstellt eine standardisierte Response.
        
        Args:
            result: Verarbeitungsergebnis
            request_info: Request-Informationen
            
        Returns:
            AudioResponse: Standardisierte Response
            
        Raises:
            AudioProcessingError: Bei Validierungsfehlern
        """
        try:
            # Erstelle Response
            response = AudioResponse(
                data=result,
                request=RequestInfo(
                    processor="audio",
                    timestamp=datetime.now().isoformat(),
                    parameters=request_info
                ),
                process=self.process_info,
                status=ProcessingStatus.SUCCESS
            )
            
            self.logger.info(
                "Response erstellt",
                process_id=self.process_id,
                status=response.status.value
            )
            
            return response
            
        except Exception as e:
            self.logger.error(
                "Fehler bei Response-Erstellung",
                error=e,
                process_id=self.process_id
            )
            raise AudioProcessingError(
                message=f"Response-Erstellung fehlgeschlagen: {str(e)}",
                error_code='VALIDATION_ERROR'
            ) 