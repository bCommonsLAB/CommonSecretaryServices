"""
@fileoverview PDF Models - Dataclasses for PDF processing and text extraction

@description
Data models for PDF processing. This file defines all dataclasses for PDF processing,
including text extraction, OCR, metadata, and preview image generation.

Main classes:
- PDFMetadata: Metadata of a processed PDF file
- PDFProcessingResult: Cacheable processing result
- PDFResponse: API response for PDF processing

Features:
- Validation of all fields in __post_init__
- Serialization to dictionary (to_dict)
- Deserialization from dictionary (from_dict)
- Support for various extraction methods (native, OCR, LLM)
- Preview image management (preview_paths, preview_zip)

@module core.models.pdf

@exports
- PDFMetadata: Dataclass - PDF metadata (frozen=True for immutability)
- PDFProcessingResult: Class - Cacheable processing result
- PDFResponse: Dataclass - API response for PDF processing

@usedIn
- src.processors.pdf_processor: Uses all PDF models
- src.processors.session_processor: Uses PDFResponse for session PDFs
- src.api.routes.pdf_routes: Uses PDFResponse for API responses

@dependencies
- Standard: dataclasses - Dataclass definitions
- Standard: typing - Type annotations
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple, cast

@dataclass(frozen=True)  # Auf frozen=True umgestellt für Unveränderlichkeit
class PDFMetadata:
    """Metadaten einer verarbeiteten PDF-Datei.
    
    Attributes:
        file_name: Name der PDF-Datei
        file_size: Größe der Datei in Bytes
        page_count: Anzahl der Seiten
        format: Dateiformat (Standard: pdf)
        process_dir: Verarbeitungsverzeichnis
        image_paths: Liste der extrahierten Bildpfade
        preview_paths: Liste der generierten Vorschaubilder
        preview_zip: Pfad zur ZIP-Datei mit Vorschaubildern
        text_paths: Liste der extrahierten Textdateien
        original_text_paths: Liste der originalen Textdateien
        text_contents: Liste von (Seitennummer, Inhalt)-Tupeln mit den tatsächlichen Textinhalten
        extraction_method: Verwendete Extraktionsmethode
    """
    file_name: str
    file_size: int
    page_count: int
    format: str = "pdf"
    process_dir: Optional[str] = None
    image_paths: List[str] = field(default_factory=list)
    preview_paths: List[str] = field(default_factory=list)
    preview_zip: Optional[str] = None
    text_paths: List[str] = field(default_factory=list)
    original_text_paths: List[str] = field(default_factory=list)
    text_contents: List[Tuple[int, str]] = field(default_factory=list)
    extraction_method: str = "native"
    
    def __post_init__(self) -> None:
        """Validiert die Metadaten nach der Initialisierung."""
        if not self.file_name:
            raise ValueError("file_name darf nicht leer sein")
        if self.file_size < 0:
            raise ValueError("file_size muss positiv sein")
        if self.page_count < 0:
            raise ValueError("page_count muss positiv sein")
        if not self.extraction_method:
            object.__setattr__(self, 'extraction_method', "native")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'file_name': self.file_name,
            'file_size': self.file_size,
            'page_count': self.page_count,
            'format': self.format,
            'process_dir': self.process_dir,
            'image_paths': self.image_paths,
            'preview_paths': self.preview_paths,
            'preview_zip': self.preview_zip,
            'text_paths': self.text_paths,
            'original_text_paths': self.original_text_paths,
            'text_contents': [{'page': page, 'content': content} for page, content in self.text_contents],
            'extraction_method': self.extraction_method
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PDFMetadata':
        """Erstellt ein PDFMetadata-Objekt aus einem Dictionary.
        
        Args:
            data: Dictionary mit den zu deserialisierenden Daten
            
        Returns:
            Eine neue PDFMetadata-Instanz
        """
        # text_contents speziell behandeln
        text_contents: List[Tuple[int, str]] = []
        raw_contents = data.get('text_contents', [])
        
        if isinstance(raw_contents, list):
            # Typ-Annotation für die Listenelemente
            contents_list: List[Any] = raw_contents
            for item in contents_list:
                try:
                    if isinstance(item, dict) and 'page' in item and 'content' in item:
                        page = int(cast(Any, item['page']))
                        content = str(cast(Any, item['content']))
                        text_contents.append((page, content))
                    elif isinstance(item, (list, tuple)):
                        # Direkt auf das zweite Element zugreifen
                        # und Fehler im vorhandenen Try/Except abfangen
                        page = int(cast(Any, item[0]))
                        content = str(cast(Any, item[1]))
                        text_contents.append((page, content))
                except (ValueError, TypeError, IndexError):
                    # Ungültige Einträge überspringen
                    continue
                    
        return cls(
            file_name=str(data.get('file_name', '')),
            file_size=int(data.get('file_size', 0)),
            page_count=int(data.get('page_count', 0)),
            format=str(data.get('format', 'pdf')),
            process_dir=data.get('process_dir'),
            image_paths=list(data.get('image_paths', [])),
            preview_paths=list(data.get('preview_paths', [])),
            preview_zip=data.get('preview_zip'),
            text_paths=list(data.get('text_paths', [])),
            original_text_paths=list(data.get('original_text_paths', [])),
            text_contents=text_contents,
            extraction_method=str(data.get('extraction_method', 'native'))
        ) 