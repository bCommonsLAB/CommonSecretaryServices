"""
Audio-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .base import BaseResponse, ProcessingStatus, RequestInfo, ProcessInfo, ErrorInfo
from .llm import LLModel, LLMInfo
from .enums import ProcessingStatus
from ..exceptions import ProcessingError

class AudioProcessingError(ProcessingError):
    """Audio-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'SEGMENT_ERROR': 'Fehler bei der Segmentierung',
        'CACHE_ERROR': 'Fehler beim Cache-Management'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'AUDIO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'AUDIO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class TranscriptionSegment:
    """Ein Segment einer Transkription"""
    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        """Validiert die Segment-Daten."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence muss zwischen 0 und 1 liegen")

@dataclass
class TranscriptionResult:
    """Ergebnis einer Transkription"""
    text: str
    detected_language: str
    segments: List[TranscriptionSegment]
    llms: List[LLModel] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert das Transkriptionsergebnis."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if not self.detected_language.strip():
            raise ValueError("Detected language darf nicht leer sein")
        if not self.segments:
            raise ValueError("Segments darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'text': self.text,
            'detected_language': self.detected_language,
            'segments': [
                {
                    'text': s.text,
                    'start': s.start,
                    'end': s.end,
                    'speaker': s.speaker,
                    'confidence': s.confidence
                }
                for s in self.segments
            ],
            'llms': [
                {
                    'model': llm.model,
                    'duration': llm.duration,
                    'tokens': llm.tokens
                }
                for llm in self.llms
            ]
        }

@dataclass
class AudioSegmentInfo:
    """Informationen über ein Audio-Segment"""
    start: float  # Start in Sekunden
    end: float    # Ende in Sekunden
    duration: float
    title: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Segment-Informationen."""
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.duration <= 0:
            raise ValueError("Duration muss positiv sein")
        if self.title is not None and not self.title.strip():
            raise ValueError("Title darf nicht leer sein wenn gesetzt")

@dataclass
class Chapter:
    """Ein Kapitel in der Audio-Datei"""
    title: str
    start: float
    end: float
    segments: List[AudioSegmentInfo] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert die Kapitel-Informationen."""
        if not self.title.strip():
            raise ValueError("Title darf nicht leer sein")
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")

@dataclass
class AudioMetadata:
    """Metadaten einer Audio-Datei"""
    title: str
    duration: float
    format: str
    channels: int
    sample_rate: int
    bit_rate: int
    chapters: List[Chapter] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert die Metadaten."""
        if not self.title.strip():
            raise ValueError("Title darf nicht leer sein")
        if self.duration <= 0:
            raise ValueError("Duration muss positiv sein")
        if not self.format.strip():
            raise ValueError("Format darf nicht leer sein")
        if self.channels <= 0:
            raise ValueError("Channels muss positiv sein")
        if self.sample_rate <= 0:
            raise ValueError("Sample rate muss positiv sein")
        if self.bit_rate <= 0:
            raise ValueError("Bit rate muss positiv sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'title': self.title,
            'duration': self.duration,
            'format': self.format,
            'channels': self.channels,
            'sample_rate': self.sample_rate,
            'bit_rate': self.bit_rate,
            'chapters': [
                {
                    'title': c.title,
                    'start': c.start,
                    'end': c.end,
                    'segments': [
                        {
                            'start': s.start,
                            'end': s.end,
                            'duration': s.duration,
                            'title': s.title
                        }
                        for s in c.segments
                    ]
                }
                for c in self.chapters
            ]
        }

@dataclass
class AudioProcessingResult:
    """Ergebnis der Audio-Verarbeitung."""
    transcription: Optional[TranscriptionResult]
    metadata: Optional[AudioMetadata]
    process_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "transcription": self.transcription.to_dict() if self.transcription else None,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "process_id": self.process_id
        }

@dataclass(frozen=True, init=False)
class AudioResponse(BaseResponse):
    """Standardisierte Response für Audio-Verarbeitung."""
    data: AudioProcessingResult
    llm_info: Optional[LLMInfo] = None
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: AudioProcessingResult,
        llm_info: Optional[LLMInfo] = None,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die AudioResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'llm_info', llm_info)

    @classmethod
    def create(cls, request: RequestInfo, process: ProcessInfo, data: AudioProcessingResult,
               llm_info: Optional[LLMInfo] = None) -> 'AudioResponse':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            request=request,
            process=process,
            data=data,
            llm_info=llm_info,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error: ErrorInfo) -> 'AudioResponse':
        """Erstellt eine Fehler-Response."""
        return cls(
            request=request,
            process=process,
            data=AudioProcessingResult(
                transcription=None,
                metadata=None,
                process_id=""
            ),
            error=error,
            status=ProcessingStatus.ERROR
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = {
            'status': self.status.value,
            'request': self.request.to_dict() if self.request else None,
            'process': self.process.to_dict() if self.process else None,
            'error': self.error.to_dict() if self.error else None,
            'data': self.data.to_dict() if self.data else None
        }
        return base_dict 