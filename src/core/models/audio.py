"""
Audio-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union, Protocol
from pathlib import Path
import io

from .base import BaseResponse, ProcessInfo, ErrorInfo
from .llm import LLMInfo
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

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Segment in ein Dictionary."""
        return {
            "text": self.text,
            "segment_id": self.segment_id,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "confidence": self.confidence,
            "title": self.title
        }

@dataclass
class TranscriptionResult:
    """Ein Transkriptionsergebnis mit Text, Sprache und Segmenten."""
    text: str
    source_language: str
    segments: List[TranscriptionSegment] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert das Transkriptionsergebnis."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if not self.source_language.strip():
            raise ValueError("Source language darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "text": self.text,
            "source_language": self.source_language,
            "segments": [s.to_dict() for s in self.segments] if self.segments else []
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TranscriptionResult':
        """Erstellt ein TranscriptionResult aus einem Dictionary."""
        segments: List[TranscriptionSegment] = [
            TranscriptionSegment(**s) for s in data.get('segments', [])
        ]
        
        return cls(
            text=data['text'],
            source_language=data['source_language'],
            segments=segments
        )

@dataclass
class AudioSegmentInfo:
    """Informationen über ein Audio-Segment"""
    file_path: Union[Path, io.BytesIO]  # Pfad zur Audio-Datei oder BytesIO Objekt
    start: float  # Start in Sekunden
    end: float    # Ende in Sekunden
    duration: float
    size_bytes: Optional[int] = None  # Größe des Segments in Bytes
    title: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Segment-Informationen."""
        if isinstance(self.file_path, (str, Path)):
            self.file_path = Path(self.file_path)
            return
        if not hasattr(self.file_path, 'seek'):
            raise ValueError("file_path muss ein Path oder BytesIO Objekt sein")
            
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.duration <= 0:
            raise ValueError("Duration muss positiv sein")
        if self.size_bytes is not None and self.size_bytes <= 0:
            raise ValueError("size_bytes muss positiv sein wenn gesetzt")
            
    def get_audio_data(self) -> Union[Path, bytes]:
        """Gibt die Audio-Daten zurück."""
        if isinstance(self.file_path, io.BytesIO):
            self.file_path.seek(0)
            return self.file_path.getvalue()
        return self.file_path

@dataclass
class Chapter:
    """Ein Kapitel in der Audio-Datei"""
    title: str
    start: float
    end: float
    segments: List[AudioSegmentInfo] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert die Kapitel-Informationen."""
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")

class AudioMetadataProtocol(Protocol):
    """Protocol für die AudioMetadata-Klasse und ihre dynamischen Attribute."""
    duration: float
    duration_formatted: str
    file_size: int
    sample_rate: int
    channels: int
    bits_per_sample: int
    format: str
    codec: str
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_path: Optional[str]
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]
    original_filename: Optional[str]
    video_id: Optional[str]
    filename: Optional[str]

@dataclass
class AudioMetadata:
    """Metadaten einer Audio-Datei"""
    duration: float
    process_dir: str
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
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioMetadata':
        """Erstellt ein AudioMetadata-Objekt aus einem Dictionary.
        
        Args:
            data: Dictionary mit den Metadaten
            
        Returns:
            AudioMetadata: Das erstellte AudioMetadata-Objekt
        """
        # Erstelle Chapters aus den Daten, falls vorhanden
        chapters: List[Chapter] = []
        for chapter_data in data.get('chapters', []):
            segments: List[AudioSegmentInfo] = []
            for segment_data in chapter_data.get('segments', []):
                # Erstelle ein AudioSegmentInfo für jedes Segment
                segments.append(AudioSegmentInfo(
                    file_path=Path(""),  # Leerer Pfad, da wir keine Dateien haben
                    start=segment_data.get('start', 0.0),
                    end=segment_data.get('end', 0.0),
                    duration=segment_data.get('duration', 0.0),
                    title=segment_data.get('title')
                ))
            
            # Erstelle ein Chapter mit den Segmenten
            chapters.append(Chapter(
                title=chapter_data.get('title', ''),
                start=chapter_data.get('start', 0.0),
                end=chapter_data.get('end', 0.0),
                segments=segments
            ))
        
        # Erstelle das AudioMetadata-Objekt
        return cls(
            title=data.get('title', 'Unbekannt'),
            duration=data.get('duration', 0.0),
            format=data.get('format', 'mp3'),
            channels=data.get('channels', 2),
            sample_rate=data.get('sample_rate', 44100),
            bit_rate=data.get('bit_rate', 128000),
            process_dir=data.get('process_dir', ''),
            chapters=chapters
        )

