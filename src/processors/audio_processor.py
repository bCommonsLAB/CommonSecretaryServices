"""Audio Processor für die Verarbeitung von Audio-Dateien.

LLM-Tracking Logik:
-----------------
Der AudioProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest) aus verschiedenen Operationen:
   a) Transkription (Whisper API):
      - Model: whisper-1
      - Purpose: transcription
      - Pro Audio-Segment ein Request

   b) Template-Transformation (wenn Template verwendet):
      - Model: gpt-4
      - Purpose: template_transform
      - Requests vom TransformerProcessor

   c) Übersetzung (wenn Zielsprache != Quellsprache):
      - Model: gpt-4
      - Purpose: translation
      - Requests vom TransformerProcessor

Ablauf:
1. LLMInfo wird für den Gesamtprozess initialisiert
2. Transkription erzeugt Whisper-Requests
3. Optional: Template/Übersetzung erzeugt GPT-Requests
4. Alle Requests werden im LLMInfo aggregiert
5. Die Response enthält beide Informationsebenen

Beispiel Response:
{
  "llm_info": {
    "requests_count": 4,
    "total_tokens": 2000,
    "total_duration": 3000,
    "total_cost": 0.20,
    "requests": [
      {
        "model": "whisper-1",
        "purpose": "transcription",
        "tokens": 500,
        "duration": 800,
        "timestamp": "2024-01-20T10:15:30Z"
      },
      {
        "model": "whisper-1", 
        "purpose": "transcription",
        "tokens": 600,
        "duration": 900,
        "timestamp": "2024-01-20T10:15:31Z"
      },
      {
        "model": "gpt-4",
        "purpose": "template_transform",
        "tokens": 400,
        "duration": 600,
        "timestamp": "2024-01-20T10:15:32Z"
      },
      {
        "model": "gpt-4",
        "purpose": "translation",
        "tokens": 500,
        "duration": 700,
        "timestamp": "2024-01-20T10:15:33Z"
      }
    ]
  }
}
"""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Protocol, cast, TypeVar, Mapping
from types import TracebackType
import time
import hashlib
import json
import traceback
import uuid
import requests
from datetime import datetime
import math

from src.core.models.transformer import LLMInfo, TransformerResponse
from src.processors.base_processor import BaseProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.core.config import Config, ApplicationConfig
from src.processors.transformer_processor import TransformerProcessor
from src.core.models.base import (
    ProcessInfo,
    ErrorInfo,
    ProcessingLogger
)
from src.core.models.audio import (
    AudioProcessingError, AudioProcessingResult, AudioResponse,
    AudioMetadata, AudioSegmentInfo, Chapter, TranscriptionResult,
    TranscriptionSegment
)
from src.core.models.llm import LLModel, LLMRequest
from src.core.models.response_factory import ResponseFactory

try:
    from pydub import AudioSegment  # type: ignore
except ImportError:
    AudioSegment = None

# Typ-Variable für AudioSegment
T = TypeVar('T', bound='AudioSegmentProtocol')

# Protokoll für Audio-Segmente
class AudioSegmentProtocol(Protocol):
    """Protocol für AudioSegment."""
    frame_rate: int
    sample_width: int
    channels: int
    duration_seconds: float
    format: str
    def __len__(self) -> int: ...
    def export(self, out_f: Any, format: Optional[str] = None, codec: Optional[str] = None, parameters: Optional[List[str]] = None) -> Any: ...
    def __getitem__(self, ms: Union[int, slice]) -> 'AudioSegmentProtocol': ...
    @staticmethod
    def from_file(
        file: str,
        format: Optional[str] = None,
        codec: Optional[str] = None,
        parameters: Optional[List[str]] = None,
        start_second: Optional[float] = None,
        duration: Optional[float] = None,
        **kwargs: Any
    ) -> 'AudioSegmentProtocol': ...
    @property
    def duration_milliseconds(self) -> int:
        """Gibt die Dauer in Millisekunden zurück."""
        return int(self.duration_seconds * 1000)

# Typ-Alias für AudioSegment
AudioSegmentType = type[AudioSegmentProtocol]

class WhisperTranscriberProtocol(Protocol):
    """Protocol für WhisperTranscriber."""
    async def transcribe_segments(
        self,
        *,
        segments: Union[List[AudioSegmentInfo], List[Chapter]],
        source_language: str,
        target_language: str,
        logger: Optional[ProcessingLogger] = None
    ) -> TranscriptionResult: ...

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
    ) -> TransformerResponse: ...
    
    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None
    ) -> TransformerResponse: ...

