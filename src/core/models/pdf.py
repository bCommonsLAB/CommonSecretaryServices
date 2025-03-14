"""
Datenmodelle für die PDF-Verarbeitung.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

@dataclass(frozen=False)  # Geändert auf nicht gefrorene Dataclass, um Aktualisierungen zu ermöglichen
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
    text_contents: List[Tuple[int, str]] = field(default_factory=list)
    extraction_method: str = "native"
    
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
            'text_contents': [{'page': page, 'content': content} for page, content in self.text_contents],
            'extraction_method': self.extraction_method
        } 