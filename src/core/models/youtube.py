"""
Modelle für die Youtube-Verarbeitung.

Implementiert die standardisierte Response-Struktur und LLM-Tracking.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Protocol
from datetime import datetime

from .base import BaseResponse, ProcessInfo, ErrorInfo, ProcessingStatus
from .audio import TranscriptionResult, TranscriptionSegment
from src.processors.cacheable_processor import CacheableResult

class YoutubeMetadataProtocol(Protocol):
    """Protocol für die YoutubeMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    url: str
    video_id: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    
    # Dynamische Attribute
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]

@dataclass(frozen=True)
class YoutubeMetadata:
    """Metadaten eines Youtube-Videos."""
    title: str
    url: str
    video_id: str
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    availability: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    thumbnail: Optional[str] = None
    upload_date: Optional[str] = None
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    dislike_count: Optional[int] = None
    average_rating: Optional[float] = None
    age_limit: Optional[int] = None
    webpage_url: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.title.strip():
            raise ValueError("title darf nicht leer sein")
        if not self.url.strip():
            raise ValueError("url darf nicht leer sein")
        if not self.video_id.strip():
            raise ValueError("video_id darf nicht leer sein")
        if self.duration < 0:
            raise ValueError("duration muss positiv sein")
        if not self.duration_formatted.strip():
            raise ValueError("duration_formatted darf nicht leer sein")
        if self.file_size is not None and self.file_size <= 0:
            raise ValueError("file_size muss positiv sein wenn gesetzt")
        if self.age_limit is not None and (self.age_limit < 0 or self.age_limit > 21):
            raise ValueError("age_limit muss zwischen 0 und 21 liegen")
        if self.average_rating is not None and (self.average_rating < 0 or self.average_rating > 5):
            raise ValueError("average_rating muss zwischen 0 und 5 liegen")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'title': self.title,
            'url': self.url,
            'video_id': self.video_id,
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'availability': self.availability,
            'categories': self.categories,
            'description': self.description,
            'tags': self.tags,
            'thumbnail': self.thumbnail,
            'upload_date': self.upload_date,
            'uploader': self.uploader,
            'uploader_id': self.uploader_id,
            'chapters': self.chapters,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'dislike_count': self.dislike_count,
            'average_rating': self.average_rating,
            'age_limit': self.age_limit,
            'webpage_url': self.webpage_url
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'YoutubeMetadata':
        """Erstellt ein YoutubeMetadata-Objekt aus einem Dictionary."""
        return cls(
            title=data['title'],
            url=data['url'],
            video_id=data['video_id'],
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            availability=data.get('availability'),
            categories=data.get('categories', []),
            description=data.get('description'),
            tags=data.get('tags', []),
            thumbnail=data.get('thumbnail'),
            upload_date=data.get('upload_date'),
            uploader=data.get('uploader'),
            uploader_id=data.get('uploader_id'),
            chapters=data.get('chapters', []),
            view_count=data.get('view_count'),
            like_count=data.get('like_count'),
            dislike_count=data.get('dislike_count'),
            average_rating=data.get('average_rating'),
            age_limit=data.get('age_limit'),
            webpage_url=data.get('webpage_url')
        )

@dataclass
class YoutubeProcessingResult(CacheableResult):
    """Ergebnis der Youtube-Verarbeitung."""
    metadata: YoutubeMetadata
    transcription: Optional[TranscriptionResult] = None
    process_id: Optional[str] = None
    processed_at: Optional[datetime] = None

    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.metadata:
            raise ValueError("metadata darf nicht None sein")
        if self.process_id is not None and not self.process_id.strip():
            raise ValueError("process_id darf nicht leer sein wenn gesetzt")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'transcription': self.transcription.to_dict() if self.transcription else None,
            'process_id': self.process_id,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'status': self.status.value
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'YoutubeProcessingResult':
        """Erstellt ein YoutubeProcessingResult aus einem Dictionary."""
        metadata = YoutubeMetadata.from_dict(data['metadata'])
        transcription_data = data.get('transcription')
        transcription = None
        
        if transcription_data:
            transcription = TranscriptionResult(
                text=transcription_data.get('text', ''),
                source_language=transcription_data.get('detected_language', 'auto'),
                segments=[
                    TranscriptionSegment(
                        text=seg['text'],
                        segment_id=seg['segment_id'],
                        start=seg['start'],
                        end=seg['end'],
                        title=seg.get('title')
                    ) for seg in transcription_data.get('segments', [])
                ]
            )
        
        processed_at = None
        if data.get('processed_at'):
            try:
                processed_at = datetime.fromisoformat(data['processed_at'])
            except (ValueError, TypeError):
                pass
                
        return cls(
            metadata=metadata,
            transcription=transcription,
            process_id=data.get('process_id'),
            processed_at=processed_at
        )

@dataclass(frozen=True, init=False)
class YoutubeResponse(BaseResponse):
    """Standardisierte Response für die Youtube-Verarbeitung."""
    data: Optional[YoutubeProcessingResult] = field(default=None)

    def __init__(
        self,
        data: YoutubeProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die YoutubeResponse."""
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
        data: Optional[YoutubeProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'YoutubeResponse':
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
    ) -> 'YoutubeResponse':
        """Erstellt eine Error-Response."""
        empty_result = YoutubeProcessingResult(
            metadata=YoutubeMetadata(
                title="",
                url="",
                video_id="",
                duration=0,
                duration_formatted="00:00:00"
            ),
            process_id=""
        )
        response = cls(data=empty_result, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 