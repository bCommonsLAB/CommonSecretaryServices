"""Audio Processor für die Verarbeitung von Audio-Dateien.

LLM-Tracking Logik:
-----------------
Der AudioProcessor trackt die LLM-Nutzung über die ProcessInfo:

1. Aggregierte Informationen in ProcessInfo:
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Hierarchisches Tracking über Sub-Prozessoren:
   a) Whisper API (Transkription):
      - Model: whisper-1
      - Purpose: transcription
      - Pro Audio-Segment ein Request

   b) TransformerProcessor (Template/Übersetzung):
      - Eigene ProcessInfo
      - Wird in Haupt-ProcessInfo integriert
"""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Protocol, cast, TypeVar, Mapping
from types import TracebackType
import hashlib
import json
import uuid
import requests
from datetime import datetime
import math
import time

from src.core.models.transformer import TransformerResponse
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.processors.transformer_processor import TransformerProcessor
from src.core.models.audio import (
    AudioProcessingResult, 
    AudioMetadata, 
    TranscriptionResult, 
    AudioResponse, 
    AudioSegmentInfo,
    Chapter
)
from src.core.models.base import ProcessInfo, ErrorInfo
from src.processors.cacheable_processor import CacheableProcessor
from src.core.models.enums import ProcessorType
from src.utils.logger import ProcessingLogger
from src.core.config import Config
from src.processors.base_processor import BaseProcessor

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
    processor: Optional[BaseProcessor[Any]]  # Hinzugefügt für BaseProcessor Integration
    
    async def transcribe_segments(
        self,
        *,
        segments: Union[List[AudioSegmentInfo], List[Chapter]],
        source_language: str,
        target_language: str,
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None
    ) -> TranscriptionResult: ...

class TransformerProcessorProtocol(Protocol):
    """Protocol für TransformerProcessor."""
    model: str
    
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

