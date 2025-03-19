"""
Metadaten-spezifische Typen und Modelle.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, Type, TypeVar

from .base import BaseResponse, RequestInfo, ProcessInfo, ErrorInfo
from .enums import ProcessingStatus
from .llm import LLMInfo

# Für Type-Safety in den Factory-Methoden
MR = TypeVar('MR', bound='MetadataResponse')

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

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die inhaltlichen Metadaten in ein Dictionary."""
        return {
            'type': self.type,
            'created': self.created,
            'modified': self.modified,
            'title': self.title,
            'subtitle': self.subtitle,
            'authors': self.authors,
            'publisher': self.publisher,
            'publication_date': self.publication_date,
            'isbn': self.isbn,
            'doi': self.doi,
            'edition': self.edition,
            'language': self.language,
            'subject_areas': self.subject_areas,
            'keywords': self.keywords,
            'abstract': self.abstract,
            'temporal_start': self.temporal_start,
            'temporal_end': self.temporal_end,
            'temporal_period': self.temporal_period,
            'spatial_location': self.spatial_location,
            'spatial_latitude': self.spatial_latitude,
            'spatial_longitude': self.spatial_longitude,
            'spatial_habitat': self.spatial_habitat,
            'spatial_region': self.spatial_region,
            'rights_holder': self.rights_holder,
            'rights_license': self.rights_license,
            'rights_access': self.rights_access,
            'rights_usage': self.rights_usage,
            'rights_attribution': self.rights_attribution,
            'rights_commercial': self.rights_commercial,
            'rights_modifications': self.rights_modifications
        }

@dataclass(frozen=True, slots=True)
class TechnicalMetadata:
    """Technische Metadaten für verschiedene Medientypen."""
    
    # Basis-Metadaten
    file_name: str
    file_mime: str
    file_size: int
    created: str
    modified: str
    
    # PDF-spezifische Metadaten
    doc_pages: Optional[int] = None
    doc_encrypted: Optional[bool] = None
    
    # Audio/Video-spezifische Metadaten
    media_duration: Optional[float] = None
    media_bitrate: Optional[int] = None
    media_codec: Optional[str] = None
    media_channels: Optional[int] = None
    media_sample_rate: Optional[int] = None
    
    # Bild-spezifische Metadaten
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_colorspace: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die technischen Metadaten in ein Dictionary."""
        return {
            'file_name': self.file_name,
            'file_mime': self.file_mime,
            'file_size': self.file_size,
            'created': self.created,
            'modified': self.modified,
            'doc_pages': self.doc_pages,
            'doc_encrypted': self.doc_encrypted,
            'media_duration': self.media_duration,
            'media_bitrate': self.media_bitrate,
            'media_codec': self.media_codec,
            'media_channels': self.media_channels,
            'media_sample_rate': self.media_sample_rate,
            'image_width': self.image_width,
            'image_height': self.image_height,
            'image_colorspace': self.image_colorspace
        }

@dataclass(frozen=True)
class MetadataData:
    """Container für alle Metadaten-Informationen."""
    technical: Optional[TechnicalMetadata] = None
    content: Optional[ContentMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'technical': self.technical.to_dict() if self.technical else None,
            'content': self.content.to_dict() if self.content else None
        }

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
    def create(
        cls: Type[MR], 
        data: Optional[MetadataData] = None, 
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> MR:
        """Erstellt eine erfolgreiche Response mit den angegebenen Daten.
        
        Args:
            data: Die Metadaten
            process: Optionale Prozess-Informationen
            **kwargs: Weitere Parameter für die BaseResponse
            
        Returns:
            MetadataResponse: Eine erfolgreiche Antwort
        """
        if data is None:
            data = MetadataData()
            
        # Erstelle eine neue Instanz mit den Basis-Parametern
        response = cls(
            request=kwargs.get('request', RequestInfo(
                processor="metadata",
                timestamp=kwargs.get('timestamp', ''),
                parameters=kwargs.get('parameters', {})
            )),
            process=process or kwargs.get('process', ProcessInfo(
                id=kwargs.get('id', ''),
                main_processor="metadata",
                started=kwargs.get('started', ''),
                sub_processors=kwargs.get('sub_processors', []),
                llm_info=kwargs.get('processor_llm_info')
            )),
            data=data,
            llm_info=kwargs.get('llm_info'),
            status=ProcessingStatus.SUCCESS,
            error=None
        )
        
        return response

    @classmethod
    def create_error(
        cls: Type[MR], 
        error: ErrorInfo,
        **kwargs: Any
    ) -> MR:
        """Erstellt eine Fehler-Response mit den angegebenen Informationen.
        
        Args:
            error: Die Fehlerinformationen
            **kwargs: Weitere Parameter für die BaseResponse
            
        Returns:
            MetadataResponse: Eine Fehlerantwort
        """
        # Erstelle eine neue Instanz mit den Basis-Parametern
        response = cls(
            request=kwargs.get('request', RequestInfo(
                processor="metadata",
                timestamp=kwargs.get('timestamp', ''),
                parameters=kwargs.get('parameters', {})
            )),
            process=kwargs.get('process', ProcessInfo(
                id=kwargs.get('id', ''),
                main_processor="metadata",
                started=kwargs.get('started', ''),
                sub_processors=kwargs.get('sub_processors', []),
                llm_info=kwargs.get('processor_llm_info')
            )),
            data=MetadataData(),  # Leere Metadaten bei Fehler
            llm_info=kwargs.get('llm_info'),
            status=ProcessingStatus.ERROR,
            error=error
        )
        
        return response 