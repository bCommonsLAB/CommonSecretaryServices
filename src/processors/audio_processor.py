"""Audio Processor für die Verarbeitung von Audio-Dateien."""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Protocol, cast, TYPE_CHECKING
from types import TracebackType
import time
import hashlib
import json
import traceback
import uuid
import requests
from datetime import datetime
import io
import math

from core.models.transformer import TransformationResult
from src.processors.base_processor import BaseProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.types.pydub_types import AudioSegmentProtocol
from src.core.config import Config, ApplicationConfig
from src.processors.transformer_processor import TransformerProcessor
from src.core.models.base import (
    ProcessingStatus,
    RequestInfo,
    ProcessInfo,
    ErrorInfo,
    ProcessingLogger
)
from src.core.models.metadata import MetadataResponse
from src.core.models.audio import (
    AudioProcessingError, AudioProcessingResult, AudioResponse,
    AudioMetadata, AudioSegmentInfo, Chapter, TranscriptionResult,
    TranscriptionSegment
)
from src.core.models.llm import LLModel

if TYPE_CHECKING:
    from .transformer_processor import TransformationResult

try:
    from pydub import AudioSegment  # type: ignore
except ImportError:
    AudioSegment = None

# Typ-Alias für AudioSegment
AudioSegmentType = AudioSegmentProtocol

class AudioSegmentProtocol(Protocol):
    """Protocol für AudioSegment."""
    frame_rate: int
    sample_width: int
    channels: int
    duration_seconds: float
    format: str
    def __len__(self) -> int: ...
    def export(self, out_f: Any, format: Optional[str] = None, codec: Optional[str] = None, parameters: Optional[List[str]] = None) -> Any: ...

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
    ) -> 'TransformationResult': ...
    
    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None
    ) -> 'TransformationResult': ...

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
        self.config: ApplicationConfig = config.get_all()  # Korrekte Typ-Annotation
        # temp_dir wird vom BaseProcessor verwaltet
        self.max_file_size = self.config.get('processors', {}).get('audio', {}).get('max_file_size', 100 * 1024 * 1024)  # 100MB
        self.segment_duration = self.config.get('processors', {}).get('audio', {}).get('segment_duration', 300)  # 5 Minuten
        self.export_format = self.config.get('processors', {}).get('audio', {}).get('export_format', 'mp3')
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

    def _process_audio_file(self, file_path: str) -> Optional[AudioSegmentType]:
        """Verarbeitet eine Audio-Datei.
        
        Args:
            file_path: Pfad zur Audio-Datei
            
        Returns:
            Optional[AudioSegmentType]: Das verarbeitete Audio oder None bei Fehler
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
            audio: AudioSegmentType = AudioSegment.from_file(file_path)
            
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
        audio: AudioSegmentType,
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
                    'title': 'Vollständige Aufnahme',
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
                chapter_dir = process_dir / f"chapter_{i}"
                chapter_dir.mkdir(parents=True, exist_ok=True)
                
                # Extrahiere das Kapitel-Audio
                chapter_audio = audio[start_ms:end_ms]
                chapter_duration_minutes = len(chapter_audio) / (60 * 1000)
                
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
                        
                        segment = chapter_audio[start:end]
                        segment_path = chapter_dir / f"segment_{j}.{self.export_format}"
                        
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
            audio_source: Die Audio-Quelle (URL, Pfad oder Bytes)
            source_info: Optionale Informationen zur Quelle
            chapters: Optionale Kapitel-Informationen
            source_language: Quellsprache der Audio-Datei (ISO 639-1)
            target_language: Zielsprache für die Transkription (ISO 639-1)
            template: Optionales Template für die Transformation
            skip_segments: Optionale Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            AudioResponse: Das Verarbeitungsergebnis
        """
        try:
            # Initialisiere source_info wenn nicht vorhanden
            source_info = source_info or {}
            source_language = source_language or "de"  # Fallback auf Deutsch
            target_language = target_language or source_language  # Fallback auf Quellsprache
            
            # Erstelle temporäre Datei aus der Quelle
            if isinstance(audio_source, bytes):
                temp_file_path = self._create_temp_file(audio_source)
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

                if not transcription_result:
                    raise ProcessingError("Keine Transkription erstellt")

                original_text: str = transcription_result.text
               
                if template:
                    # Transformiere den Text mit dem Template
                    transformation_result: TransformationResult = self.transformer.transformByTemplate(
                        source_text=original_text,
                        source_language=source_language,
                        target_language=target_language,
                        template=template
                    )
                    
                    if transformation_result and transformation_result.text:
                        original_text = transformation_result.text

                # Erstelle das finale Ergebnis
                metadata: AudioMetadata = AudioMetadata(
                    duration=float(len(audio)) / 1000.0,  # Konvertiere ms zu Sekunden
                    format=getattr(audio, 'format', 'mp3'),
                    channels=getattr(audio, 'channels', 2),  # Default zu Stereo
                    process_dir=str(process_dir),
                )
                
                result: AudioProcessingResult = AudioProcessingResult(
                    transcription=transcription_result,
                    metadata=metadata,
                    process_id=self.process_id  # Füge process_id hinzu
                )

                # Speichere das Ergebnis
                #self._save_result(result, process_dir)
                
                request_data: Dict[str, Any] = {
                    'original_filename': source_info.get('original_filename'),
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template
                }
                
                response: AudioResponse = self._create_response(result, request_data)
                return response

            except Exception as e:
                self._handle_error(e, "audio_processing")
                raise

        except Exception as e:
            self._handle_error(e, "audio_processing")
            raise

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