@dataclass(frozen=True)
class AudioProcessingResult:
    """Ergebnis der Audio-Verarbeitung."""
    transcription: TranscriptionResult
    metadata: AudioMetadata
    process_id: Optional[str] = None
    transformation_result: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription and self.transcription.text else ProcessingStatus.ERROR

    def __post_init__(self) -> None:
        """Initialisiert das AudioProcessingResult."""
        if not self.transcription:
            raise ValueError("Transcription darf nicht None sein")
        if not self.metadata:
            raise ValueError("Metadata darf nicht None sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'transcription': self.transcription.to_dict() if self.transcription else None,
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'transformation_result': self.transformation_result,
            'status': self.status.value
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioProcessingResult':
        """Erstellt ein AudioProcessingResult aus einem Dictionary."""
        return cls(
            transcription=TranscriptionResult.from_dict(data.get('transcription', {})) if data.get('transcription') else TranscriptionResult(text="", source_language="unknown"),
            metadata=AudioMetadata.from_dict(data.get('metadata', {})) if data.get('metadata') else AudioMetadata(duration=0.0, process_dir="", format="unknown", channels=0),
            process_id=data.get('process_id'),
            transformation_result=data.get('transformation_result')
        )

@dataclass(frozen=True, init=False)
class AudioResponse(BaseResponse):
    """Standardisierte Response für Audio-Verarbeitung."""
    data: Optional[AudioProcessingResult] = field(default=None)

    def __init__(
        self,
        data: AudioProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die AudioResponse."""
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
        data: Optional[AudioProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'AudioResponse':
        """Erstellt eine erfolgreiche Response.
        
        Args:
            data: Die Verarbeitungsergebnisse
            process: Optionale ProcessInfo mit LLM-Tracking
            **kwargs: Weitere Parameter für die Response
            
        Returns:
            AudioResponse: Die erstellte Response
            
        Raises:
            ValueError: Wenn data None ist
        """
        if data is None:
            raise ValueError("data must not be None")
            
        # Erstelle Response mit ProcessInfo
        response = cls(
            data=data,
            process=process,
            **kwargs
        )
        
        # Setze Status auf SUCCESS
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'AudioResponse':
        """Erstellt eine Error-Response.
        
        Args:
            error: Die Fehlerinformationen
            process: Optionale ProcessInfo mit LLM-Tracking
            **kwargs: Weitere Parameter für die Response
            
        Returns:
            AudioResponse: Die Error-Response
        """
        # Erstelle leeres Result für Error-Response
        empty_result = AudioProcessingResult(
            transcription=TranscriptionResult(
                text="",
                source_language="unknown"
            ),
            metadata=AudioMetadata(
                duration=0.0,
                process_dir="",
                format="unknown",
                channels=0
            )
        )
        
        # Erstelle Response mit Error
        response = cls(
            data=empty_result,
            process=process,
            **kwargs
        )
        
        # Setze Status und Error
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        
        return response

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

@dataclass
class AudioProcessingRequest:
    """Request-Daten für die Audio-Verarbeitung."""
    source: str
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    template: Optional[str] = None
    original_filename: Optional[str] = None
    video_id: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert die Request-Daten."""
        if not self.source:
            raise ValueError("Source darf nicht leer sein")

@dataclass
class AudioProcessingProcess:
    """Process-Daten für die Audio-Verarbeitung."""
    elapsed_time: int  # in Millisekunden
    llm_info: Optional[LLMInfo] = None
