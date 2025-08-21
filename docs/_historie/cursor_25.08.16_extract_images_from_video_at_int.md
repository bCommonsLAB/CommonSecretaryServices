# Extract images from video at intervals
_Exported on 8/21/2025 at 18:12:12 GMT+2 from Cursor (1.4.5)_

---

**User**

@video_processor.py  Ich habe da ein Video und möchte alle 5 Sekunden ein Bild speichern. Wie könnte ich das machen, dass es so ähnlich funktioniert wie das Transkribieren einer PDF-Datei, wo ja auch jede Seite einzeln analysiert wird? Ich möchte einfach mal einzelne Bilder generieren aus einem Video und diese in einem lokalen Filesystem speichern. Wie könnte man das bei diesem Videoprozessor als seperaten Endpoint anbieten? Also irgendwie Video to Image, wo man als Parameter den Abstand eingibt, alle Sekunden, ja, und welche Größe oder so.@video_routes.py Ich würde mir das in der Video-Route als eigenen Endpoint auspolieren.

---

**Cursor**

Ich starte mit einem kurzen Read-Only-Scan, um die vorhandenen Video-Modelle und Response-Strukturen zu verstehen und die neuen Funktionen sauber zu integrieren. Danach füge ich minimale, fokussierte Edits hinzu: eine neue Methode im `VideoProcessor` zum Extrahieren von Frames und einen neuen Endpoint in `video_routes.py`, der die Parameter `interval_seconds`, optionale Zielgröße und Format akzeptiert und die Bilder lokal speichert. Ich beginne mit einer Suche nach bestehenden Video-Modellen und Response-Typen, um die neue Response zu definieren oder wiederzuverwenden.

Ich schaue mir kurz die vorhandenen Response-Strukturen und Basismodelle an, um eine konsistente neue Response für Frame-Extraktion zu definieren und den Endpoint sauber anzubinden. Danach implementiere ich die minimalen Edits in Prozessor und Route.

Ich erweitere die Video-Modelle um Frame-Extraktionsergebnisse, implementiere im `VideoProcessor` eine `extract_frames`-Methode mit ffmpeg, und füge in `video_routes.py` einen neuen Endpoint mit Parametern für Intervall und Größe hinzu. Danach prüfe ich Linter-Fehler für die geänderten Dateien.

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_dict: Dict[str, Any] = audio_result_dict
                audio_result = AudioProcessingResult.from_dict(typed_dict)
            except:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_dict: Dict[str, Any] = transcription_dict
                transcription = TranscriptionResult.from_dict(typed_dict)
            except:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

from typing import List

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        return cls(
            metadata=VideoMetadata.from_dict(data['metadata']) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=[FrameInfo.from_dict(fd) for fd in data.get('frames', []) if isinstance(fd, dict)],
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

Ich implementiere jetzt die neuen Datentypen und den neuen Verarbeitungsweg: 1) ergänze `VideoProcessor` um `extract_frames` inkl. optionalem Caching; 2) erweitere die Cache-Serialisierung für beide Ergebnis-Typen; 3) füge in `video_routes.py` einen neuen Endpoint `/frames` (POST) mit Parametern `interval_seconds`, `width`, `height`, `format` hinzu. Anschließend prüfe ich die Linter-Hinweise für die geänderten Dateien.

