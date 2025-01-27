"""
Audio-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from .base import BaseResponse, RequestInfo, ProcessInfo, ErrorInfo
from .enums import ProcessingStatus
from .llm import LLModel

@dataclass
class TranscriptionSegment:
    """Ein Segment einer Transkription"""
    text: str
    start: float
    end: float
    speaker: Optional[str] = None
    confidence: float = 1.0

@dataclass
class TranscriptionResult:
    """Ergebnis einer Transkription"""
    text: str
    detected_language: str
    segments: List[TranscriptionSegment]
    llms: List[LLModel] = field(default_factory=list)

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
            ]
        }

@dataclass
class AudioSegmentInfo:
    """Informationen über ein Audio-Segment"""
    start: float  # Start in Sekunden
    end: float    # Ende in Sekunden
    duration: float
    title: Optional[str] = None

@dataclass
class Chapter:
    """Ein Kapitel in der Audio-Datei"""
    title: str
    start: float
    end: float
    segments: List[AudioSegmentInfo] = field(default_factory=list)

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

@dataclass(frozen=True, init=False)
class AudioProcessingResult(BaseResponse):
    """Ergebnis der Audio-Verarbeitung"""
    metadata: AudioMetadata
    transcription: TranscriptionResult
    llm_model: Optional[LLModel] = None
    translation_model: Optional[LLModel] = None

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        metadata: AudioMetadata,
        transcription: TranscriptionResult,
        llm_model: Optional[LLModel] = None,
        translation_model: Optional[LLModel] = None,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert das AudioProcessingResult."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'metadata', metadata)
        object.__setattr__(self, 'transcription', transcription)
        object.__setattr__(self, 'llm_model', llm_model)
        object.__setattr__(self, 'translation_model', translation_model)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        segments = [
            {
                'text': segment.text,
                'start': segment.start,
                'end': segment.end,
                'speaker': segment.speaker,
                'confidence': segment.confidence
            }
            for segment in self.transcription.segments
        ]

        return {
            'metadata': {
                'title': self.metadata.title,
                'duration': self.metadata.duration,
                'format': self.metadata.format,
                'channels': self.metadata.channels,
                'sample_rate': self.metadata.sample_rate,
                'bit_rate': self.metadata.bit_rate,
                'chapters': [
                    {
                        'title': chapter.title,
                        'start': chapter.start,
                        'end': chapter.end,
                        'segments': [
                            {
                                'start': segment.start,
                                'end': segment.end,
                                'duration': segment.duration,
                                'title': segment.title
                            }
                            for segment in chapter.segments
                        ]
                    }
                    for chapter in self.metadata.chapters
                ]
            },
            'transcription': {
                'text': self.transcription.text,
                'detected_language': self.transcription.detected_language,
                'segments': segments
            },
            'llm_model': {
                'model': self.llm_model.model,
                'duration': self.llm_model.duration,
                'tokens': self.llm_model.tokens
            } if self.llm_model else None,
            'translation_model': {
                'model': self.translation_model.model,
                'duration': self.translation_model.duration,
                'tokens': self.translation_model.tokens
            } if self.translation_model else None
        } 