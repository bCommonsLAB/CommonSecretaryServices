"""
Audio-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Sequence
from .base import BaseResponse, ProcessingStatus, RequestInfo, ProcessInfo, ErrorInfo
from .llm import LLModel, LLMInfo
from .enums import ProcessingStatus
from ..exceptions import ProcessingError
from pathlib import Path

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
    segment_id: int
    start: float
    end: float
    speaker: Optional[str] = None
    confidence: float = 1.0
    title: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Segment-Daten."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if self.segment_id < 0:
            raise ValueError("Segment ID muss positiv sein")
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence muss zwischen 0 und 1 liegen")
        if self.title is not None and not self.title.strip():
            raise ValueError("Title darf nicht leer sein wenn gesetzt")

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
                    'segment_id': s.segment_id,
                    'start': s.start,
                    'end': s.end,
                    'speaker': s.speaker,
                    'confidence': s.confidence,
                    'title': s.title
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
    file_path: Path  # Pfad zur Audio-Datei
    start: float  # Start in Sekunden
    end: float    # Ende in Sekunden
    duration: float
    title: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Segment-Informationen."""
        if not isinstance(self.file_path, Path):
            self.file_path = Path(self.file_path)
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
    duration: float
    process_dir: str
    args: Dict[str, Any]
    title: str = "Unbekannt"
    format: str = "mp3"
    channels: int = 2
    sample_rate: int = 44100
    bit_rate: int = 128000
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
            'process_dir': self.process_dir,
            'args': self.args,
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
    transcription: TranscriptionResult
    metadata: AudioMetadata
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

@dataclass
class WhisperSegment:
    """Ein Segment aus der Whisper API."""
    text: str
    start: float
    end: float
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
class WhisperResponse:
    """Response von der Whisper API."""
    text: str
    language: str
    duration: float
    segments: List[WhisperSegment]
    task: str = "transcribe"
    
    def __post_init__(self) -> None:
        """Validiert die Response-Daten."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if not self.language.strip():
            raise ValueError("Language darf nicht leer sein")
        if self.duration <= 0:
            raise ValueError("Duration muss positiv sein")
        if not self.segments:
            raise ValueError("Segments darf nicht leer sein")
        if not self.task in ["transcribe", "translate"]:
            raise ValueError("Task muss 'transcribe' oder 'translate' sein")
            
    @classmethod
    def from_api_response(cls, response: Dict[str, Any]) -> 'WhisperResponse':
        """Erstellt eine WhisperResponse aus der API-Antwort."""
        segments = [
            WhisperSegment(
                text=seg.get('text', ''),
                start=seg.get('start', 0.0),
                end=seg.get('end', 0.0),
                confidence=seg.get('confidence', 1.0)
            )
            for seg in response.get('segments', [])
        ]
        
        return cls(
            text=response.get('text', ''),
            language=response.get('language', ''),
            duration=response.get('duration', 0.0),
            segments=segments,
            task=response.get('task', 'transcribe')
        )

@dataclass
class AudioTranscriptionParams:
    """Parameter für die Audio-Transkription."""
    model: str = "whisper-1"
    language: Optional[str] = None
    response_format: str = "verbose_json"
    temperature: float = 0.0
    
    def __post_init__(self) -> None:
        """Validiert die Parameter."""
        if not self.model.strip():
            raise ValueError("Model darf nicht leer sein")
        if self.language is not None and not self.language.strip():
            raise ValueError("Language darf nicht leer sein wenn gesetzt")
        if not self.response_format in ["json", "text", "srt", "verbose_json", "vtt"]:
            raise ValueError("Response format muss einer der folgenden Werte sein: json, text, srt, verbose_json, vtt")
        if self.temperature < 0 or self.temperature > 1:
            raise ValueError("Temperature muss zwischen 0 und 1 liegen")
            
    def to_api_params(self) -> Dict[str, Any]:
        """Konvertiert die Parameter in ein Dictionary für die API."""
        params = {
            "model": self.model,
            "response_format": self.response_format,
            "temperature": self.temperature
        }
        if self.language:
            params["language"] = self.language
        return params 