class AudioProcessor(CacheableProcessor[AudioProcessingResult]):
    """Audio Processor für die Verarbeitung von Audio-Dateien.
    
    Diese Klasse verarbeitet Audio-Dateien, segmentiert sie bei Bedarf und führt Transkription/Übersetzung durch.
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        max_file_size (int): Maximale Dateigröße in Bytes (Default: 100MB)
        segment_duration (int): Dauer der Audio-Segmente in Sekunden
        export_format (str): Format für exportierte Audio-Dateien
        temp_file_suffix (str): Suffix für temporäre Dateien
        temp_dir (Path): Verzeichnis für temporäre Dateien
        cache_dir (Path): Verzeichnis für den Cache
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "audio_cache"
    
    temp_dir: Path  # Explizite Typ-Annotation für temp_dir
    cache_dir: Path  # Explizite Typ-Annotation für cache_dir
    start_time: Optional[datetime] = None  # Startzeit des Verarbeitungsprozesses
    end_time: Optional[datetime] = None  # Endzeit des Verarbeitungsprozesses
    duration: Optional[float] = None
    
    def __init__(self, resource_calculator: ResourceCalculator, 
                 process_id: Optional[str] = None, 
                 parent_process_info: Optional[ProcessInfo] = None):
        """Initialisiert den AudioProcessor."""
        # Zeit für Gesamtinitialisierung starten
        init_start = time.time()
        
        # Superklasse-Initialisierung
        super().__init__(resource_calculator=resource_calculator, 
                        process_id=process_id, 
                        parent_process_info=parent_process_info)
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            audio_config = processor_config.get('audio', {})
            
            # Audio-spezifische Konfiguration
            self.max_file_size = audio_config.get('max_file_size', 125829120)
            self.segment_duration = audio_config.get('segment_duration', 300)
            self.max_segments = audio_config.get('max_segments', 100)
            self.export_format = audio_config.get('export_format', 'mp3')
            self.temp_file_suffix = f".{self.export_format}"
            
            # Sub-Prozessoren mit ProcessInfo initialisieren
            self.transformer_processor = TransformerProcessor(
                resource_calculator, 
                process_id,
                parent_process_info=self.process_info
            )
            
            # Transcriber mit Audio-spezifischen Konfigurationen
            transcriber_config = {
                'processor_name': 'audio',
                'cache_dir': str(self.cache_dir),
                'temp_dir': str(self.temp_dir),
                'debug_dir': str(self.temp_dir / "debug")
            }
            
            self.transcriber = WhisperTranscriber(transcriber_config, processor=self)
            
            # Performance-Logging
            init_end = time.time()
            self.logger.info(f"Gesamte Initialisierungszeit: {(init_end - init_start) * 1000:.2f} ms")
            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des AudioProcessors",
                            error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

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

    def cleanup_cache(self, max_age_days: Optional[int] = None, delete_transcripts: bool = False) -> Dict[str, int]:
        """Löscht alte Cache-Einträge die älter als max_age_days sind.
        
        Args:
            max_age_days: Maximales Alter in Tagen. Wenn None, wird der Standardwert verwendet.
            delete_transcripts: Ob auch die Transkriptdateien gelöscht werden sollen
            
        Returns:
            Dict[str, int]: Statistiken zur Bereinigung (gelöschte Einträge)
        """
        # MongoDB-Cache bereinigen
        delete_stats = super().cleanup_cache(max_age_days)
        
        # Alte Transkripte löschen, wenn gewünscht
        if delete_transcripts:
            # Implementierung für das Löschen der Transkripte...
            pass
        
        return delete_stats

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
        """Lädt eine Audio-Datei von einer URL herunter und gibt den lokalen Pfad zurück.
        
        Args:
            url: URL der Audio-Datei
            
        Returns:
            Path: Lokaler Pfad zur heruntergeladenen Datei
        """
        try:
            # Temporären Dateinamen generieren
            temp_file = self.temp_dir / f"audio_{str(uuid.uuid4())}{self.temp_file_suffix}"
            
            # Audio-Datei herunterladen
            response: requests.Response = requests.get(url, stream=True)
            if response.status_code != 200:
                raise ProcessingError(f"Fehler beim Herunterladen der Audio-Datei (Status {response.status_code})")
            
            content_length = int(response.headers.get('content-length', 0))
            if content_length > self.max_file_size:
                raise ProcessingError(
                    f"Audio-Datei zu groß: {content_length} Bytes (max: {self.max_file_size} Bytes)",
                    details={"error_code": 'VALIDATION_ERROR'}
                )
            
            # In temporäre Datei speichern
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                
            self.logger.debug(f"Audio-Datei heruntergeladen: {url} -> {temp_file}")
            return temp_file
            
        except Exception as e:
            self.logger.error("Fehler beim Herunterladen der Audio-Datei", error=e)
            raise ProcessingError(
                f"Fehler beim Herunterladen der Audio-Datei: {str(e)}",
                details={"error_code": 'FILE_ERROR'}
            )

    def _process_audio_file(self, file_path: str) -> Optional[AudioSegmentProtocol]:
        """Verarbeitet eine Audio-Datei und gibt ein AudioSegment zurück.
        
        Args:
            file_path: Pfad zur Audio-Datei
            
        Returns:
            Optional[AudioSegmentProtocol]: Das AudioSegment oder None bei Fehler
        """
        try:
            # Prüfe ob die Datei existiert
            if not os.path.exists(file_path):
                raise ProcessingError(
                    f"Audio-Datei nicht gefunden: {file_path}",
                    details={"error_code": 'FILE_ERROR'}
                )
            
            # Prüfe die Dateigröße
            file_size: int = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                raise ProcessingError(
                    f"Audio-Datei zu groß: {file_size} Bytes (max: {self.max_file_size} Bytes)",
                    details={"error_code": 'VALIDATION_ERROR'}
                )
            
            # Lade die Audio-Datei
            if not AudioSegment:
                raise ProcessingError("AudioSegment nicht verfügbar")
                
            raw_audio = AudioSegment.from_file(file_path)  # type: ignore
            audio: AudioSegmentProtocol = cast(AudioSegmentProtocol, raw_audio)
            
            if not audio:
                raise ProcessingError(
                    "Audio konnte nicht geladen werden",
                    details={"error_code": 'FILE_ERROR'}
                )
            
            return audio
            
        except Exception as e:
            if not isinstance(e, ProcessingError):
                self.logger.error("Fehler beim Verarbeiten der Audio-Datei", error=e)
                raise ProcessingError(
                    f"Fehler beim Verarbeiten der Audio-Datei: {str(e)}",
                    details={"error_code": 'FILE_ERROR'}
                )
            raise

    def get_process_dir(self, audio_path: str, original_filename: Optional[str] = None, video_id: Optional[str] = None, use_temp: bool = True) -> Path:
        """
        Erstellt ein Verzeichnis für die Verarbeitung basierend auf dem Dateinamen.
        
        Args:
            audio_path: Pfad zur Audio-Datei
            original_filename: Optionaler Original-Dateiname
            video_id: Optionale Video-ID (für YouTube-Videos)
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        # Verzeichnis basierend auf der ID oder dem Dateinamen erstellen
        if video_id:
            process_dir = base_dir / video_id
        elif original_filename:
            path_hash: str = hashlib.md5(str(original_filename).encode()).hexdigest()
            process_dir: Path = base_dir / path_hash
        else:
            path_hash = hashlib.md5(str(audio_path).encode()).hexdigest()
            process_dir = base_dir / path_hash
            
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
            
            # Erstelle Kapitel-Segmente (max. Segment-Dauer gemäß Konfiguration)
            chapter_segments: List[Chapter] = []
            
            # Segmentdauer in Minuten (aus Konfiguration in Sekunden)
            max_duration_minutes = self.segment_duration / 60
            
            # Verwende die Instanzvariable max_segments
            total_segments_count = 0
            
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
                        # Prüfe, ob wir das maximale Limit erreicht haben
                        if self.max_segments is not None and total_segments_count >= self.max_segments:
                            self.logger.info(f"Maximum von {self.max_segments} Segmenten erreicht, breche Segmentierung ab")
                            break
                            
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
                        
                        total_segments_count += 1  # Inkrementiere den Segmentzähler
                        
                        self.logger.debug(f"Kapitel {i+1} Teil {j+1}/{num_segments} erstellt",
                                        duration_sec=len(segment)/1000.0,
                                        segment_path=str(segment_path))
                else:
                    # Wenn Kapitel kurz genug ist, behalte es als ein Segment
                    
                    # Prüfe, ob wir das maximale Limit erreicht haben
                    if self.max_segments is not None and total_segments_count >= self.max_segments:
                        self.logger.info(f"Maximum von {self.max_segments} Segmenten erreicht, überspringe Kapitel {i}")
                        continue
                        
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
                    
                    total_segments_count += 1  # Inkrementiere den Segmentzähler
                    
                    self.logger.debug(f"Kapitel {i+1} als einzelnes Segment erstellt",
                                    duration_sec=len(chapter_audio)/1000.0,
                                    segment_path=str(segment_path))
                
                # Erstelle Chapter mit seinen Segmenten
                if segments:  # Nur wenn Segmente erstellt wurden
                    chapter_segments.append(Chapter(
                        title=title,
                        start=start_ms/1000.0,  # Konvertiere zu Sekunden
                        end=end_ms/1000.0,      # Konvertiere zu Sekunden
                        segments=segments
                    ))
                    
                # Wenn wir das maximale Limit erreicht haben, brechen wir ab
                if self.max_segments is not None and total_segments_count >= self.max_segments:
                    self.logger.info(f"Maximum von {self.max_segments} Segmenten erreicht, breche Kapitelverarbeitung ab")
                    break
            
            return chapter_segments

        except Exception as e:
            self.logger.error("Fehler bei der Segmentierung", error=e)
            raise

    def _create_cache_key(self, audio_path: str, source_info: Optional[Dict[str, Any]] = None, 
                         target_language: Optional[str] = None, template: Optional[str] = None) -> str:
        """Erstellt einen Cache-Schlüssel basierend auf der Audio-Quelle, Zielsprache und Template.
        
        Args:
            audio_path: Pfad zur Audio-Datei
            source_info: Optionale Informationen zur Quelle
            target_language: Die Zielsprache für die Verarbeitung
            template: Optionales Template für die Verarbeitung
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Bestimme die Basis für den Cache-Key
        base_key = ""
        
        if source_info:
            video_id = source_info.get('video_id')
            original_filename = source_info.get('original_filename')
            
            if video_id:
                # Bei Video-ID diese als Basis verwenden
                base_key = video_id
            elif original_filename:
                # Bei Original-Dateinamen diesen als Basis verwenden
                base_key = original_filename
            else:
                # Sonst den Pfad als Basis verwenden
                file_size = None
                try:
                    file_size = Path(audio_path).stat().st_size
                except:
                    pass
                    
                # Wenn Dateigröße verfügbar, diese mit in den Schlüssel einbeziehen
                if file_size:
                    base_key = f"{audio_path}_{file_size}"
                else:
                    base_key = audio_path
        else:
            # Sonst den Pfad als Basis verwenden
            file_size = None
            try:
                file_size = Path(audio_path).stat().st_size
            except:
                pass
                
            # Wenn Dateigröße verfügbar, diese mit in den Schlüssel einbeziehen
            if file_size:
                base_key = f"{audio_path}_{file_size}"
            else:
                base_key = audio_path
        
        # Zielsprache hinzufügen, wenn vorhanden
        if target_language:
            base_key += f"|lang={target_language}"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            base_key += f"|template={template}"
            
        self.logger.debug(f"Cache-Schlüssel erstellt: {base_key}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(base_key)

    def serialize_for_cache(self, result: AudioProcessingResult) -> Dict[str, Any]:
        """Serialisiert das AudioProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das AudioProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "source_path": getattr(result.metadata, "source_path", None),
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten aus dem Result-Objekt extrahieren
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None),
            "original_filename": getattr(result.metadata, "original_filename", None),
            "video_id": getattr(result.metadata, "video_id", None)
        }
        
        return cache_data
    
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> AudioProcessingResult:
        """Deserialisiert die Cache-Daten zurück in ein AudioProcessingResult.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            AudioProcessingResult: Das deserialisierte AudioProcessingResult
        """
        # Result-Objekt aus den Daten erstellen
        result_data = cached_data.get('result', {})
        result = AudioProcessingResult.from_dict(result_data)
        
        # Dynamisch zusätzliche Metadaten aus dem Cache hinzufügen
        metadata_attrs = {
            'source_path': cached_data.get('source_path'),
            'source_language': cached_data.get('source_language'),
            'target_language': cached_data.get('target_language'),
            'template': cached_data.get('template'),
            'original_filename': cached_data.get('original_filename'),
            'video_id': cached_data.get('video_id')
        }
        
        # Füge die zusätzlichen Attribute zum Metadata-Objekt hinzu
        for attr_name, attr_value in metadata_attrs.items():
            if attr_value is not None:
                setattr(result.metadata, attr_name, attr_value)
        
        return result

    def _create_specialized_indexes(self, collection: Any) -> None:
        """Erstellt spezialisierte Indizes für AudioProcessor-Cache.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Index für Audio-Pfad erstellen
            if "source_path_1" not in index_info:
                collection.create_index([("source_path", 1)])
                self.logger.debug("source_path-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")

    async def process(
        self,
        audio_source: Union[str, Path, bytes],
        source_info: Optional[Dict[str, Any]] = None,
        chapters: Optional[List[Dict[str, Any]]] = None,
        source_language: Optional[str] = None,
        target_language: Optional[str] = None,
        template: Optional[str] = None,
        skip_segments: Optional[List[int]] = None,
        use_cache: bool = True
    ) -> AudioResponse:
        """Verarbeitet eine Audio-Datei."""
        
        try:
            # Parameter validieren und standardisieren
            source_info = source_info or {}
            source_language = source_language or "de"
            target_language = target_language or source_language
            
            # Cache-Schlüssel generieren
            cache_key = self._create_cache_key(
                audio_path=str(audio_source),
                source_info=source_info,
                target_language=target_language,
                template=template
            )
            
            # Cache prüfen
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    return AudioResponse.create(
                        data=cached_result,
                        process=self.process_info
                    )
            
            # Audio verarbeiten
            audio = self._process_audio_file(str(audio_source))
            if not audio:
                raise ProcessingError("Audio konnte nicht verarbeitet werden")
            
            # Audio segmentieren
            process_dir = self.get_process_dir(str(audio_source), source_info.get('original_filename'))
            segments = self.get_audio_segments(audio, process_dir, chapters, skip_segments)
            
            # Transkription durchführen
            transcription_result = await self.transcriber.transcribe_segments(
                segments=segments,
                source_language=source_language,
                target_language=target_language,
                logger=self.logger,
                processor=self.__class__.__name__
            )
            
            # Template-Transformation wenn nötig
            if template:
                transformer_response = self.transformer_processor.transformByTemplate(
                    text=transcription_result.text,
                    source_language=source_language,
                    target_language=target_language,
                    template=template,
                    context=source_info
                )
                
                if transformer_response and transformer_response.data:
                    transcription_result = TranscriptionResult(
                        text=transformer_response.data.text,
                        source_language=transcription_result.source_language,
                        segments=transcription_result.segments
                    )
            
            # Ergebnis erstellen
            result = AudioProcessingResult(
                transcription=transcription_result,
                metadata=AudioMetadata(
                    duration=float(len(audio)) / 1000.0,
                    process_dir=str(process_dir),
                    format=self.export_format,
                    channels=getattr(audio, 'channels', 2)
                ),
                process_id=self.process_id
            )
            
            # Im Cache speichern
            if use_cache:
                self.save_to_cache(cache_key, result)
            
            # Response erstellen
            return AudioResponse.create(
                data=result,
                process=self.process_info
            )
            
        except Exception as e:
            self.logger.error("Fehler bei der Audio-Verarbeitung",
                            error=e,
                            error_type=type(e).__name__)
            
            return AudioResponse.create_error(
                error=ErrorInfo(
                    code="AUDIO_PROCESSING_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                ),
                process=self.process_info
            )

    def _create_temp_file(self, audio_data: bytes) -> Path:
        """Erstellt eine temporäre Datei aus Audio-Bytes.
        
        Args:
            audio_data: Die Audio-Daten als Bytes
            
        Returns:
            Path: Pfad zur temporären Datei
        """
        # Stelle sicher, dass das uploads-Verzeichnis im temp_dir existiert
        uploads_dir = self.temp_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        
        # Erstelle die temporäre Datei im uploads-Verzeichnis
        temp_file = uploads_dir / f"temp_{uuid.uuid4()}{self.temp_file_suffix}"
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
        """Behandelt Fehler während der Verarbeitung.
        
        Args:
            error: Der aufgetretene Fehler
            stage: Die Phase, in der der Fehler aufgetreten ist
        """
        error_type = type(error).__name__
        error_details = {
            "error_type": error_type,
            "stage": stage
        }
        
        self.logger.error(
            f"Fehler bei der Audio-Verarbeitung\nError: {str(error)} - Args: {error_details}",
            extra={"error": error, "error_details": error_details}
        )

    def _create_response(self, result: AudioProcessingResult, request: Dict[str, Any], 
                        elapsed_time: float, from_cache: bool = False, cache_key: str="") -> AudioResponse:
        """Erstellt eine API-Response aus dem Verarbeitungsergebnis.
        
        Args:
            result: Das Verarbeitungsergebnis
            request: Die ursprüngliche Anfrage
            elapsed_time: Die benötigte Zeit in Sekunden
            
        Returns:
            AudioResponse: Die API-Response
        """
        # Response erstellen
        response: AudioResponse = self.create_response(
            processor_name=ProcessorType.AUDIO.value,
            result=result,
            request_info=request,
            response_class=AudioResponse,
            from_cache=from_cache,
            cache_key=cache_key
        )
        
        return response 