```python
"""
Video Processor für die Verarbeitung von Video-Dateien.

LLM-Tracking Logik:
-----------------
Der VideoProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
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
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple, List
from datetime import datetime
import uuid
import hashlib
import subprocess  # Importiere subprocess für die FFmpeg-Integration
import json

import yt_dlp  # type: ignore

from src.core.config import Config
from src.core.models.base import ErrorInfo
from src.core.models.video import (
    VideoSource,
    VideoMetadata,
    VideoProcessingResult,
    VideoResponse,
    VideoFramesResult,
    VideoFramesResponse,
    FrameInfo
)
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.base import ProcessInfo
from .cacheable_processor import CacheableProcessor
from .transformer_processor import TransformerProcessor
from .audio_processor import AudioProcessor

# Typ-Alias für yt-dlp
YDLDict = Dict[str, Any]

class VideoProcessor(CacheableProcessor[VideoProcessingResult]):
    """
    Prozessor für die Verarbeitung von Video-Dateien.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der VideoProcessor erbt von CacheableProcessor, um MongoDB-Caching zu nutzen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "video_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den VideoProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Lade Konfiguration
        config = Config()
        processor_config = config.get('processors', {})
        video_config = processor_config.get('video', {})
        
        # Video-spezifische Konfigurationen
        self.max_duration = video_config.get('max_duration', 3600)  # 1 Stunde
        
        # Debug-Logging der Video-Konfiguration
        self.logger.debug("VideoProcessor initialisiert mit Konfiguration", 
                         max_duration=self.max_duration,
                         temp_dir=str(self.temp_dir),
                         cache_dir=str(self.cache_dir))
        
        # Initialisiere Prozessoren
        self.transformer = TransformerProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Initialisiere den Transcriber mit Video-spezifischen Konfigurationen
        transcriber_config = {
            "process_id": process_id,
            "processor_name": "video",
            "cache_dir": str(self.cache_dir),  # Haupt-Cache-Verzeichnis
            "temp_dir": str(self.temp_dir),    # Temporäres Unterverzeichnis
            "debug_dir": str(self.temp_dir / "debug")
        }
        self.transcriber = WhisperTranscriber(transcriber_config, processor=self)
        
        self.audio_processor = AudioProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Download-Optionen
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'socket_timeout': 30,
            'retries': 10,
            'sleep_interval': 3,
            'max_sleep_interval': 10,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'no_playlist': True,
            'extract_flat': False,
            'youtube_include_dash_manifest': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            },
            'extractor_args': {
                'vimeo': {
                    'password': None,
                    'access_token': None
                }
            },
            'format_sort': ['ext:mp4:m4a', 'ext:webm:webma', 'ext:mp3'],
            'prefer_ffmpeg': True,
            'keepvideo': False
        }
    
    def create_process_dir(self, identifier: str, use_temp: bool = True) -> Path:
        """
        Erstellt und gibt das Verarbeitungsverzeichnis für ein Video zurück.
        
        Args:
            identifier: Eindeutige Kennung des Videos (URL, ID, etc.)
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        # Verzeichnis mit Unterordner "video" erstellen
        process_dir = base_dir / "video" / identifier
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir
        
    def _format_duration(self, seconds: int) -> str:
        """Formatiert Sekunden in ein lesbares Format (HH:MM:SS)."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _normalize_vimeo_url(self, url: str) -> str:
        """
        Konvertiert Vimeo-Player-URLs in direkte Vimeo-URLs.
        
        Args:
            url: Die ursprüngliche URL
            
        Returns:
            str: Die normalisierte Vimeo-URL
        """
        import re
        
        # Vimeo-Player-URL-Muster
        player_pattern = r'https?://player\.vimeo\.com/video/(\d+)'
        match = re.match(player_pattern, url)
        
        if match:
            video_id = match.group(1)
            normalized_url = f"https://vimeo.com/{video_id}"
            self.logger.info(f"Vimeo-Player-URL normalisiert: {url} -> {normalized_url}")
            return normalized_url
        
        # Direkte Vimeo-URL bereits korrekt
        if 'vimeo.com' in url:
            return url
            
        return url

    def _extract_video_info(self, url: str) -> Tuple[str, int, str]:
        """
        Extrahiert grundlegende Informationen aus einem Video.
        
        Args:
            url: URL des Videos
            
        Returns:
            Tuple mit (Titel, Dauer in Sekunden, Video-ID)
        """
        # URL normalisieren (besonders für Vimeo)
        normalized_url = self._normalize_vimeo_url(url)
        
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info: YDLDict = ydl.extract_info(normalized_url, download=False)  # type: ignore
            if not info:
                raise ValueError("Keine Video-Informationen gefunden")
            
            video_id = str(info.get('id', hashlib.md5(normalized_url.encode()).hexdigest()))
            title = str(info.get('title', 'Unbekanntes Video'))
            duration = int(info.get('duration', 0))
            
            return title, duration, video_id

    def _create_cache_key(self, source: Union[str, VideoSource], target_language: str = 'de', template: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf der Video-Quelle, Zielsprache und Template.
        
        Args:
            source: Die Video-Quelle (URL oder VideoSource-Objekt)
            target_language: Die Zielsprache für die Verarbeitung
            template: Optionales Template für die Verarbeitung
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Schlüssel aus der Quelle erstellen
        base_key = ""
        
        # Bei VideoSource das URL-Attribut verwenden
        if isinstance(source, VideoSource):
            if source.url:
                base_key = source.url
            elif source.file_name:
                # Bei hochgeladenen Dateien einen erweiterten Schlüssel mit mehreren Attributen erstellen
                file_info = {
                    'name': source.file_name,
                    'size': source.file_size
                }
                # Serialisieren und hashen
                base_key = hashlib.md5(json.dumps(file_info, sort_keys=True).encode()).hexdigest()
            else:
                raise ValueError("VideoSource muss entweder URL oder file_name haben")
        else:
            # Bei String direkt als URL verwenden
            base_key = source
        
        # Zielsprache hinzufügen
        cache_key = f"{base_key}|lang={target_language}"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            cache_key += f"|template={template}"
            
        self.logger.debug(f"Cache-Schlüssel erstellt: {cache_key}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(cache_key)

    def serialize_for_cache(self, result: Union[VideoProcessingResult, VideoFramesResult]) -> Dict[str, Any]:
        """
        Serialisiert das VideoProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das VideoProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern, inkl. Typ-Kennzeichnung
        result_type = "video_frames" if isinstance(result, VideoFramesResult) else "video_processing"
        cache_data = {
            "result_type": result_type,
            "result": result.to_dict(),
            "source_url": result.metadata.source.url if result.metadata.source else None,
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten aus dem Result-Objekt extrahieren
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None)
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> Union[VideoProcessingResult, VideoFramesResult]:
        """
        Deserialisiert die Cache-Daten zurück in ein VideoProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            VideoProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        result_type = cached_data.get("result_type", "video_processing")
        if result_type == "video_frames":
            return VideoFramesResult.from_dict(result_data)
        return VideoProcessingResult.from_dict(result_data)

    def _create_cache_key_frames(
        self,
        source: Union[str, VideoSource],
        interval_seconds: int,
        width: Optional[int],
        height: Optional[int],
        image_format: str = "jpg"
    ) -> str:
        """Erstellt Cache-Key für Frame-Extraktion."""
        if isinstance(source, VideoSource):
            base_key = source.url or (source.file_name or "uploaded_file")
        else:
            base_key = source
        size_part = f"size={width}x{height}" if width or height else "size=orig"
        key_str = f"frames|{base_key}|interval={interval_seconds}|{size_part}|fmt={image_format}"
        return self.generate_cache_key(key_str)

    async def extract_frames(
        self,
        source: Union[str, VideoSource],
        interval_seconds: int = 5,
        width: Optional[int] = None,
        height: Optional[int] = None,
        image_format: str = "jpg",
        use_cache: bool = True,
        binary_data: Optional[bytes] = None
    ) -> VideoFramesResponse:
        """Extrahiert Frames in festem Intervall und speichert sie lokal."""
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        frames_dir: Path = working_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        temp_video_path: Optional[Path] = None
        title: str = ""
        duration: int = 0
        video_id: str = ""

        try:
            # Quelle normalisieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source = source

            cache_key = self._create_cache_key_frames(video_source if isinstance(video_source, VideoSource) else source,
                                                      interval_seconds, width, height, image_format)
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and isinstance(cached_result, VideoFramesResult):
                    return self.create_response(
                        processor_name="video",
                        result=cached_result,
                        request_info={
                            'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                            'interval_seconds': interval_seconds,
                            'width': width,
                            'height': height,
                            'format': image_format,
                            'use_cache': use_cache
                        },
                        response_class=VideoFramesResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # Video vorbereiten (vollständiges Video, nicht nur Audio)
            if video_source.url:
                normalized_url = self._normalize_vimeo_url(video_source.url)
                with yt_dlp.YoutubeDL({
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestvideo+bestaudio/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': str(working_dir / '%(title)s.%(ext)s'),
                    'retries': 10,
                    'socket_timeout': 30,
                    'nocheckcertificate': True,
                }) as ydl:
                    info: YDLDict = ydl.extract_info(normalized_url, download=True)  # type: ignore
                    if not info:
                        raise ValueError("Keine Video-Informationen gefunden")
                    video_id = str(info.get('id'))
                    title = str(info.get('title', 'video'))
                    duration = int(info.get('duration', 0))
                # Eingangsdatei finden
                candidates = list(working_dir.glob("*.mp4")) + list(working_dir.glob("*.mkv")) + list(working_dir.glob("*.webm"))
                if not candidates:
                    raise ValueError("Heruntergeladenes Video nicht gefunden")
                temp_video_path = candidates[0]
            else:
                # Upload-Fall
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "uploaded_video"
                if not video_source.file_name or not binary_data:
                    raise ValueError("Dateiname und Binärdaten erforderlich für Upload")
                temp_video_path = working_dir / video_source.file_name
                temp_video_path.write_bytes(binary_data)

            # ffmpeg-Filterkette aufbauen
            filters: List[str] = []
            # 1 Frame alle N Sekunden
            filters.append(f"fps=1/{max(1, int(interval_seconds))}")
            # Optional skalieren
            if width or height:
                w = width if width else -1
                h = height if height else -1
                filters.append(f"scale={w}:{h}:flags=lanczos")
            filter_str = ",".join(filters)

            # Ausgabeformat und Pfad
            image_ext = image_format.lower()
            if image_ext not in {"jpg", "jpeg", "png"}:
                image_ext = "jpg"
            output_pattern = frames_dir / f"frame_%06d.{image_ext}"

            # ffmpeg ausführen
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', str(temp_video_path),
                '-vf', filter_str,
                str(output_pattern)
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)

            # erzeugte Dateien einsammeln
            files = sorted(frames_dir.glob(f"*.{image_ext}"))
            frames: List[FrameInfo] = []
            for idx, fpath in enumerate(files, start=0):
                frames.append(FrameInfo(
                    index=idx,
                    timestamp_s=float(idx * max(1, int(interval_seconds))),
                    file_path=str(fpath),
                    width=width,
                    height=height
                ))

            # Metadaten
            metadata = VideoMetadata(
                title=title or "",
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration if duration else 0),
                process_dir=str(working_dir),
                video_id=video_id
            )

            frames_result = VideoFramesResult(
                metadata=metadata,
                process_id=self.process_id,
                output_dir=str(frames_dir),
                interval_seconds=int(interval_seconds),
                frame_count=len(frames),
                frames=frames
            )

            # Optional cachen
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=frames_result)

            return self.create_response(
                processor_name="video",
                result=frames_result,
                request_info={
                    'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                    'interval_seconds': interval_seconds,
                    'width': width,
                    'height': height,
                    'format': image_format,
                    'use_cache': use_cache
                },
                response_class=VideoFramesResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error("Fehler bei der Frame-Extraktion",
                              error=e,
                              error_type=type(e).__name__)
            error_source = VideoSource()
            return self.create_response(
                processor_name="video",
                result=VideoFramesResult(
                    metadata=VideoMetadata(
                        title="Error",
                        source=error_source,
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    process_id=self.process_id,
                    output_dir=str(frames_dir),
                    interval_seconds=int(interval_seconds),
                    frame_count=0,
                    frames=[]
                ),
                request_info={
                    'source': str(source),
                    'interval_seconds': interval_seconds,
                    'width': width,
                    'height': height,
                    'format': image_format,
                    'use_cache': use_cache
                },
                response_class=VideoFramesResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_FRAME_EXTRACTION_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )
        finally:
            # temp video optional nicht löschen, da frames im selben Ordner liegen; hier keine zusätzliche Bereinigung
            pass

    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die Video-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Index für source_url
            if "source_url_1" not in index_info:
                collection.create_index([("source_url", 1)])
                self.logger.debug("source_url-Index erstellt")
            
            # Index für processed_at
            if "processed_at_1" not in index_info:
                collection.create_index([("processed_at", 1)])
                self.logger.debug("processed_at-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")

    async def process(
        self, 
        source: Union[str, VideoSource],
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None,
        use_cache: bool = True,
        binary_data: Optional[bytes] = None
    ) -> VideoResponse:
        """Verarbeitet ein Video."""
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        temp_video_path: Optional[Path] = None
        audio_path: Optional[Path] = None

        try:
            # Video-Quelle validieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source: VideoSource = source

            # Cache-Schlüssel generieren und prüfen
            cache_key = self._create_cache_key(source, target_language, template)
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Video: {cached_result.metadata.title}")
                    return self.create_response(
                        processor_name="video",
                        result=cached_result,
                        request_info={
                            'source': source.to_dict() if isinstance(source, VideoSource) and hasattr(source, 'to_dict') else str(source),
                            'source_language': source_language,
                            'target_language': target_language,
                            'template': template,
                            'use_cache': use_cache
                        },
                        response_class=VideoResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # Video-Informationen extrahieren
            if video_source.url:
                # URL normalisieren (besonders für Vimeo)
                normalized_url = self._normalize_vimeo_url(video_source.url)
                title, duration, video_id = self._extract_video_info(normalized_url)
                
                # Video herunterladen
                download_opts = self.ydl_opts.copy()
                output_path = str(working_dir / "%(title)s.%(ext)s")
                download_opts['outtmpl'] = output_path
                
                self.logger.info(f"Starte Download von: {normalized_url}")
                with yt_dlp.YoutubeDL(download_opts) as ydl:
                    ydl.download([normalized_url])  # type: ignore
            else:
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "Hochgeladenes Video"
                duration = 0
                
                if not video_source.file_name or not binary_data:
                    raise ValueError("Dateiname und Binärdaten erforderlich für Upload")
                
                # Binärdaten speichern
                temp_video_path = working_dir / video_source.file_name
                temp_video_path.write_bytes(binary_data)

                # Zu MP3 konvertieren
                if not temp_video_path.suffix.lower() == '.mp3':
                    audio_path = temp_video_path.with_suffix('.mp3')
                    cmd = [
                        'ffmpeg', '-i', str(temp_video_path),
                        '-vn', '-acodec', 'libmp3lame',
                        '-q:a', '4', '-y', str(audio_path)
                    ]
                    subprocess.run(cmd, check=True, capture_output=True, text=True)

            # MP3-Datei finden wenn nicht schon gesetzt
            if not audio_path:
                mp3_files = list(working_dir.glob("*.mp3"))
                if not mp3_files:
                    raise ValueError("Keine MP3-Datei gefunden")
                audio_path = mp3_files[0]

            # Dauer prüfen
            if duration > self.max_duration:
                raise ValueError(f"Video zu lang: {duration} Sekunden (Maximum: {self.max_duration} Sekunden)")

            # Audio verarbeiten
            self.logger.info("Starte Audio-Verarbeitung")
            audio_response = await self.audio_processor.process(
                audio_source=str(audio_path),
                source_info={
                    'original_filename': title,
                    'video_id': video_id
                },
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache
            )

            # Erkannte Quellsprache aktualisieren
            if audio_response.data and audio_response.data.transcription:
                if source_language == 'auto':
                    source_language = audio_response.data.transcription.source_language

            # Metadaten erstellen
            metadata = VideoMetadata(
                title=title,
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration),
                file_size=audio_path.stat().st_size if audio_path else None,
                process_dir=str(working_dir),
                audio_file=str(audio_path) if audio_path else None
            )

            # Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=metadata,
                transcription=audio_response.data.transcription if audio_response.data else None,
                process_id=self.process_id
            )

            # Im Cache speichern
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=result)

            # Response erstellen
            return self.create_response(
                processor_name="video",
                result=result,
                request_info={
                    'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=VideoResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error("Fehler bei der Video-Verarbeitung",
                            error=e,
                            error_type=type(e).__name__)

            # Erstelle eine standardmäßige VideoSource für den Fehlerfall
            error_source = VideoSource()
            
            # Einfache String-Repräsentation des Quellobjekts
            source_repr = str(source)

            return self.create_response(
                processor_name="video",
                result=VideoProcessingResult(
                    metadata=VideoMetadata(
                        title="Error",
                        source=error_source,
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    transcription=None,
                    process_id=self.process_id
                ),
                request_info={
                    'source': source_repr,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=VideoResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_PROCESSING_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )

        finally:
            # Aufräumen
            if temp_video_path and temp_video_path.exists():
                try:
                    temp_video_path.unlink()
                    self.logger.debug(f"Temporäre Videodatei gelöscht: {temp_video_path}")
                except Exception as cleanup_error:
                    self.logger.warning(f"Konnte temporäre Datei nicht löschen: {cleanup_error}") 
```

```python
# type: ignore
"""
Video-Prozessor API-Routen.
Enthält alle Endpoints zur Verarbeitung von Video-Dateien und YouTube-Videos.
"""
from flask import request
from flask_restx import Model, Namespace, OrderedModel, Resource, fields
from typing import Dict, Any, Union, Optional
import traceback
import asyncio
import uuid
from werkzeug.datastructures import FileStorage
import time
from datetime import datetime
import os
from pathlib import Path

from src.processors.video_processor import VideoProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.core.models.video import VideoSource, VideoResponse, VideoFramesResponse
from src.core.models.youtube import YoutubeResponse
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker, PerformanceTracker

# Initialisiere Logger
logger = get_logger(process_id="video-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
video_ns = Namespace('video', description='Video-Verarbeitungs-Operationen')

# Parser für Multipart-Formulardaten (für Datei-Uploads)
video_upload_parser = video_ns.parser()
video_upload_parser.add_argument('file', location='files', type=FileStorage, required=False, help='Video-Datei zum Hochladen')
video_upload_parser.add_argument('url', location='form', type=str, required=False, help='URL des Videos (alternativ zur Datei)')
video_upload_parser.add_argument('target_language', location='form', type=str, default='de', required=False, help='Zielsprache für die Transkription')
video_upload_parser.add_argument('source_language', location='form', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
video_upload_parser.add_argument('template', location='form', type=str, required=False, help='Optional Template für die Verarbeitung')
video_upload_parser.add_argument('useCache', location='form', type=str, default='true', required=False, help='Cache verwenden (true/false)')
video_upload_parser.add_argument('force_refresh', location='form', type=str, default='false', required=False, help='Cache ignorieren und Verarbeitung erzwingen (true/false)')

# Parser für Frame-Extraktion (Form)
frames_form_parser = video_ns.parser()
frames_form_parser.add_argument('file', location='files', type=FileStorage, required=False, help='Video-Datei zum Hochladen')
frames_form_parser.add_argument('url', location='form', type=str, required=False, help='URL des Videos (alternativ zur Datei)')
frames_form_parser.add_argument('interval_seconds', location='form', type=int, default=5, required=False, help='Abstand zwischen Frames in Sekunden')
frames_form_parser.add_argument('width', location='form', type=int, required=False, help='Zielbreite der Bilder (optional)')
frames_form_parser.add_argument('height', location='form', type=int, required=False, help='Zielhöhe der Bilder (optional)')
frames_form_parser.add_argument('format', location='form', type=str, default='jpg', required=False, help='Bildformat (jpg/png)')
frames_form_parser.add_argument('useCache', location='form', type=str, default='true', required=False, help='Cache verwenden (true/false)')

# Parser für JSON-Anfragen
video_json_parser = video_ns.parser()
video_json_parser.add_argument('url', location='json', type=str, required=True, help='URL des Videos')
video_json_parser.add_argument('target_language', location='json', type=str, default='de', required=False, help='Zielsprache für die Transkription')
video_json_parser.add_argument('source_language', location='json', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
video_json_parser.add_argument('template', location='json', type=str, required=False, help='Optional Template für die Verarbeitung')
video_json_parser.add_argument('useCache', location='json', type=bool, default=True, required=False, help='Cache verwenden (default: True)')
video_json_parser.add_argument('force_refresh', location='json', type=bool, default=False, required=False, help='Cache ignorieren und Verarbeitung erzwingen (default: False)')

# Parser für Frame-Extraktion (JSON)
frames_json_parser = video_ns.parser()
frames_json_parser.add_argument('url', location='json', type=str, required=False, help='URL des Videos')
frames_json_parser.add_argument('interval_seconds', location='json', type=int, default=5, required=False, help='Abstand zwischen Frames in Sekunden')
frames_json_parser.add_argument('width', location='json', type=int, required=False, help='Zielbreite der Bilder (optional)')
frames_json_parser.add_argument('height', location='json', type=int, required=False, help='Zielhöhe der Bilder (optional)')
frames_json_parser.add_argument('format', location='json', type=str, default='jpg', required=False, help='Bildformat (jpg/png)')
frames_json_parser.add_argument('useCache', location='json', type=bool, default=True, required=False, help='Cache verwenden (default: True)')

# Parser für YouTube-Anfragen
youtube_parser = video_ns.parser()
youtube_parser.add_argument('url', location='json', type=str, required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', help='YouTube Video URL')
youtube_parser.add_argument('source_language', location='json', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
youtube_parser.add_argument('target_language', location='json', type=str, default='de', required=False, help='Zielsprache (ISO 639-1 code)')
youtube_parser.add_argument('template', location='json', type=str, default='youtube', required=False, help='Template für die Verarbeitung')
youtube_parser.add_argument('useCache', location='json', type=bool, default=True, required=False, help='Cache verwenden (default: True)')

# Parser für YouTube-Anfragen mit Formular
youtube_form_parser = video_ns.parser()
youtube_form_parser.add_argument('url', location='form', type=str, required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', help='YouTube Video URL')
youtube_form_parser.add_argument('source_language', location='form', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
youtube_form_parser.add_argument('target_language', location='form', type=str, default='de', required=False, help='Zielsprache (ISO 639-1 code)')
youtube_form_parser.add_argument('template', location='form', type=str, default='youtube', required=False, help='Template für die Verarbeitung')
youtube_form_parser.add_argument('useCache', location='form', type=str, default='true', required=False, help='Cache verwenden (true/false)')

# Definiere Error-Modell, identisch zum alten Format
error_model: Model | OrderedModel = video_ns.model('Error', {
    'error': fields.String(description='Fehlermeldung')
})

# Definiere Modelle für die API-Dokumentation - IDENTISCH zur alten Version
youtube_response: Model | OrderedModel = video_ns.model('YoutubeResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(video_ns.model('YoutubeRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(video_ns.model('YoutubeProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(video_ns.model('YoutubeData', {
        'metadata': fields.Raw(description='Video Metadaten'),
        'transcription': fields.Raw(description='Transkriptionsergebnis (wenn verfügbar)')
    })),
    'error': fields.Nested(video_ns.model('YoutubeError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Explizites Modell für Video-Responses
video_response: Model | OrderedModel = video_ns.model('VideoResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(video_ns.model('VideoRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(video_ns.model('VideoProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(video_ns.model('VideoData', {
        'metadata': fields.Raw(description='Video Metadaten'),
        'transcription': fields.Raw(description='Transkriptionsergebnis (wenn verfügbar)')
    })),
    'error': fields.Nested(video_ns.model('VideoError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Model für Youtube-URLs und Parameter
youtube_input = video_ns.model('YoutubeInput', {
    'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache (ISO 639-1 code)'),
    'template': fields.String(required=False, default='youtube', description='Template für die Verarbeitung (default: youtube)'),
    'useCache': fields.Boolean(required=False, default=True, description='Cache verwenden (default: True)')
})

# Model für Video-Requests (für JSON-Anfragen)
video_request = video_ns.model('VideoRequest', {
    'url': fields.String(required=False, description='URL des Videos'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache für die Transkription'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'template': fields.String(required=False, description='Optional Template für die Verarbeitung'),
    'useCache': fields.Boolean(required=False, default=True, description='Cache verwenden (default: True)')
})

# Helper-Funktionen zum Abrufen der Prozessoren
def get_video_processor(process_id: Optional[str] = None) -> VideoProcessor:
    """Get or create video processor instance with process ID"""
    if not process_id:
        process_id = str(uuid.uuid4())
    return VideoProcessor(resource_calculator, process_id=process_id)

def get_youtube_processor(process_id: Optional[str] = None) -> YoutubeProcessor:
    """Get or create youtube processor instance with process ID"""
    if not process_id:
        process_id = str(uuid.uuid4())
    return YoutubeProcessor(resource_calculator, process_id=process_id)

# Hilfsfunktion für die YouTube-Verarbeitung
async def process_youtube(url: str, source_language: str = 'auto', target_language: str = 'de', 
                          template: str = 'youtube', use_cache: bool = True, process_id: Optional[str] = None) -> YoutubeResponse:
    """
    Verarbeitet eine YouTube-URL und extrahiert den Audio-Inhalt.
    
    Args:
        url: Die YouTube-URL
        source_language: Die Quellsprache des Videos (auto für automatische Erkennung)
        target_language: Die Zielsprache für die Transkription
        template: Das zu verwendende Template
        use_cache: Ob der Cache verwendet werden soll
        process_id: Optional eine eindeutige Prozess-ID
        
    Returns:
        YoutubeResponse mit den Verarbeitungsergebnissen
    """
    if not process_id:
        process_id = str(uuid.uuid4())
    
    youtube_processor = get_youtube_processor(process_id)
    logger.info(f"Verarbeite YouTube-URL: {url} mit Prozess-ID: {process_id}")
    
    result = await youtube_processor.process(
        url=url,
        source_language=source_language,
        target_language=target_language,
        template=template,
        use_cache=use_cache
    )
    
    return result

# Hilfsfunktion für die Video-Verarbeitung
async def process_video(source: VideoSource, binary_data: Optional[bytes] = None, source_language: str = 'auto', target_language: str = 'de',
                       template: Optional[str] = None, use_cache: bool = True, 
                       force_refresh: bool = False, process_id: Optional[str] = None) -> VideoResponse:
    """
    Verarbeitet ein Video und extrahiert den Audio-Inhalt.
    
    Args:
        source: Die VideoSource (URL oder Datei)
        binary_data: Die Binärdaten des Videos (optional)
        source_language: Die Quellsprache des Videos (auto für automatische Erkennung)
        target_language: Die Zielsprache für die Transkription
        template: Das zu verwendende Template (optional)
        use_cache: Ob der Cache verwendet werden soll
        force_refresh: Ob der Cache ignoriert und die Verarbeitung erzwungen werden soll
        process_id: Optional eine eindeutige Prozess-ID
        
    Returns:
        VideoResponse mit den Verarbeitungsergebnissen
    """
    if not process_id:
        process_id = str(uuid.uuid4())
    
    processor: VideoProcessor = get_video_processor(process_id)
    logger.info(f"Starte Video-Verarbeitung mit Prozess-ID: {process_id}")
    
    # Video verarbeiten mit den vom Benutzer angegebenen Cache-Einstellungen
    result: VideoResponse = await processor.process(
        source=source,
        binary_data=binary_data,
        target_language=target_language,
        source_language=source_language,
        template=template,
        use_cache=use_cache
    )
    
    # Wenn force_refresh aktiviert ist, sollte die Prozessorlogik dies bereits berücksichtigt haben
    # In Zukunft kann hier zusätzliche Logik für force_refresh hinzugefügt werden, wenn der Prozessor dies unterstützt
    
    return result

# Hilfsfunktion für Frame-Extraktion
async def process_video_frames(source: VideoSource, binary_data: Optional[bytes] = None,
                               interval_seconds: int = 5,
                               width: Optional[int] = None,
                               height: Optional[int] = None,
                               image_format: str = 'jpg',
                               use_cache: bool = True,
                               process_id: Optional[str] = None) -> VideoFramesResponse:
    if not process_id:
        process_id = str(uuid.uuid4())
    processor: VideoProcessor = get_video_processor(process_id)
    logger.info(f"Starte Frame-Extraktion mit Prozess-ID: {process_id}")
    result: VideoFramesResponse = await processor.extract_frames(
        source=source,
        interval_seconds=interval_seconds,
        width=width,
        height=height,
        image_format=image_format,
        use_cache=use_cache,
        binary_data=binary_data
    )
    return result

# YouTube-Endpunkt
@video_ns.route('/youtube')
class YoutubeEndpoint(Resource):
    @video_ns.expect(youtube_form_parser)
    @video_ns.response(200, 'Erfolg', youtube_response)
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.doc(id='process_youtube',
                 description='Verarbeitet ein Youtube-Video und extrahiert den Audio-Inhalt. Unterstützt sowohl JSON als auch Formular-Anfragen.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet ein Youtube-Video und extrahiert den Audio-Inhalt.
        
        Benötigt eine gültige YouTube-URL und unterstützt verschiedene Parameter zur Steuerung der Verarbeitung.
        Die Verarbeitung umfasst das Herunterladen des Videos, die Extraktion der Audio-Spur und die Transkription des Inhalts.
        
        Die Anfrage kann entweder als JSON oder als Formular (multipart/form-data) gesendet werden.
        """
        try:
            # Prozess-ID für die Verarbeitung
            process_id = str(uuid.uuid4())
            tracker = get_performance_tracker() or get_performance_tracker(process_id)
            
            # Parameter verarbeiten
            url = None
            source_language = 'auto'
            target_language = 'de'
            template = 'youtube'
            use_cache = True
            
            # Prüfe, ob die Anfrage als Formular oder als JSON gesendet wurde
            if request.form and 'url' in request.form:
                # Formular-Anfrage
                url = request.form.get('url')
                source_language = request.form.get('source_language', 'auto')
                target_language = request.form.get('target_language', 'de')
                template = request.form.get('template', 'youtube')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
            else:
                # JSON-Anfrage
                args = youtube_parser.parse_args()
                url = args.get('url')
                source_language = args.get('source_language', 'auto')
                target_language = args.get('target_language', 'de')
                template = args.get('template', 'youtube')
                use_cache = args.get('useCache', True)

            if not url:
                raise ProcessingError("Youtube-URL ist erforderlich")
            
            # Verarbeite YouTube-Video mit der Hilfsfunktion
            result = asyncio.run(process_youtube(
                url=url,
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache,
                process_id=process_id
            ))
            
            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker and hasattr(tracker, 'eval_result'):
                tracker.eval_result(result)
            
            # Konvertiere Ergebnis in Dict und gib es zurück
            return result.to_dict()
            
        except ValueError as ve:
            logger.error("Validierungsfehler",
                        error=ve,
                        error_type="ValidationError",
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': 'ValidationError',
                    'message': str(ve),
                    'details': {}
                }
            }, 400
        except ProcessingError as e:
            logger.error("Verarbeitungsfehler",
                        error=e,
                        error_type="ProcessingError",
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': getattr(e, 'error_code', 'ProcessingError'),
                    'message': str(e),
                    'details': getattr(e, 'details', {})
                }
            }, 400
        except Exception as e:
            logger.error("Youtube-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {
                        'error_type': type(e).__name__,
                        'traceback': traceback.format_exc()
                    }
                }
            }, 400

# Video-Verarbeitungs-Endpunkt
@video_ns.route('/process')
class VideoProcessEndpoint(Resource):
    @video_ns.doc(id='process_video', 
                 description='Verarbeitet ein Video und extrahiert den Audio-Inhalt. Unterstützt sowohl URLs als auch Datei-Uploads über Formular-Anfragen.')
    @video_ns.response(200, 'Erfolg', video_response)
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.expect(video_upload_parser)
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet ein Video und extrahiert den Audio-Inhalt.
        Unterstützt sowohl URLs als auch Datei-Uploads.
        
        Für Datei-Uploads verwende multipart/form-data mit dem Parameter 'file'.
        Für URL-basierte Verarbeitung kann entweder multipart/form-data mit dem Parameter 'url' 
        oder eine JSON-Anfrage mit dem Parameter 'url' verwendet werden.
        """
        try:
            # Initialisiere Variablen
            source: VideoSource = None
            binary_data: Optional[bytes] = None
            target_language: str = 'de'
            source_language: str = 'auto'
            template: Optional[str] = None
            use_cache: bool = True
            force_refresh: bool = False
            process_id = str(uuid.uuid4())

            # Prüfe ob Datei oder URL
            if request.files and 'file' in request.files and request.files['file'].filename:
                # File Upload
                uploaded_file: FileStorage = request.files['file']
                # Lese binäre Daten, aber speichere sie NICHT in der VideoSource
                binary_data = uploaded_file.read()
                # Größe der Datei bestimmen
                file_size = len(binary_data)
                # Aktueller Zeitstempel
                upload_timestamp = datetime.now().isoformat()
                # Erstelle VideoSource mit zusätzlichen Identifikationsmerkmalen
                source = VideoSource(
                    file_name=uploaded_file.filename,
                    file_size=file_size,
                    upload_timestamp=upload_timestamp
                )
                # Parameter aus form-data
                target_language = request.form.get('target_language', 'de')
                source_language = request.form.get('source_language', 'auto')
                template = request.form.get('template')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
                force_refresh_str = request.form.get('force_refresh', 'false')
                force_refresh = force_refresh_str.lower() == 'true'
                
                logger.info(f"Verarbeite hochgeladene Datei: {uploaded_file.filename}")
            elif request.form and 'url' in request.form and request.form['url']:
                # URL aus form-data
                url = request.form.get('url')
                source = VideoSource(url=url)
                
                # Parameter aus form-data
                target_language = request.form.get('target_language', 'de')
                source_language = request.form.get('source_language', 'auto')
                template = request.form.get('template')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
                force_refresh_str = request.form.get('force_refresh', 'false')
                force_refresh = force_refresh_str.lower() == 'true'
                
                logger.info(f"Verarbeite Video-URL aus form-data: {url}")
            else:
                # JSON Request
                data = request.get_json()
                if not data or 'url' not in data:
                    raise ProcessingError("Entweder URL oder Datei muss angegeben werden")
                
                url = data.get('url')
                source = VideoSource(url=url)
                
                # Parameter aus JSON
                target_language = data.get('target_language', 'de')
                source_language = data.get('source_language', 'auto')
                template = data.get('template')
                use_cache = data.get('useCache', True)
                force_refresh = data.get('force_refresh', False)
                
                logger.info(f"Verarbeite Video-URL aus JSON: {url}")

            if not source:
                raise ProcessingError("Keine gültige Video-Quelle gefunden")

            # Verarbeite Video mit Hilfsfunktion
            result: VideoResponse = asyncio.run(process_video(
                source=source,
                binary_data=binary_data,  # Übergebe die Binärdaten separat
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache,
                force_refresh=force_refresh,
                process_id=process_id
            ))
            
            # Konvertiere Ergebnis in Dict und gib es zurück
            return result.to_dict()

        except ProcessingError as e:
            logger.error(f"Verarbeitungsfehler: {str(e)}", exc_info=True)
            return {
                'status': 'error',
                'error': {
                    'code': 'PROCESSING_ERROR',
                    'message': str(e),
                    'details': getattr(e, 'details', {})
                }
            }, 400
        except Exception as e:
            logger.error("Video-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {
                        'error_type': type(e).__name__,
                        'traceback': traceback.format_exc()
                    }
                }
            }, 500 

# Video-Frames Endpunkt
@video_ns.route('/frames')
class VideoFramesEndpoint(Resource):
    @video_ns.doc(id='extract_video_frames', description='Extrahiert Frames aus einem Video in festem Intervall und speichert sie lokal.')
    @video_ns.response(200, 'Erfolg')
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.expect(frames_form_parser)
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        try:
            source: VideoSource = None
            binary_data: Optional[bytes] = None
            interval_seconds: int = 5
            width: Optional[int] = None
            height: Optional[int] = None
            image_format: str = 'jpg'
            use_cache: bool = True
            process_id = str(uuid.uuid4())

            # Datei-Upload?
            if request.files and 'file' in request.files and request.files['file'].filename:
                uploaded_file: FileStorage = request.files['file']
                binary_data = uploaded_file.read()
                file_size = len(binary_data)
                upload_timestamp = datetime.now().isoformat()
                source = VideoSource(
                    file_name=uploaded_file.filename,
                    file_size=file_size,
                    upload_timestamp=upload_timestamp
                )
                # Form-Parameter
                interval_seconds = int(request.form.get('interval_seconds', 5))
                width = int(request.form['width']) if 'width' in request.form and request.form['width'] else None
                height = int(request.form['height']) if 'height' in request.form and request.form['height'] else None
                image_format = request.form.get('format', 'jpg')
                use_cache = (request.form.get('useCache', 'true').lower() == 'true')
            elif request.form and 'url' in request.form and request.form['url']:
                # URL per form-data
                url = request.form.get('url')
                source = VideoSource(url=url)
                interval_seconds = int(request.form.get('interval_seconds', 5))
                width = int(request.form['width']) if 'width' in request.form and request.form['width'] else None
                height = int(request.form['height']) if 'height' in request.form and request.form['height'] else None
                image_format = request.form.get('format', 'jpg')
                use_cache = (request.form.get('useCache', 'true').lower() == 'true')
            else:
                # JSON Request
                data = request.get_json() or {}
                url = data.get('url')
                if not url and not (request.files and 'file' in request.files):
                    raise ProcessingError("Entweder URL oder Datei muss angegeben werden")
                if url:
                    source = VideoSource(url=url)
                interval_seconds = int(data.get('interval_seconds', 5))
                width = int(data['width']) if 'width' in data and data['width'] is not None else None
                height = int(data['height']) if 'height' in data and data['height'] is not None else None
                image_format = data.get('format', 'jpg')
                use_cache = bool(data.get('useCache', True))

            if not source:
                raise ProcessingError("Keine gültige Video-Quelle gefunden")

            result: VideoFramesResponse = asyncio.run(process_video_frames(
                source=source,
                binary_data=binary_data,
                interval_seconds=interval_seconds,
                width=width,
                height=height,
                image_format=image_format,
                use_cache=use_cache,
                process_id=process_id
            ))

            return result.to_dict()

        except ProcessingError as e:
            logger.error(f"Verarbeitungsfehler: {str(e)}", exc_info=True)
            return {
                'status': 'error',
                'error': {
                    'code': 'PROCESSING_ERROR',
                    'message': str(e),
                    'details': getattr(e, 'details', {})
                }
            }, 400
        except Exception as e:
            logger.error("Video-Frame-Extraktion Fehler",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {
                        'error_type': type(e).__name__,
                        'traceback': traceback.format_exc()
                    }
                }
            }, 500
```

