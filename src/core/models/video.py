"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any

from .base import BaseResponse, ProcessingStatus, RequestInfo, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from .llm import LLMInfo
from ..exceptions import ProcessingError

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
    file: Optional[bytes] = None
    file_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name
            # file wird nicht serialisiert
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name')
        )

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
class VideoProcessingResult:
    """Ergebnis der Video-Verarbeitung"""
    metadata: VideoMetadata
    transcription: Optional[TranscriptionResult] = None
    process_id: Optional[str] = None
    is_from_cache: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'metadata': self.metadata.to_dict(),
            'transcription': self.transcription.to_dict() if self.transcription else None,
            'process_id': self.process_id,
            'is_from_cache': self.is_from_cache
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt aus Dict"""
        transcription = None
        if data.get('transcription'):
            # Einfache Konstruktion des TranscriptionResult
            trans_data = data['transcription']
            transcription = TranscriptionResult(
                text=trans_data['text'],
                source_language=trans_data['source_language']
            )
            
        return cls(
            metadata=VideoMetadata.from_dict(data['metadata']),
            transcription=transcription,
            process_id=data.get('process_id'),
            is_from_cache=data.get('is_from_cache', False)
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: VideoProcessingResult

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: VideoProcessingResult,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)

    @classmethod
    def create(cls, request: RequestInfo, process: ProcessInfo, data: VideoProcessingResult,
               llm_info: Optional[LLMInfo] = None) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if llm_info:
            process.llm_info = llm_info
        return cls(
            data=data,
            request=request,
            process=process,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error: ErrorInfo) -> 'VideoResponse':
        """Erstellt eine Fehler-Response."""
        dummy_source = VideoSource(url="")
        dummy_metadata = VideoMetadata(
            title="",
            source=dummy_source,
            duration=0,
            duration_formatted="00:00:00",
            process_dir=""
        )
        dummy_result = VideoProcessingResult(
            metadata=dummy_metadata,
            transcription=None,
            process_id=""
        )
        return cls(
            data=dummy_result,
            request=request,
            process=process,
            error=error,
            status=ProcessingStatus.ERROR
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict 