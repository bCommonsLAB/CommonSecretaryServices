"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union
from pathlib import Path
from datetime import datetime

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

@dataclass(frozen=True)
class VideoSource:
    """Quelle des zu verarbeitenden Videos."""
    url: Optional[str] = None
    file: Optional[Union[Path, bytes]] = None
    file_name: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Quelle."""
        if not self.url and not self.file:
            raise ValueError("Entweder URL oder File muss angegeben werden")
        if self.file and not self.file_name:
            raise ValueError("Bei File-Upload muss ein Dateiname angegeben werden")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Quelle in ein Dictionary."""
        return {
            "url": self.url,
            "file": str(self.file) if isinstance(self.file, Path) else bool(self.file),
            "file_name": self.file_name
        }

@dataclass(frozen=True)
class VideoMetadata:
    """Metadaten des verarbeiteten Videos."""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    process_dir: str
    file_size: Optional[int] = None
    audio_file: Optional[str] = None
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    modified: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self) -> None:
        """Validiert die Metadaten."""
        if not self.title.strip():
            raise ValueError("title darf nicht leer sein")
        if self.duration < 0:
            raise ValueError("duration muss positiv sein")
        if not self.duration_formatted.strip():
            raise ValueError("duration_formatted darf nicht leer sein")
        if not self.process_dir.strip():
            raise ValueError("process_dir darf nicht leer sein")
        if self.file_size is not None and self.file_size <= 0:
            raise ValueError("file_size muss positiv sein wenn gesetzt")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            "title": self.title,
            "source": self.source.to_dict(),
            "duration": self.duration,
            "duration_formatted": self.duration_formatted,
            "file_size": self.file_size,
            "process_dir": self.process_dir,
            "audio_file": self.audio_file,
            "created": self.created,
            "modified": self.modified
        }

@dataclass(frozen=True)
class VideoProcessingResult:
    """Ergebnis der Video-Verarbeitung."""
    metadata: VideoMetadata
    transcription: Optional[TranscriptionResult]
    process_id: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "metadata": self.metadata.to_dict(),
            "transcription": self.transcription.to_dict() if self.transcription else None,
            "process_id": self.process_id
        }

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
            process.llm_info = llm_info.to_dict()
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