Ich führe jetzt Linter-Checks für die geänderten Dateien aus und behebe ggf. offensichtliche Typ-/Lint-Probleme, bevor ich zurückkomme.

```python
"""
Video Processor für die Verarbeitung von Video-Dateien.

LLM-Tracking Logik:
-----------------
Der VideoProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
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
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple, List
from datetime import datetime
import uuid
import hashlib
import subprocess  # Importiere subprocess für die FFmpeg-Integration
import json

import yt_dlp  # type: ignore

from src.core.config import Config
from src.core.models.base import ErrorInfo
from src.core.models.video import (
    VideoSource,
    VideoMetadata,
    VideoProcessingResult,
    VideoResponse,
    VideoFramesResult,
    VideoFramesResponse,
    FrameInfo
)
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.base import ProcessInfo
from .cacheable_processor import CacheableProcessor
from .transformer_processor import TransformerProcessor
from .audio_processor import AudioProcessor

# Typ-Alias für yt-dlp
YDLDict = Dict[str, Any]

from typing import Union as _UnionTypeAlias

VideoAnyResult = _UnionTypeAlias[VideoProcessingResult, VideoFramesResult]

class VideoProcessor(CacheableProcessor[VideoAnyResult]):
    """
    Prozessor für die Verarbeitung von Video-Dateien.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der VideoProcessor erbt von CacheableProcessor, um MongoDB-Caching zu nutzen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "video_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den VideoProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Lade Konfiguration
        config = Config()
        processor_config = config.get('processors', {})
        video_config = processor_config.get('video', {})
        
        # Video-spezifische Konfigurationen
        self.max_duration = video_config.get('max_duration', 3600)  # 1 Stunde
        
        # Debug-Logging der Video-Konfiguration
        self.logger.debug("VideoProcessor initialisiert mit Konfiguration", 
                         max_duration=self.max_duration,
                         temp_dir=str(self.temp_dir),
                         cache_dir=str(self.cache_dir))
        
        # Initialisiere Prozessoren
        self.transformer = TransformerProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Initialisiere den Transcriber mit Video-spezifischen Konfigurationen
        transcriber_config = {
            "process_id": process_id,
            "processor_name": "video",
            "cache_dir": str(self.cache_dir),  # Haupt-Cache-Verzeichnis
            "temp_dir": str(self.temp_dir),    # Temporäres Unterverzeichnis
            "debug_dir": str(self.temp_dir / "debug")
        }
        self.transcriber = WhisperTranscriber(transcriber_config, processor=self)
        
        self.audio_processor = AudioProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Download-Optionen
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'socket_timeout': 30,
            'retries': 10,
            'sleep_interval': 3,
            'max_sleep_interval': 10,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'no_playlist': True,
            'extract_flat': False,
            'youtube_include_dash_manifest': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            },
            'extractor_args': {
                'vimeo': {
                    'password': None,
                    'access_token': None
                }
            },
            'format_sort': ['ext:mp4:m4a', 'ext:webm:webma', 'ext:mp3'],
            'prefer_ffmpeg': True,
            'keepvideo': False
        }
    
    def create_process_dir(self, identifier: str, use_temp: bool = True) -> Path:
        """
        Erstellt und gibt das Verarbeitungsverzeichnis für ein Video zurück.
        
        Args:
            identifier: Eindeutige Kennung des Videos (URL, ID, etc.)
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        # Verzeichnis mit Unterordner "video" erstellen
        process_dir = base_dir / "video" / identifier
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir
        
    def _format_duration(self, seconds: int) -> str:
        """Formatiert Sekunden in ein lesbares Format (HH:MM:SS)."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _normalize_vimeo_url(self, url: str) -> str:
        """
        Konvertiert Vimeo-Player-URLs in direkte Vimeo-URLs.
        
        Args:
            url: Die ursprüngliche URL
            
        Returns:
            str: Die normalisierte Vimeo-URL
        """
        import re
        
        # Vimeo-Player-URL-Muster
        player_pattern = r'https?://player\.vimeo\.com/video/(\d+)'
        match = re.match(player_pattern, url)
        
        if match:
            video_id = match.group(1)
            normalized_url = f"https://vimeo.com/{video_id}"
            self.logger.info(f"Vimeo-Player-URL normalisiert: {url} -> {normalized_url}")
            return normalized_url
        
        # Direkte Vimeo-URL bereits korrekt
        if 'vimeo.com' in url:
            return url
            
        return url

    def _extract_video_info(self, url: str) -> Tuple[str, int, str]:
        """
        Extrahiert grundlegende Informationen aus einem Video.
        
        Args:
            url: URL des Videos
            
        Returns:
            Tuple mit (Titel, Dauer in Sekunden, Video-ID)
        """
        # URL normalisieren (besonders für Vimeo)
        normalized_url = self._normalize_vimeo_url(url)
        
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info: YDLDict = ydl.extract_info(normalized_url, download=False)  # type: ignore
            if not info:
                raise ValueError("Keine Video-Informationen gefunden")
            
            video_id = str(info.get('id', hashlib.md5(normalized_url.encode()).hexdigest()))
            title = str(info.get('title', 'Unbekanntes Video'))
            duration = int(info.get('duration', 0))
            
            return title, duration, video_id

    def _create_cache_key(self, source: Union[str, VideoSource], target_language: str = 'de', template: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf der Video-Quelle, Zielsprache und Template.
        
        Args:
            source: Die Video-Quelle (URL oder VideoSource-Objekt)
            target_language: Die Zielsprache für die Verarbeitung
            template: Optionales Template für die Verarbeitung
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Schlüssel aus der Quelle erstellen
        base_key = ""
        
        # Bei VideoSource das URL-Attribut verwenden
        if isinstance(source, VideoSource):
            if source.url:
                base_key = source.url
            elif source.file_name:
                # Bei hochgeladenen Dateien einen erweiterten Schlüssel mit mehreren Attributen erstellen
                file_info = {
                    'name': source.file_name,
                    'size': source.file_size
                }
                # Serialisieren und hashen
                base_key = hashlib.md5(json.dumps(file_info, sort_keys=True).encode()).hexdigest()
            else:
                raise ValueError("VideoSource muss entweder URL oder file_name haben")
        else:
            # Bei String direkt als URL verwenden
            base_key = source
        
        # Zielsprache hinzufügen
        cache_key = f"{base_key}|lang={target_language}"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            cache_key += f"|template={template}"
            
        self.logger.debug(f"Cache-Schlüssel erstellt: {cache_key}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(cache_key)

    def serialize_for_cache(self, result: Union[VideoProcessingResult, VideoFramesResult]) -> Dict[str, Any]:
        """
        Serialisiert das VideoProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das VideoProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern, inkl. Typ-Kennzeichnung
        result_type = "video_frames" if isinstance(result, VideoFramesResult) else "video_processing"
        cache_data = {
            "result_type": result_type,
            "result": result.to_dict(),
            "source_url": result.metadata.source.url if result.metadata.source else None,
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten aus dem Result-Objekt extrahieren
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None)
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> VideoAnyResult:
        """
        Deserialisiert die Cache-Daten zurück in ein VideoProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            VideoProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        result_type = cached_data.get("result_type", "video_processing")
        if result_type == "video_frames":
            return VideoFramesResult.from_dict(result_data)
        return VideoProcessingResult.from_dict(result_data)

    def _create_cache_key_frames(
        self,
        source: Union[str, VideoSource],
        interval_seconds: int,
        width: Optional[int],
        height: Optional[int],
        image_format: str = "jpg"
    ) -> str:
        """Erstellt Cache-Key für Frame-Extraktion."""
        if isinstance(source, VideoSource):
            base_key = source.url or (source.file_name or "uploaded_file")
        else:
            base_key = source
        size_part = f"size={width}x{height}" if width or height else "size=orig"
        key_str = f"frames|{base_key}|interval={interval_seconds}|{size_part}|fmt={image_format}"
        return self.generate_cache_key(key_str)

    async def extract_frames(
        self,
        source: Union[str, VideoSource],
        interval_seconds: int = 5,
        width: Optional[int] = None,
        height: Optional[int] = None,
        image_format: str = "jpg",
        use_cache: bool = True,
        binary_data: Optional[bytes] = None
    ) -> VideoFramesResponse:
        """Extrahiert Frames in festem Intervall und speichert sie lokal."""
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        frames_dir: Path = working_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        temp_video_path: Optional[Path] = None
        title: str = ""
        duration: int = 0
        video_id: str = ""

        try:
            # Quelle normalisieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source = source

            cache_key = self._create_cache_key_frames(video_source,
                                                      interval_seconds, width, height, image_format)
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and isinstance(cached_result, VideoFramesResult):
                    return self.create_response(
                        processor_name="video",
                        result=cached_result,
                        request_info={
                            'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                            'interval_seconds': interval_seconds,
                            'width': width,
                            'height': height,
                            'format': image_format,
                            'use_cache': use_cache
                        },
                        response_class=VideoFramesResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # Video vorbereiten (vollständiges Video, nicht nur Audio)
            if video_source.url:
                normalized_url = self._normalize_vimeo_url(video_source.url)
                with yt_dlp.YoutubeDL({
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestvideo+bestaudio/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': str(working_dir / '%(title)s.%(ext)s'),
                    'retries': 10,
                    'socket_timeout': 30,
                    'nocheckcertificate': True,
                }) as ydl:
                    info: YDLDict = ydl.extract_info(normalized_url, download=True)  # type: ignore
                    if not info:
                        raise ValueError("Keine Video-Informationen gefunden")
                    video_id = str(info.get('id'))
                    title = str(info.get('title', 'video'))
                    duration = int(info.get('duration', 0))
                # Eingangsdatei finden
                candidates = list(working_dir.glob("*.mp4")) + list(working_dir.glob("*.mkv")) + list(working_dir.glob("*.webm"))
                if not candidates:
                    raise ValueError("Heruntergeladenes Video nicht gefunden")
                temp_video_path = candidates[0]
            else:
                # Upload-Fall
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "uploaded_video"
                if not video_source.file_name or not binary_data:
                    raise ValueError("Dateiname und Binärdaten erforderlich für Upload")
                temp_video_path = working_dir / video_source.file_name
                temp_video_path.write_bytes(binary_data)

            # ffmpeg-Filterkette aufbauen
            filters: List[str] = []
            # 1 Frame alle N Sekunden
            filters.append(f"fps=1/{max(1, int(interval_seconds))}")
            # Optional skalieren
            if width or height:
                w = width if width else -1
                h = height if height else -1
                filters.append(f"scale={w}:{h}:flags=lanczos")
            filter_str = ",".join(filters)

            # Ausgabeformat und Pfad
            image_ext = image_format.lower()
            if image_ext not in {"jpg", "jpeg", "png"}:
                image_ext = "jpg"
            output_pattern = frames_dir / f"frame_%06d.{image_ext}"

            # ffmpeg ausführen
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', str(temp_video_path),
                '-vf', filter_str,
                str(output_pattern)
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)

            # erzeugte Dateien einsammeln
            files = sorted(frames_dir.glob(f"*.{image_ext}"))
            frames: List[FrameInfo] = []
            for idx, fpath in enumerate(files, start=0):
                frames.append(FrameInfo(
                    index=idx,
                    timestamp_s=float(idx * max(1, int(interval_seconds))),
                    file_path=str(fpath),
                    width=width,
                    height=height
                ))

            # Metadaten
            metadata = VideoMetadata(
                title=title or "",
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration if duration else 0),
                process_dir=str(working_dir),
                video_id=video_id
            )

            frames_result = VideoFramesResult(
                metadata=metadata,
                process_id=self.process_id,
                output_dir=str(frames_dir),
                interval_seconds=int(interval_seconds),
                frame_count=len(frames),
                frames=frames
            )

            # Optional cachen
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=frames_result)

            return self.create_response(
                processor_name="video",
                result=frames_result,
                request_info={
                    'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                    'interval_seconds': interval_seconds,
                    'width': width,
                    'height': height,
                    'format': image_format,
                    'use_cache': use_cache
                },
                response_class=VideoFramesResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error("Fehler bei der Frame-Extraktion",
                              error=e,
                              error_type=type(e).__name__)
            error_source = VideoSource()
            return self.create_response(
                processor_name="video",
                result=VideoFramesResult(
                    metadata=VideoMetadata(
                        title="Error",
                        source=error_source,
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    process_id=self.process_id,
                    output_dir=str(frames_dir),
                    interval_seconds=int(interval_seconds),
                    frame_count=0,
                    frames=[]
                ),
                request_info={
                    'source': str(source),
                    'interval_seconds': interval_seconds,
                    'width': width,
                    'height': height,
                    'format': image_format,
                    'use_cache': use_cache
                },
                response_class=VideoFramesResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_FRAME_EXTRACTION_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )
        finally:
            # temp video optional nicht löschen, da frames im selben Ordner liegen; hier keine zusätzliche Bereinigung
            pass

    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die Video-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Index für source_url
            if "source_url_1" not in index_info:
                collection.create_index([("source_url", 1)])
                self.logger.debug("source_url-Index erstellt")
            
            # Index für processed_at
            if "processed_at_1" not in index_info:
                collection.create_index([("processed_at", 1)])
                self.logger.debug("processed_at-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")

    async def process(
        self, 
        source: Union[str, VideoSource],
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None,
        use_cache: bool = True,
        binary_data: Optional[bytes] = None
    ) -> VideoResponse:
        """Verarbeitet ein Video."""
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        temp_video_path: Optional[Path] = None
        audio_path: Optional[Path] = None

        try:
            # Video-Quelle validieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source: VideoSource = source

            # Cache-Schlüssel generieren und prüfen
            cache_key = self._create_cache_key(source, target_language, template)
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Video: {cached_result.metadata.title}")
                    return self.create_response(
                        processor_name="video",
                        result=cached_result,
                        request_info={
                            'source': source.to_dict() if isinstance(source, VideoSource) and hasattr(source, 'to_dict') else str(source),
                            'source_language': source_language,
                            'target_language': target_language,
                            'template': template,
                            'use_cache': use_cache
                        },
                        response_class=VideoResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # Video-Informationen extrahieren
            if video_source.url:
                # URL normalisieren (besonders für Vimeo)
                normalized_url = self._normalize_vimeo_url(video_source.url)
                title, duration, video_id = self._extract_video_info(normalized_url)
                
                # Video herunterladen
                download_opts = self.ydl_opts.copy()
                output_path = str(working_dir / "%(title)s.%(ext)s")
                download_opts['outtmpl'] = output_path
                
                self.logger.info(f"Starte Download von: {normalized_url}")
                with yt_dlp.YoutubeDL(download_opts) as ydl:
                    ydl.download([normalized_url])  # type: ignore
            else:
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "Hochgeladenes Video"
                duration = 0
                
                if not video_source.file_name or not binary_data:
                    raise ValueError("Dateiname und Binärdaten erforderlich für Upload")
                
                # Binärdaten speichern
                temp_video_path = working_dir / video_source.file_name
                temp_video_path.write_bytes(binary_data)

                # Zu MP3 konvertieren
                if not temp_video_path.suffix.lower() == '.mp3':
                    audio_path = temp_video_path.with_suffix('.mp3')
                    cmd = [
                        'ffmpeg', '-i', str(temp_video_path),
                        '-vn', '-acodec', 'libmp3lame',
                        '-q:a', '4', '-y', str(audio_path)
                    ]
                    subprocess.run(cmd, check=True, capture_output=True, text=True)

            # MP3-Datei finden wenn nicht schon gesetzt
            if not audio_path:
                mp3_files = list(working_dir.glob("*.mp3"))
                if not mp3_files:
                    raise ValueError("Keine MP3-Datei gefunden")
                audio_path = mp3_files[0]

            # Dauer prüfen
            if duration > self.max_duration:
                raise ValueError(f"Video zu lang: {duration} Sekunden (Maximum: {self.max_duration} Sekunden)")

            # Audio verarbeiten
            self.logger.info("Starte Audio-Verarbeitung")
            audio_response = await self.audio_processor.process(
                audio_source=str(audio_path),
                source_info={
                    'original_filename': title,
                    'video_id': video_id
                },
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache
            )

            # Erkannte Quellsprache aktualisieren
            if audio_response.data and audio_response.data.transcription:
                if source_language == 'auto':
                    source_language = audio_response.data.transcription.source_language

            # Metadaten erstellen
            metadata = VideoMetadata(
                title=title,
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration),
                file_size=audio_path.stat().st_size if audio_path else None,
                process_dir=str(working_dir),
                audio_file=str(audio_path) if audio_path else None
            )

            # Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=metadata,
                transcription=audio_response.data.transcription if audio_response.data else None,
                process_id=self.process_id
            )

            # Im Cache speichern
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=result)

            # Response erstellen
            return self.create_response(
                processor_name="video",
                result=result,
                request_info={
                    'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=VideoResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error("Fehler bei der Video-Verarbeitung",
                            error=e,
                            error_type=type(e).__name__)

            # Erstelle eine standardmäßige VideoSource für den Fehlerfall
            error_source = VideoSource()
            
            # Einfache String-Repräsentation des Quellobjekts
            source_repr = str(source)

            return self.create_response(
                processor_name="video",
                result=VideoProcessingResult(
                    metadata=VideoMetadata(
                        title="Error",
                        source=error_source,
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    transcription=None,
                    process_id=self.process_id
                ),
                request_info={
                    'source': source_repr,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=VideoResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_PROCESSING_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )

        finally:
            # Aufräumen
            if temp_video_path and temp_video_path.exists():
                try:
                    temp_video_path.unlink()
                    self.logger.debug(f"Temporäre Videodatei gelöscht: {temp_video_path}")
                except Exception as cleanup_error:
                    self.logger.warning(f"Konnte temporäre Datei nicht löschen: {cleanup_error}") 
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_dict: Dict[str, Any] = audio_result_dict
                audio_result = AudioProcessingResult.from_dict(typed_dict)
            except:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription: Dict[str, Any] = dict(transcription_dict)
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

from typing import List

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        return cls(
            metadata=VideoMetadata.from_dict(data['metadata']) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=[FrameInfo.from_dict(fd) for fd in data.get('frames', []) if isinstance(fd, dict)],
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_audio: Dict[str, Any] = dict(audio_result_dict)
                audio_result = AudioProcessingResult.from_dict(typed_audio)
            except Exception:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription: Dict[str, Any] = dict(transcription_dict)
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

from typing import List

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        return cls(
            metadata=VideoMetadata.from_dict(data['metadata']) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=[FrameInfo.from_dict(fd) for fd in data.get('frames', []) if isinstance(fd, dict)],
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_audio: Dict[str, Any] = {str(k): v for k, v in audio_result_dict.items()}
                audio_result = AudioProcessingResult.from_dict(typed_audio)
            except Exception:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription: Dict[str, Any] = {str(k): v for k, v in transcription_dict.items()}
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

from typing import List

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        return cls(
            metadata=VideoMetadata.from_dict(data['metadata']) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=[FrameInfo.from_dict(fd) for fd in data.get('frames', []) if isinstance(fd, dict)],
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_audio: Dict[str, Any] = {str(k): v for k, v in audio_result_dict.items()}
                audio_result = AudioProcessingResult.from_dict(typed_audio)
            except Exception:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription: Dict[str, Any] = {str(k): v for k, v in transcription_dict.items()}
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

from typing import List

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        metadata_val: VideoMetadata = VideoMetadata.from_dict(data['metadata']) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            )
        frames_list_raw = data.get('frames', [])
        frames_typed: List[FrameInfo] = [FrameInfo.from_dict(fd) for fd in frames_list_raw if isinstance(fd, dict)]
        return cls(
            metadata=metadata_val,
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=frames_typed,
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol, cast, List

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_audio: Dict[str, Any] = {str(k): v for k, v in audio_result_dict.items()}
                audio_result = AudioProcessingResult.from_dict(typed_audio)
            except Exception:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription: Dict[str, Any] = {str(k): v for k, v in transcription_dict.items()}
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        metadata_val: VideoMetadata = VideoMetadata.from_dict(data['metadata']) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            )
        frames_list_raw = data.get('frames', [])
        frames_typed: List[FrameInfo] = [FrameInfo.from_dict(fd) for fd in frames_list_raw if isinstance(fd, dict)]
        return cls(
            metadata=metadata_val,
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=frames_typed,
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol, cast, List

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_audio_items: List[tuple[str, Any]] = [(str(k), v) for k, v in audio_result_dict.items()]
                typed_audio: Dict[str, Any] = dict(typed_audio_items)
                audio_result = AudioProcessingResult.from_dict(typed_audio)
            except Exception:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription_items: List[tuple[str, Any]] = [(str(k), v) for k, v in transcription_dict.items()]
                typed_transcription: Dict[str, Any] = dict(typed_transcription_items)
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        metadata_val: VideoMetadata = VideoMetadata.from_dict(cast(Dict[str, Any], data['metadata'])) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            )
        frames_list_raw: List[Any] = cast(List[Any], data.get('frames', []))
        frames_typed: List[FrameInfo] = [FrameInfo.from_dict(cast(Dict[str, Any], fd)) for fd in frames_list_raw if isinstance(fd, dict)]
        return cls(
            metadata=metadata_val,
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=frames_typed,
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

```python
"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol, cast, List

