"""
Modelle für die Youtube-Verarbeitung.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from .base import BaseResponse, ProcessInfo, RequestInfo, ErrorInfo, ProcessingStatus
from .audio import TranscriptionResult
from src.processors.cacheable_processor import CacheableResult

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

@dataclass
class YoutubeProcessingResult(CacheableResult):
    """Ergebnis der Youtube-Verarbeitung.
    
    Attributes:
        metadata: Metadaten des Videos
        transcription: Transkriptionsergebnis (wenn verfügbar)
        process_id: ID des Verarbeitungsprozesses
    """
    metadata: YoutubeMetadata
    transcription: Optional[TranscriptionResult] = None
    process_id: Optional[str] = None

    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.transcription else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'transcription': {
                'text': self.transcription.text,
                'detected_language': self.transcription.source_language,
                'segments': [
                    {
                        'text': seg.text,
                        'segment_id': seg.segment_id,
                        'start': seg.start,
                        'end': seg.end,
                        'title': seg.title
                    } for seg in self.transcription.segments
                ]
            } if self.transcription else None,
            'process_id': self.process_id
        }

@dataclass(frozen=True, init=False)
class YoutubeResponse(BaseResponse):
    """
    Standardisierte Response für die Youtube-Verarbeitung.
    
    Attributes:
        request: Informationen zur Anfrage
        process: Informationen zum Verarbeitungsprozess
        data: Die verarbeiteten Daten
        status: Status der Verarbeitung
    """
    data: YoutubeProcessingResult

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: YoutubeProcessingResult,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die YoutubeResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict()
        return base_dict 