# Typ-Aliase für Konfigurationswerte
AudioConfig = Dict[str, Any]
ProcessorConfig = Mapping[str, Any]

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
        self.config: ApplicationConfig = config.get_all()
        
        # Audio-Konfiguration aus Config extrahieren
        processor_config: ProcessorConfig = self.config.get('processors', {})
        audio_config: AudioConfig = processor_config.get('audio', {})
        
        # Konfigurationswerte mit Typ-Annotationen
        self.max_file_size: int = audio_config.get('max_file_size', 100 * 1024 * 1024)  # 100MB
        self.segment_duration: int = audio_config.get('segment_duration', 300)  # 5 Minuten
        self.export_format: str = audio_config.get('export_format', 'mp3')
        self.temp_file_suffix: str = f".{self.export_format}"
        
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

    def _download_audio(self, url: str) -> Path:
        """Lädt eine Audio-Datei von einer URL herunter.
        
        Args:
            url: Die URL der Audio-Datei
            
        Returns:
            Path: Pfad zur heruntergeladenen Datei
        """
        try:
            # Erstelle temporäre Datei
            temp_file = self.temp_dir / f"download_{uuid.uuid4()}{self.temp_file_suffix}"
            
            # Lade Datei herunter
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                    
            return temp_file
            
        except Exception as e:
            self.logger.error("Fehler beim Herunterladen der Audio-Datei", error=e)
            raise AudioProcessingError(
                f"Fehler beim Herunterladen der Audio-Datei: {str(e)}",
                error_code='FILE_ERROR'
            )

    def _process_audio_file(self, file_path: str) -> Optional[AudioSegmentProtocol]:
        """Verarbeitet eine Audio-Datei.
        
        Args:
            file_path: Pfad zur Audio-Datei
            
        Returns:
            Optional[AudioSegmentProtocol]: Das verarbeitete Audio oder None bei Fehler
        """
        try:
            # Prüfe ob die Datei existiert
            if not os.path.exists(file_path):
                raise AudioProcessingError(
                    f"Audio-Datei nicht gefunden: {file_path}",
                    error_code='FILE_ERROR'
                )
            
            # Prüfe die Dateigröße
            file_size: int = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                raise AudioProcessingError(
                    f"Audio-Datei zu groß: {file_size} Bytes (max: {self.max_file_size} Bytes)",
                    error_code='VALIDATION_ERROR'
                )
            
            # Lade die Audio-Datei
            if not AudioSegment:
                raise AudioProcessingError("AudioSegment nicht verfügbar")
                
            raw_audio = AudioSegment.from_file(file_path)  # type: ignore
            audio: AudioSegmentProtocol = cast(AudioSegmentProtocol, raw_audio)
            
            if not audio:
                raise AudioProcessingError(
                    "Audio konnte nicht geladen werden",
                    error_code='FILE_ERROR'
                )
            
            return audio
            
        except Exception as e:
            if not isinstance(e, AudioProcessingError):
                self.logger.error("Fehler beim Verarbeiten der Audio-Datei", error=e)
                raise AudioProcessingError(
                    f"Fehler beim Verarbeiten der Audio-Datei: {str(e)}",
                    error_code='FILE_ERROR'
                )
            raise

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

    def get_audio_segments(
        self,
        audio: AudioSegmentProtocol,
        process_dir: Path,
        chapters: Optional[List[Dict[str, Any]]] = None,
        skip_segments: Optional[List[int]] = None
    ) -> Union[List[AudioSegmentInfo], List[Chapter]]:
        """Teilt Audio in Segmente auf.
        
        Args:
            audio: Das zu segmentierende Audio
            process_dir: Verzeichnis für die Segmente
            chapters: Liste der Kapitel mit Start- und Endzeiten
            skip_segments: Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            Union[List[AudioSegmentInfo], List[Chapter]]: Liste der Segmente oder Kapitel
        """
        try:
            # Erstelle Verzeichnis wenn nötig
            process_dir.mkdir(parents=True, exist_ok=True)
            
            # Wenn keine Kapitel vorhanden sind, erstelle ein Kapitel über die gesamte Länge
            if not chapters:
                duration_ms: int = len(audio)    
                chapters = [{
                    'title': '',
                    'start_ms': 0,
                    'end_ms': duration_ms
                }]
            
            # Erstelle Kapitel-Segmente (5 Minuten max pro Segment)
            chapter_segments: List[Chapter] = []
            max_duration_minutes = 5
            
            for i, chapter in enumerate(chapters):
                if i in (skip_segments or []):
                    self.logger.info(f"Überspringe bereits verarbeitetes Kapitel {i}")
                    continue

                start_ms = chapter.get('start_ms', 0)
                end_ms = chapter.get('end_ms', len(audio))
                title = chapter.get('title', 'Unbenanntes Kapitel')
                
                # Erstelle ein Verzeichnis für das Kapitel
                chapter_dir: Path = process_dir / f"chapter_{i}"
                chapter_dir.mkdir(parents=True, exist_ok=True)
                
                # Extrahiere das Kapitel-Audio
                chapter_audio: AudioSegmentProtocol = audio[start_ms:end_ms]
                chapter_duration_minutes: float = len(chapter_audio) / (60 * 1000)
                
                # Teile Kapitel wenn es länger als max_duration_minutes ist
                if chapter_duration_minutes > max_duration_minutes:
                    self.logger.info(f"Kapitel {i+1} zu lang, teile es auf",
                                   duration_minutes=chapter_duration_minutes,
                                   max_duration_minutes=max_duration_minutes)
                    
                    # Berechne die Anzahl der benötigten Segmente
                    num_segments = math.ceil(chapter_duration_minutes / max_duration_minutes)
                    segment_duration_ms = len(chapter_audio) // num_segments
                    
                    # Erstelle die Segmente
                    segments: List[AudioSegmentInfo] = []
                    for j in range(num_segments):
                        start = j * segment_duration_ms
                        end = min((j + 1) * segment_duration_ms, len(chapter_audio))
                        
                        segment: AudioSegmentProtocol = chapter_audio[start:end]
                        segment_path: Path = chapter_dir / f"segment_{j}.{self.export_format}"
                        
                        # Exportiere mit optimalen Whisper-Parametern
                        segment.export(
                            str(segment_path),
                            format=self.export_format,
                            parameters=["-ac", "1", "-ar", "16000"]  # Mono, 16kHz
                        )
                        
                        segments.append(AudioSegmentInfo(
                            file_path=segment_path,
                            start=start/1000.0,  # Konvertiere zu Sekunden
                            end=end/1000.0,      # Konvertiere zu Sekunden
                            duration=(end-start)/1000.0  # Konvertiere zu Sekunden
                        ))
                        
                        self.logger.debug(f"Kapitel {i+1} Teil {j+1}/{num_segments} erstellt",
                                        duration_sec=len(segment)/1000.0,
                                        segment_path=str(segment_path))
                else:
                    # Wenn Kapitel kurz genug ist, behalte es als ein Segment
                    segment_path = chapter_dir / f"full.{self.export_format}"
                    chapter_audio.export(
                        str(segment_path),
                        format=self.export_format,
                        parameters=["-ac", "1", "-ar", "16000"]  # Mono, 16kHz
                    )
                    
                    segments = [AudioSegmentInfo(
                        file_path=segment_path,
                        start=0,
                        end=len(chapter_audio)/1000.0,  # Konvertiere zu Sekunden
                        duration=len(chapter_audio)/1000.0  # Konvertiere zu Sekunden
                    )]
                    
                    self.logger.debug(f"Kapitel {i+1} als einzelnes Segment erstellt",
                                    duration_sec=len(chapter_audio)/1000.0,
                                    segment_path=str(segment_path))
                
                # Erstelle Chapter mit seinen Segmenten
                chapter_segments.append(Chapter(
                    title=title,
                    start=start_ms/1000.0,  # Konvertiere zu Sekunden
                    end=end_ms/1000.0,      # Konvertiere zu Sekunden
                    segments=segments
                ))
            
            return chapter_segments

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
        transcript_file: Path = process_dir / "segments_transcript.txt"
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
                        segment_id=i,
                        start=segment_data.get('start', 0.0),
                        end=segment_data.get('end', 0.0),
                        title=segment_data.get('title')
                    )
                    segments.append(segment)
                
                return TranscriptionResult(
                    text=data.get('text', ''),
                    source_language=data.get('detected_language', 'de'),
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
        source_language: Optional[str] = None,
        target_language: Optional[str] = None,
        template: Optional[str] = None,
        skip_segments: Optional[List[int]] = None
    ) -> AudioResponse:
        """Verarbeitet eine Audio-Datei.
        
        Args:
            audio_source: Die Audio-Quelle (Pfad, URL oder Bytes)
            source_info: Optionale Zusatzinformationen zur Quelle
            chapters: Optionale Kapitelinformationen
            source_language: Quellsprache (ISO 639-1)
            target_language: Zielsprache (ISO 639-1)
            template: Optionales Template für die Transformation
            skip_segments: Optionale Liste von zu überspringenden Segmenten
            
        Returns:
            AudioResponse: Das Verarbeitungsergebnis
        """
        # Initialisiere LLMInfo für den gesamten Prozess
        llm_info = LLMInfo(
            model=self.transformer.model,
            purpose="audio-processing",
            requests=[]  # Explizit leere Liste
        )
        start_time = datetime.now()
        
        try:
            # Initialisiere source_info wenn nicht vorhanden
            source_info = source_info or {}
            source_language = source_language or "de"  # Fallback auf Deutsch
            target_language = target_language or source_language  # Fallback auf Quellsprache
            
            # Erstelle temporäre Datei aus der Quelle
            if isinstance(audio_source, bytes):
                temp_file_path: Path = self._create_temp_file(audio_source)
            elif isinstance(audio_source, str) and audio_source.startswith(('http://', 'https://')):
                temp_file_path = self._download_audio(audio_source)
            else:
                temp_file_path = Path(audio_source)

            # Erstelle Verarbeitungsverzeichnis
            process_dir: Path = self.get_process_dir(
                str(temp_file_path),
                source_info.get('original_filename'),
                source_info.get('video_id')
            )

            try:
                # Verarbeite die Audio-Datei
                audio: AudioSegmentProtocol | None = self._process_audio_file(str(temp_file_path))
                
                if not audio:
                    raise ProcessingError("Audio konnte nicht verarbeitet werden")

                # Erstelle Audio-Segmente
                segment_infos: Union[List[AudioSegmentInfo], List[Chapter]] = self.get_audio_segments(audio, process_dir, chapters, skip_segments)

                # Transkription durchführen
                self.logger.info(f"Verarbeite {len(segment_infos)} Kapitel")
                transcription_result: TranscriptionResult = await self.transcriber.transcribe_segments(
                    segments=segment_infos,
                    source_language=source_language,
                    target_language=target_language,
                    logger=self.logger
                )

                if transcription_result.source_language != source_language:
                    source_language = transcription_result.source_language

                if not transcription_result:
                    raise ProcessingError("Keine Transkription erstellt")

                # Füge Whisper-Requests hinzu
                if transcription_result.requests:
                    self.logger.info(f"Füge {len(transcription_result.requests)} Whisper-Requests hinzu")
                    llm_info.add_request(transcription_result.requests)
                elif transcription_result.llms:  # Fallback auf llms wenn requests leer
                    self.logger.info(f"Füge {len(transcription_result.llms)} Whisper-LLMs als Requests hinzu")
                    # Konvertiere LLModels zu LLMRequests
                    llm_requests: List[LLMRequest] = [
                        LLMRequest(
                            model=llm.model,
                            purpose="transcription",
                            tokens=llm.tokens,
                            duration=int(llm.duration),  # Konvertiere zu int für Millisekunden
                            timestamp=llm.timestamp
                        )
                        for llm in transcription_result.llms
                    ]
                    llm_info.add_request(llm_requests)

                original_text: str = transcription_result.text

                # Template-Transformation oder Übersetzung durchführen
                if template:
                    # Transformiere den Text mit dem Template
                    self.logger.info(f"Text transformation mit Template {template}")
                    transformer_response: TransformerResponse = self.transformer.transformByTemplate(
                        source_text=original_text,
                        source_language=source_language,
                        target_language=target_language,
                        template=template,
                        context=source_info
                    )
                    
                    # Füge Template-Transformation Requests hinzu
                    if transformer_response.process and transformer_response.process.llm_info:
                        self.logger.info(f"Füge {len(transformer_response.process.llm_info.requests)} Template-Transformation-Requests hinzu")
                        llm_info.add_request(transformer_response.process.llm_info.requests)
                    
                    if transformer_response and transformer_response.data and transformer_response.data.output:
                        transcription_result = TranscriptionResult(
                            text=transformer_response.data.output.text,
                            source_language=transcription_result.source_language,
                            segments=transcription_result.segments,
                            requests=[],  # Leere Liste statt None
                            llms=[]  # Leere Liste statt None
                        )

                # Erstelle das finale Ergebnis
                metadata = AudioMetadata(
                    duration=float(len(audio)) / 1000.0,  # Konvertiere ms zu Sekunden
                    process_dir=str(process_dir),
                    format=getattr(audio, 'format', 'mp3'),
                    channels=getattr(audio, 'channels', 2)
                )
                
                # Erstelle bereinigte Version des Results ohne Requests
                result = AudioProcessingResult(
                    transcription=TranscriptionResult(
                        text=transcription_result.text if transcription_result else "",
                        source_language=transcription_result.source_language if transcription_result else "unknown",
                        segments=transcription_result.segments if transcription_result and transcription_result.segments else [],
                        requests=[],
                        llms=[]
                    ),
                    metadata=metadata,
                    process_id=self.process_id,
                    transformation_result=None  # Kein separates Transformationsergebnis mehr
                )

                # Erstelle die Response mit ResponseFactory
                end_time: datetime = datetime.now()
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}, Duration: {llm_info.total_duration}")
                
                return ResponseFactory.create_response(
                    processor_name="audio",
                    result=result,
                    request_info={
                        'original_filename': source_info.get('original_filename'),
                        'source_language': source_language,
                        'target_language': target_language,
                        'template': template,
                        'started': start_time.isoformat(),
                        'completed': end_time.isoformat(),
                        'duration_ms': duration_ms
                    },
                    response_class=AudioResponse,
                    llm_info=llm_info
                )

            except Exception as e:
                # Log den Fehler und erstelle Error-Response
                self.logger.error(
                    "Fehler bei der Audio-Verarbeitung",
                    error=e,
                    error_type=type(e).__name__,
                    stage="audio_processing",
                    process_id=self.process_id
                )
                
                error_info = ErrorInfo(
                    code=type(e).__name__,
                    message=str(e),
                    details={
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                        "stage": "audio_processing",
                        "process_id": self.process_id
                    }
                )
                
                # Error-Response mit ResponseFactory
                end_time = datetime.now()
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                
                return ResponseFactory.create_response(
                    processor_name="audio",
                    result=AudioProcessingResult(
                        transcription=TranscriptionResult(
                            text="",
                            source_language="unknown",
                            segments=[],
                            requests=[],
                            llms=[]
                        ),
                        metadata=AudioMetadata(
                            duration=0.0,
                            process_dir="",
                            format="unknown",
                            channels=0
                        ),
                        process_id=self.process_id,
                        transformation_result=None
                    ),
                    request_info={
                        'original_filename': source_info.get('original_filename') if source_info else None,
                        'source_language': source_language,
                        'target_language': target_language,
                        'template': template,
                        'started': start_time.isoformat(),
                        'completed': end_time.isoformat(),
                        'duration_ms': duration_ms
                    },
                    response_class=AudioResponse,
                    error=error_info
                )

        except Exception as e:
            # Log den Fehler und erstelle Error-Response
            self.logger.error(
                "Fehler bei der Audio-Verarbeitung",
                error=e,
                error_type=type(e).__name__,
                stage="audio_processing",
                process_id=self.process_id
            )
            
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                    "stage": "audio_processing",
                    "process_id": self.process_id
                }
            )
            
            # Error-Response mit ResponseFactory
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            return ResponseFactory.create_response(
                processor_name="audio",
                result=AudioProcessingResult(
                    transcription=TranscriptionResult(
                        text="",
                        source_language="unknown",
                        segments=[],
                        requests=[],
                        llms=[]
                    ),
                    metadata=AudioMetadata(
                        duration=0.0,
                        process_dir="",
                        format="unknown",
                        channels=0
                    ),
                    process_id=self.process_id,
                    transformation_result=None
                ),
                request_info={
                    'original_filename': source_info.get('original_filename') if source_info else None,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'started': start_time.isoformat(),
                    'completed': end_time.isoformat(),
                    'duration_ms': duration_ms
                },
                response_class=AudioResponse,
                error=error_info
            )

    def _create_temp_file(self, audio_data: bytes) -> Path:
        """Erstellt eine temporäre Datei aus Audio-Bytes.
        
        Args:
            audio_data: Die Audio-Daten als Bytes
            
        Returns:
            Path: Pfad zur temporären Datei
        """
        temp_file = self.temp_dir / f"temp_{uuid.uuid4()}{self.temp_file_suffix}"
        with open(temp_file, 'wb') as f:
            f.write(audio_data)
        return temp_file

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
        error_details = {
            'error_type': type(error).__name__,
            'stage': stage,
            'traceback': traceback.format_exc(),
            'process_id': self.process_id
        }
        
        # Wenn es ein ProcessingError ist, füge die vorhandenen Details hinzu
        if isinstance(error, ProcessingError) and hasattr(error, 'details'):
            error_details.update(error.details)
            
        error_info = ErrorInfo(
            code=error_details.get('error_type', 'AUDIO_PROCESSING_ERROR'),
            message=str(error),
            details=error_details
        )
        
        if self.logger:
            self.logger.error(
                "Fehler bei der Audio-Verarbeitung",
                error=error,
                error_code=error_details.get('error_type', 'AUDIO_PROCESSING_ERROR'),
                stage=stage,
                process_id=self.process_id
            )
        
        raise ProcessingError(
            message=str(error),
            details=error_info.details
        ) 