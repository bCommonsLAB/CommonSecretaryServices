"""Audio Processor für die Verarbeitung von Audio-Dateien."""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Protocol, cast, TYPE_CHECKING, IO
from types import TracebackType
import time
import hashlib
import json
import traceback
import tempfile
import gc
import uuid
import requests
from datetime import datetime
import asyncio

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

class WhisperTranscriberProtocol(Protocol):
    """Protocol für WhisperTranscriber."""
    async def transcribe_segments(
        self,
        *,
        segments: Union[List[AudioSegmentInfo], List[Chapter]],
        target_language: str,
        logger: Optional[ProcessingLogger] = None
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
        self.export_format = config.get('export_format', 'mp3')
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
            
            # Wenn Kapitel vorhanden sind, nutze diese für die Segmentierung
            if chapters:
                return self._create_chapter_segments(audio, chapters, 30)  # 30 Minuten max pro Segment
            
            # Ansonsten erstelle ein einzelnes Segment
            return self._create_single_segment(audio)

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
        """Verarbeitet eine Audio-Datei.
        
        Args:
            audio_source: Die Audio-Quelle (URL, Pfad oder Bytes)
            source_info: Optionale Informationen zur Quelle
            chapters: Optionale Kapitel-Informationen
            target_language: Optionale Zielsprache
            template: Optionales Template für die Transformation
            skip_segments: Optionale Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            AudioResponse: Das Verarbeitungsergebnis
        """
        try:
            # Initialisiere source_info wenn nicht vorhanden
            source_info = source_info or {}
            
            # Erstelle temporäre Datei aus der Quelle
            if isinstance(audio_source, bytes):
                temp_file_path = self._create_temp_file(audio_source)
            elif isinstance(audio_source, str) and audio_source.startswith(('http://', 'https://')):
                temp_file_path = self._download_audio(audio_source)
            else:
                temp_file_path = Path(audio_source)

            # Erstelle Verarbeitungsverzeichnis
            process_dir = self.get_process_dir(
                str(temp_file_path),
                source_info.get('original_filename'),
                source_info.get('video_id')
            )

            try:
                # Verarbeite die Audio-Datei
                audio = self._process_audio_file(str(temp_file_path))
                
                if not audio:
                    raise ProcessingError("Audio konnte nicht verarbeitet werden")

                # Erstelle Audio-Segmente
                segment_infos = self.get_audio_segments(audio, process_dir, chapters, skip_segments)

                # Transkription durchführen
                self.logger.info(f"Verarbeite {len(segment_infos)} Segmente")
                transcription_result: TranscriptionResult = await self.transcriber.transcribe_segments(
                    segments=segment_infos,
                    target_language=target_language or "de",  # Fallback auf Deutsch wenn keine Sprache angegeben
                    logger=self.logger
                )

                if not transcription_result:
                    raise ProcessingError("Keine Transkription erstellt")

                # Übersetze den kompletten Text wenn nötig
                detected_language: str = transcription_result.detected_language
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
                    # Transformiere den Text mit dem Template
                    transformation_result = self.transformer.transformByTemplate(
                        source_text=original_text,
                        source_language=detected_language,
                        target_language=target_language or detected_language,
                        template=template
                    )
                    
                    if transformation_result and transformation_result.transformed_text:
                        original_text = transformation_result.transformed_text

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
                #self._save_result(result, process_dir)
                
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

    def _create_single_segment(self, audio: AudioSegmentType) -> List[AudioSegmentInfo]:
        """Erstellt ein einzelnes Segment aus dem kompletten Audio.
        
        Args:
            audio: Das Audio-Segment das gespeichert werden soll
            
        Returns:
            List[AudioSegmentInfo]: Liste mit einem einzelnen Segment
            
        Raises:
            AudioProcessingError: Wenn die Konvertierung fehlschlägt
        """
        try:
            # Stelle sicher dass der temp_dir existiert
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Erstelle den Segment-Pfad
            segment_path = self.temp_dir / "segment_0.mp3"  # Immer .mp3 Extension verwenden
            
            # Logge Audio-Informationen vor der Konvertierung
            self.logger.info(
                "Audio-Informationen vor Konvertierung",
                frame_rate=audio.frame_rate,
                channels=audio.channels,
                sample_width=audio.sample_width,
                duration_ms=len(audio)
            )
            
            # Exportiere als MP3 mit optimalen Parametern für Whisper
            try:
                self.logger.info(
                    "Starte Audio-Konvertierung",
                    target_path=str(segment_path),
                    format="mp3",
                    parameters={
                        "sample_rate": "16000",
                        "channels": "1",
                        "bitrate": "128k"
                    }
                )
                
                audio.export(
                    str(segment_path),
                    format="mp3",
                    parameters=[
                        "-ar", "16000",  # Sample Rate: 16kHz
                        "-ac", "1",      # Mono Audio
                        "-b:a", "128k"   # Bitrate: 128k
                    ]
                )
                
                # Verifiziere die exportierte Datei
                if not segment_path.exists():
                    raise AudioProcessingError(
                        message="Exportierte Audio-Datei wurde nicht erstellt",
                        error_code="SEGMENT_ERROR"
                    )
                    
                file_size = segment_path.stat().st_size
                self.logger.info(
                    "Audio-Konvertierung abgeschlossen",
                    file_size_bytes=file_size,
                    file_path=str(segment_path)
                )
                
            except Exception as e:
                # Spezifische Fehlerbehandlung für Audio-Konvertierung
                error_msg = str(e)
                if "format not supported" in error_msg.lower():
                    raise AudioProcessingError(
                        message="Das Audio-Format wird nicht unterstützt. Bitte verwenden Sie ein gängiges Format wie MP3, WAV oder FLAC.",
                        error_code="FORMAT_ERROR"
                    )
                elif "codec not supported" in error_msg.lower():
                    raise AudioProcessingError(
                        message="Der Audio-Codec wird nicht unterstützt. Bitte verwenden Sie einen Standard-Codec.",
                        error_code="CODEC_ERROR"
                    )
                else:
                    raise AudioProcessingError(
                        message=f"Audio-Konvertierung fehlgeschlagen: {error_msg}",
                        error_code="SEGMENT_ERROR"
                    )

            # Berechne die Dauer in Sekunden
            duration = len(audio) / 1000.0  # Konvertiere von Millisekunden zu Sekunden
            
            # Erstelle das AudioSegmentInfo
            segment = AudioSegmentInfo(
                file_path=segment_path,
                start=0.0,
                end=duration,
                duration=duration
            )
            
            return [segment]
            
        except Exception as e:
            if not isinstance(e, AudioProcessingError):
                self.logger.error(
                    "Unerwarteter Fehler bei der Segment-Erstellung",
                    error=str(e),
                    error_type=type(e).__name__
                )
                raise AudioProcessingError(
                    message=f"Segment-Erstellung fehlgeschlagen: {str(e)}",
                    error_code="SEGMENT_ERROR"
                )
            raise

    def _create_chapter(self, title: str, start: float, end: float, segments: List[AudioSegmentInfo]) -> Chapter:
        """Erstellt ein Kapitel mit den gegebenen Informationen.
        
        Args:
            title: Titel des Kapitels
            start: Startzeit in Sekunden
            end: Endzeit in Sekunden
            segments: Liste der Audio-Segmente
            
        Returns:
            Chapter: Das erstellte Kapitel
        """
        return Chapter(
            title=title,
            start=start,
            end=end,
            segments=segments
        )

    def _process_existing_segments(
        self,
        segments_or_chapters: Union[List[AudioSegmentInfo], List[Chapter]],
        process_dir: Path,
        skip_segments: Optional[List[int]] = None
    ) -> Union[List[AudioSegmentInfo], List[Chapter]]:
        """Verarbeitet existierende Segmente und kopiert sie ins Prozessverzeichnis.
        
        Args:
            segments_or_chapters: Liste der existierenden Segmente oder Kapitel
            process_dir: Zielverzeichnis für die Segmente
            skip_segments: Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            Union[List[AudioSegmentInfo], List[Chapter]]: Aktualisierte Liste der Segmente oder Kapitel
        """
        try:
            if not segments_or_chapters:
                return []
            
            # Erstelle Cache-Verzeichnis wenn nötig
            process_dir.mkdir(parents=True, exist_ok=True)
            
            # Verarbeite Segmente basierend auf Typ
            if isinstance(segments_or_chapters[0], Chapter):
                # Für Kapitel-basierte Segmentierung
                chapter_segments = cast(List[Chapter], segments_or_chapters)
                processed_chapters: List[Chapter] = []
                
                for chapter in chapter_segments:
                    processed_segments: List[AudioSegmentInfo] = []
                    
                    for i, segment in enumerate(chapter.segments):
                        if skip_segments and i in skip_segments:
                            continue
                        
                        # Kopiere Segment-Datei ins Prozessverzeichnis
                        new_path = process_dir / segment.file_path.name
                        shutil.copy2(str(segment.file_path), str(new_path))
                        
                        # Aktualisiere Segment mit neuem Pfad
                        processed_segments.append(AudioSegmentInfo(
                            file_path=new_path,
                            start=segment.start,
                            end=segment.end,
                            duration=segment.duration
                        ))
                    
                    # Erstelle aktualisiertes Kapitel
                    processed_chapters.append(Chapter(
                        title=chapter.title,
                        start=chapter.start,
                        end=chapter.end,
                        segments=processed_segments
                    ))
                
                return processed_chapters
                
            else:
                # Für einfache Segmentierung
                segments = cast(List[AudioSegmentInfo], segments_or_chapters)
                processed_segments: List[AudioSegmentInfo] = []
                
                for i, segment in enumerate(segments):
                    if skip_segments and i in skip_segments:
                        continue
                    
                    # Kopiere Segment-Datei ins Prozessverzeichnis
                    new_path = process_dir / segment.file_path.name
                    shutil.copy2(str(segment.file_path), str(new_path))
                    
                    # Aktualisiere Segment mit neuem Pfad
                    processed_segments.append(AudioSegmentInfo(
                        file_path=new_path,
                        start=segment.start,
                        end=segment.end,
                        duration=segment.duration
                    ))
                
                return processed_segments
                
        except Exception as e:
            self.logger.error("Fehler beim Verarbeiten existierender Segmente", error=e)
            raise AudioProcessingError(
                f"Fehler beim Verarbeiten existierender Segmente: {str(e)}",
                error_code='SEGMENT_ERROR'
            )

    def _create_chapter_segments(self, audio: AudioSegmentType, chapters: List[Dict[str, Any]], max_duration_minutes: int) -> List[Chapter]:
        """Erstellt Audio-Segmente basierend auf Kapitelinformationen.
        
        Args:
            audio: Das zu teilende AudioSegment
            chapters: Liste der Kapitelinformationen
            max_duration_minutes: Maximale Dauer eines Segments in Minuten
            
        Returns:
            List[Chapter]: Liste der erstellten Kapitel mit ihren Segmenten
        """
        chapter_segments: List[Chapter] = []
        
        for chapter in chapters:
            start_ms = chapter.get('start_ms', 0)
            end_ms = chapter.get('end_ms', len(audio))
            title = chapter.get('title', 'Unbenanntes Kapitel')
            
            # Erstelle ein Verzeichnis für das Kapitel
            chapter_dir = self.temp_dir / f"chapter_{len(chapter_segments)}"
            chapter_dir.mkdir(parents=True, exist_ok=True)
            
            chapter_audio = audio[start_ms:end_ms]
            segments = self._split_by_duration(chapter_audio, max_duration_minutes, base_path=chapter_dir)
            
            chapter_segments.append(Chapter(
                title=title,
                start=start_ms/1000.0,  # Konvertiere zu Sekunden
                end=end_ms/1000.0,      # Konvertiere zu Sekunden
                segments=segments
            ))
            
        return chapter_segments

    def _split_by_duration(
        self,
        audio: AudioSegmentType,
        max_duration_minutes: int,
        base_path: Optional[Path] = None
    ) -> List[AudioSegmentInfo]:
        """Teilt Audio in Segmente basierend auf maximaler Dauer.
        
        Args:
            audio: Das zu teilende AudioSegment
            max_duration_minutes: Maximale Dauer eines Segments in Minuten
            base_path: Optionaler Basis-Pfad für die Segmente
            
        Returns:
            List[AudioSegmentInfo]: Liste der erstellten Segmente
        """
        segments: List[AudioSegmentInfo] = []
        max_duration_ms = max_duration_minutes * 60 * 1000
        
        for i, start_ms in enumerate(range(0, len(audio), max_duration_ms)):
            end_ms = min(start_ms + max_duration_ms, len(audio))
            segment = audio[start_ms:end_ms]
            
            # Erstelle temporäre Datei für das Segment
            segment_path = (base_path or self.temp_dir) / f"segment_{i}.mp3"  # Immer als MP3 speichern
            segment.export(str(segment_path), format='mp3')  # Konvertiere zu MP3
            
            # Erstelle Segment-Info
            segments.append(AudioSegmentInfo(
                file_path=segment_path,
                start=start_ms/1000.0,  # Konvertiere zu Sekunden
                end=end_ms/1000.0,      # Konvertiere zu Sekunden
                duration=(end_ms-start_ms)/1000.0  # Konvertiere zu Sekunden
            ))
        
        return segments 