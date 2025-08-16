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