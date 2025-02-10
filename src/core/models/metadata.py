"""
Metadaten-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

from .base import BaseResponse, RequestInfo, ProcessInfo, ErrorInfo
from .enums import ProcessingStatus
from .llm import LLMInfo

@dataclass(frozen=True, slots=True)
class ContentMetadata:
    """Inhaltliche Metadaten für verschiedene Medientypen."""
    
    # Basis-Metadaten
    type: Optional[str] = None
    created: Optional[str] = None
    modified: Optional[str] = None
    
    # Bibliographische Grunddaten
    title: Optional[str] = None
    subtitle: Optional[str] = None
    authors: Optional[str] = None
    publisher: Optional[str] = None
    publication_date: Optional[str] = None
    isbn: Optional[str] = None
    doi: Optional[str] = None
    edition: Optional[str] = None
    language: Optional[str] = None
    
    # Wissenschaftliche Klassifikation
    subject_areas: Optional[str] = None
    keywords: Optional[str] = None
    abstract: Optional[str] = None
    
    # Räumliche und zeitliche Einordnung
    temporal_start: Optional[str] = None
    temporal_end: Optional[str] = None
    temporal_period: Optional[str] = None
    spatial_location: Optional[str] = None
    spatial_latitude: Optional[float] = None
    spatial_longitude: Optional[float] = None
    spatial_habitat: Optional[str] = None
    spatial_region: Optional[str] = None
    
    # Rechte und Lizenzen
    rights_holder: Optional[str] = None
    rights_license: Optional[str] = None
    rights_access: Optional[str] = None
    rights_usage: Optional[str] = None
    rights_attribution: Optional[str] = None
    rights_commercial: Optional[bool] = None
    rights_modifications: Optional[bool] = None
    
    def __post_init__(self) -> None:
        # Validiere optionale Felder wenn sie gesetzt sind
        if self.language is not None and len(self.language) != 2:
            raise ValueError("Language code must be ISO 639-1 (2 characters)")
        if self.spatial_latitude is not None and not -90 <= self.spatial_latitude <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if self.spatial_longitude is not None and not -180 <= self.spatial_longitude <= 180:
            raise ValueError("Longitude must be between -180 and 180")

@dataclass(frozen=True, slots=True)
class TechnicalMetadata:
    """Technische Metadaten einer Datei."""
    file_name: str
    file_mime: str
    file_size: int
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    modified: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Optionale Felder für verschiedene Dateitypen
    doc_pages: Optional[int] = None
    media_duration: Optional[float] = None
    media_bitrate: Optional[int] = None
    media_codec: Optional[str] = None
    media_channels: Optional[int] = None
    media_sample_rate: Optional[int] = None
    
    def __post_init__(self) -> None:
        if not self.file_name.strip():
            raise ValueError("File name must not be empty")
        if not self.file_mime.strip():
            raise ValueError("MIME type must not be empty")
        if self.file_size < 0:
            raise ValueError("File size must be positive")
        if self.doc_pages is not None and self.doc_pages <= 0:
            raise ValueError("Document pages must be positive")
        if self.media_duration is not None and self.media_duration <= 0:
            raise ValueError("Media duration must be positive")
        if self.media_bitrate is not None and self.media_bitrate <= 0:
            raise ValueError("Media bitrate must be positive")
        if self.media_channels is not None and self.media_channels <= 0:
            raise ValueError("Media channels must be positive")
        if self.media_sample_rate is not None and self.media_sample_rate <= 0:
            raise ValueError("Media sample rate must be positive") 

@dataclass(frozen=True, slots=True)
class MetadataData:
    """Container für alle Metadaten-Informationen."""
    technical: Optional[TechnicalMetadata] = None
    content: Optional[ContentMetadata] = None
    source_info: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.technical and not self.content:
            raise ValueError("At least one of technical or content metadata must be provided")

@dataclass(frozen=True, init=False)
class MetadataResponse(BaseResponse):
    """Hauptresponse-Klasse für den MetadataProcessor."""
    data: MetadataData
    llm_info: Optional[LLMInfo] = None
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: MetadataData,
        llm_info: Optional[LLMInfo] = None,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die MetadataResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'llm_info', llm_info)

    @classmethod
    def create(cls, request: RequestInfo, process: ProcessInfo, data: MetadataData,
               llm_info: Optional[LLMInfo] = None) -> 'MetadataResponse':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            request=request,
            process=process,
            data=data,
            llm_info=llm_info,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error_info: ErrorInfo) -> 'MetadataResponse':
        """Erstellt eine Fehler-Response."""
        return cls(
            request=request,
            process=process,
            data=MetadataData(content=None, technical=None),  # Leere Metadaten bei Fehler
            error=error_info,
            status=ProcessingStatus.ERROR
        ) 