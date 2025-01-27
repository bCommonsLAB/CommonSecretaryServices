"""
YouTube-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from .audio import AudioProcessingResult

@dataclass(frozen=True, slots=True)
class YoutubeMetadata:
    """Metadaten eines YouTube-Videos."""
    title: str
    url: str
    video_id: str
    duration: int
    duration_formatted: str
    process_dir: str
    file_size: Optional[int] = None
    audio_file: Optional[str] = None
    
    # Video-spezifische Metadaten
    source_type: str = field(default="youtube")
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

    def __post_init__(self):
        if not self.title.strip():
            raise ValueError("Title must not be empty")
        if not self.url.strip():
            raise ValueError("URL must not be empty")
        if not self.video_id.strip():
            raise ValueError("Video ID must not be empty")
        if self.duration < 0:
            raise ValueError("Duration must be non-negative")
        if not self.duration_formatted.strip():
            raise ValueError("Duration formatted must not be empty")
        if not self.process_dir.strip():
            raise ValueError("Process directory must not be empty")
        if self.audio_file is not None and not self.audio_file.strip():
            raise ValueError("Audio file must not be empty if provided")

@dataclass(frozen=True, slots=True)
class YoutubeProcessingResult:
    """
    Ergebnis der YouTube-Verarbeitung.
    Kombiniert YoutubeMetadata mit optionalem AudioProcessingResult.
    """
    metadata: YoutubeMetadata
    process_id: str
    audio_result: Optional[AudioProcessingResult] = None

    def __post_init__(self):
        if not self.process_id.strip():
            raise ValueError("Process ID must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert das Ergebnis in ein Dictionary für die API-Antwort.
        """
        result = {
            "title": self.metadata.title,
            "duration": self.metadata.duration,
            "url": self.metadata.url,
            "video_id": self.metadata.video_id,
            "process_id": self.process_id,
            "file_size": self.metadata.file_size,
            "process_dir": self.metadata.process_dir,
            "audio_file": self.metadata.audio_file,
            "youtube_metadata": {
                "upload_date": self.metadata.upload_date,
                "uploader": self.metadata.uploader,
                "view_count": self.metadata.view_count,
                "like_count": self.metadata.like_count,
                "description": self.metadata.description,
                "tags": self.metadata.tags,
                "categories": self.metadata.categories
            }
        }
        
        if self.audio_result is not None:
            if self.audio_result.transcription:
                result["transcription"] = self.audio_result.transcription.to_dict()
            if self.audio_result.metadata:
                result["audio_metadata"] = self.audio_result.metadata.to_dict()

        return result 