from .base import BaseResponse, ProcessingStatus, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from ..exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableResult

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    upload_timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'upload_timestamp': self.upload_timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name'),
            file_size=data.get('file_size'),
            upload_timestamp=data.get('upload_timestamp')
        )

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult(CacheableResult):
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        process_id (str): ID des Verarbeitungsprozesses
        audio_result (Optional[Any]): Ergebnis der Audio-Verarbeitung
        transcription (Optional[Any]): Transkriptionsergebnis
    """
    metadata: VideoMetadata
    process_id: str
    audio_result: Optional[Any] = None
    transcription: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_audio: Dict[str, Any] = {}
                for key, value in cast(Dict[Any, Any], audio_result_dict).items():
                    typed_audio[str(key)] = value
                audio_result = AudioProcessingResult.from_dict(typed_audio)
            except Exception:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_transcription: Dict[str, Any] = {}
                for key, value in cast(Dict[Any, Any], transcription_dict).items():
                    typed_transcription[str(key)] = value
                transcription = TranscriptionResult.from_dict(typed_transcription)
            except Exception:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: Optional[VideoProcessingResult] = field(default=None)

    def __init__(
        self,
        data: VideoProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoResponse':
        """Erstellt eine Error-Response."""
        empty_result = VideoProcessingResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 

# Neue Modelle für Frame-Extraktion

@dataclass
class FrameInfo:
    """Informationen zu einem extrahierten Frame."""
    index: int
    timestamp_s: float
    file_path: str
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'timestamp_s': self.timestamp_s,
            'file_path': self.file_path,
            'width': self.width,
            'height': self.height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FrameInfo':
        return cls(
            index=int(data.get('index', 0)),
            timestamp_s=float(data.get('timestamp_s', 0.0)),
            file_path=str(data.get('file_path', '')),
            width=data.get('width'),
            height=data.get('height'),
        )

@dataclass
class VideoFramesResult(CacheableResult):
    """Ergebnis der Frame-Extraktion aus einem Video."""
    metadata: VideoMetadata
    process_id: str
    output_dir: str
    interval_seconds: int
    frame_count: int
    frames: List[FrameInfo] = field(default_factory=list)

    @property
    def status(self) -> ProcessingStatus:
        # Erfolgreich, wenn mindestens ein Frame erzeugt wurde
        return ProcessingStatus.SUCCESS if self.frame_count > 0 else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        return {
            'metadata': self.metadata.to_dict(),
            'process_id': self.process_id,
            'output_dir': self.output_dir,
            'interval_seconds': self.interval_seconds,
            'frame_count': self.frame_count,
            'frames': [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoFramesResult':
        metadata_val: VideoMetadata = VideoMetadata.from_dict(cast(Dict[str, Any], data['metadata'])) if 'metadata' in data else VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            )
        frames_list_raw: List[Any] = cast(List[Any], data.get('frames', []))
        frames_typed: List[FrameInfo] = [FrameInfo.from_dict(cast(Dict[str, Any], fd)) for fd in frames_list_raw if isinstance(fd, dict)]
        return cls(
            metadata=metadata_val,
            process_id=str(data.get('process_id', '')),
            output_dir=str(data.get('output_dir', '')),
            interval_seconds=int(data.get('interval_seconds', 0)),
            frame_count=int(data.get('frame_count', 0)),
            frames=frames_typed,
        )

@dataclass(frozen=True, init=False)
class VideoFramesResponse(BaseResponse):
    """Standardisierte API-Response für Video-Frame-Extraktion."""
    data: Optional[VideoFramesResult] = field(default=None)

    def __init__(
        self,
        data: VideoFramesResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[VideoFramesResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'VideoFramesResponse':
        empty_result = VideoFramesResult(
            metadata=VideoMetadata(
                title="",
                source=VideoSource(),
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id="",
            output_dir="",
            interval_seconds=0,
            frame_count=0,
            frames=[],
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

Kurzer Plan: Ich habe eine einfache Frame-Extraktion implementiert, analog zur Seitenverarbeitung bei PDFs: neuer Ergebnis-/Response-Typ, neue Methode im `VideoProcessor` für Frame-Extraktion (ffmpeg), plus ein eigener API-Endpoint in `video_routes.py`. Frames werden lokal gespeichert, Parameter wie Intervall und Größe sind steuerbar. Linter ist sauber.

### Was ist neu
- In `src/core/models/video.py`
  - Neue Dataclasses: `FrameInfo`, `VideoFramesResult`, `VideoFramesResponse`.
- In `src/processors/video_processor.py`
  - Neue Methode `extract_frames(...)` mit ffmpeg (`fps=1/N`, optionaler `scale`).
  - Cache-Unterstützung inkl. Typ-Kennzeichnung (`result_type`).
- In `src/api/routes/video_routes.py`
  - Neuer Endpoint `POST /video/frames` (JSON und multipart/form-data).
  - Parameter: `interval_seconds`, `width`, `height`, `format` (jpg/png), `useCache`.

### Wie funktioniert es
- Quelle per URL oder Datei-Upload.
- Alle N Sekunden wird ein Frame extrahiert und als `frame_000001.jpg` etc. in ein lokales Verzeichnis geschrieben.
- Antwort enthält u. a.:
  - `data.output_dir`: Verzeichnis mit allen Bildern
  - `data.frame_count`: Anzahl erzeugter Frames
  - `data.frames[]`: Liste mit Pfaden und Zeitstempeln

### API verwenden
- JSON (YouTube/Vimeo/Datei-URL):
```bash
curl -X POST "http://localhost:5000/video/frames" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "interval_seconds": 5,
    "width": 1280,
    "height": 720,
    "format": "jpg",
    "useCache": true
  }'
```

- Multipart (Datei-Upload):
```bash
curl -X POST "http://localhost:5000/video/frames" \
  -F "file=@C:/path/zum/video.mp4" \
  -F "interval_seconds=5" \
  -F "width=1280" \
  -F "height=720" \
  -F "format=png" \
  -F "useCache=true"
```

- Hinweise:
  - `interval_seconds`: minimal 1 Sekunde.
  - `width`/`height` optional; fehlender Wert = Seitenverhältnis beibehalten.
  - `format`: `jpg` (Default) oder `png`.

### Abhängigkeiten
- ffmpeg muss installiert und im PATH verfügbar sein.
  - Windows: `choco install ffmpeg` oder Download von `ffmpeg.org`, dann PATH setzen.
  - Test: `ffmpeg -version`.

### Start & Test
- Server starten:
```powershell
venv\Scripts\activate; $env:PYTHONPATH = "."; python src/main.py
```
- Beispiel-Request senden (s. oben).
- Prüfen:
  - Response enthält `data.output_dir` und `data.frame_count > 0`.
  - Bilder liegen lokal unter dem angegebenen Ordner (z. B. `cache/video/temp/video/<uuid>/frames`).

### Caching
- Cache-Key berücksichtigt Quelle, `interval_seconds`, `width`/`height` und `format`.
- `useCache=false` erzwingt Neuverarbeitung.

### Varianten (falls du später umbauen willst)
- ffmpeg (aktuell): sehr performant, wenig Code.
- OpenCV: feineres Timing, aber schwerer bei exotischen Codecs.
- moviepy: Pythonic, aber langsamer und mehr Dependencies.

Status: Edits in `video.py`, `video_processor.py`, `video_routes.py` implementiert; Linter fehlerfrei für diese Dateien.

- Neues Feature: Video → Bilder als eigener Endpoint `/video/frames` mit Intervall und Größe.
- Verarbeitung nutzt ffmpeg; Bilder werden lokal gespeichert; Pfad in `data.output_dir`.
- Cache für Frames integriert; Linter geprüft (clean).

```shellscript
curl -X POST "http://localhost:5000/video/frames" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "interval_seconds": 5,
    "width": 1280,
    "height": 720,
    "format": "jpg",
    "useCache": true
  }'
```

```shellscript
curl -X POST "http://localhost:5000/video/frames" \
  -F "file=@C:/path/zum/video.mp4" \
  -F "interval_seconds=5" \
  -F "width=1280" \
  -F "height=720" \
  -F "format=png" \
  -F "useCache=true"
```

```powershell
venv\Scripts\activate; $env:PYTHONPATH = "."; python src/main.py
```

