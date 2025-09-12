"""
PDF Processor für die Verarbeitung von PDF-Dateien.

LLM-Tracking Logik:
-----------------
Der PDFProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
   a) Text-Extraktion:
      - Model: pdf-extraction
      - Purpose: text_extraction
      
   b) OCR-Extraktion:
      - Model: tesseract
      - Purpose: ocr_extraction
      
   c) Template-Transformation (wenn Template verwendet):
      - Model: gpt-4
      - Purpose: template_transform
"""

import traceback
import time
import json
import hashlib
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Optional, Union, cast, TYPE_CHECKING, List, Tuple
from dataclasses import dataclass, field
import subprocess
import os
from urllib.parse import urlparse
import fitz  # type: ignore
import requests

from src.processors.cacheable_processor import CacheableProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.core.config import Config
from src.core.models.base import ErrorInfo, BaseResponse, ProcessInfo
from src.core.models.pdf import PDFMetadata
from src.processors.transformer_processor import TransformerProcessor
from src.processors.imageocr_processor import ImageOCRProcessor  # Neue Import
from src.core.models.enums import ProcessingStatus
from src.utils.image2text_utils import Image2TextService

# Konstanten für Processor-Typen
PROCESSOR_TYPE_PDF = "pdf"

# Konstanten für Extraktionsmethoden
EXTRACTION_NATIVE = "native"  # Nur native Text-Extraktion
EXTRACTION_OCR = "ocr"       # Nur OCR
EXTRACTION_BOTH = "both"     # Beide Methoden kombinieren
EXTRACTION_PREVIEW = "preview"
EXTRACTION_PREVIEW_AND_NATIVE = "preview_and_native"  # Vorschaubilder und native Text-Extraktion

# Neue Konstanten für LLM-basierte OCR
EXTRACTION_LLM = "llm"  # LLM-basierte OCR mit Markdown-Output
EXTRACTION_LLM_AND_NATIVE = "llm_and_native"  # LLM + native Text
EXTRACTION_LLM_AND_OCR = "llm_and_ocr"  # LLM + Tesseract OCR
# Neue Methode: serverseitige Mistral-OCR ohne lokale Seitenrendering-Pipeline
EXTRACTION_MISTRAL_OCR = "mistral_ocr"

# PyMuPDF Typendefinitionen für den Linter
if TYPE_CHECKING:
    class FitzPage:
        """Typ-Definitionen für PyMuPDF Page-Objekte."""
        rect: Any
        def get_text(self) -> str: ...
        def get_pixmap(self, matrix: Any = None) -> 'FitzPixmap': ...
    
    class FitzPixmap:
        """Typ-Definitionen für PyMuPDF Pixmap-Objekte."""
        def save(self, filename: str, output: str = "", jpg_quality: int = 80) -> None: ...

# Typ-Aliase für bessere Linter-Unterstützung
FitzPageType = Any  # type: ignore
FitzPixmapType = Any  # type: ignore

@dataclass(frozen=True)
class PDFProcessingResult:
    """Ergebnis der PDF-Verarbeitung."""
    metadata: PDFMetadata
    extracted_text: Optional[str]
    ocr_text: Optional[str] = None
    process_id: Optional[str] = None
    processed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # Neue Felder für Bilder-Archiv
    images_archive_data: Optional[str] = None  # Base64-kodiertes ZIP-Archiv mit Bildern
    images_archive_filename: Optional[str] = None  # Dateiname des Bilder-Archives
    # Rohantwort der Mistral OCR API (nur bei extraction_method=mistral_ocr gesetzt)
    mistral_ocr_raw: Optional[Dict[str, Any]] = None
    
    def __post_init__(self) -> None:
        """Validiert das Ergebnis nach der Initialisierung."""
        if not self.metadata:
            raise ValueError("metadata darf nicht leer sein")
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.extracted_text or self.ocr_text else ProcessingStatus.ERROR
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'extracted_text': self.extracted_text,
            'ocr_text': self.ocr_text,
            'process_id': self.process_id,
            'processed_at': self.processed_at,
            'images_archive_data': self.images_archive_data,
            'images_archive_filename': self.images_archive_filename,
            # Rohantwort der Mistral OCR API (optional)
            'mistral_ocr_raw': getattr(self, 'mistral_ocr_raw', None)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PDFProcessingResult':
        """Erstellt ein PDFProcessingResult aus einem Dictionary."""
        from src.core.models.pdf import PDFMetadata
        
        # Metadaten direkt aus dem Dictionary extrahieren
        metadata_dict: Dict[str, Any] = data.get('metadata', {})
        
        # PDFMetadata aus Dictionary erstellen
        if metadata_dict:
            metadata = PDFMetadata.from_dict(metadata_dict)
        else:
            # Minimale Metadaten, falls keine vorhanden sind
            metadata = PDFMetadata(
                file_name="Unknown",
                file_size=0,
                page_count=0
            )
        
        return cls(
            metadata=metadata,
            extracted_text=data.get('extracted_text'),
            ocr_text=data.get('ocr_text'),
            process_id=data.get('process_id'),
            processed_at=data.get('processed_at', datetime.now(UTC).isoformat()),
            images_archive_data=data.get('images_archive_data'),
            images_archive_filename=data.get('images_archive_filename'),
            # Mistral Rohdaten wenn vorhanden übernehmen
            **({'mistral_ocr_raw': data.get('mistral_ocr_raw')} if 'mistral_ocr_raw' in data else {})
        )

@dataclass(frozen=True)
class PDFResponse(BaseResponse):
    """Standardisierte Response für die PDF-Verarbeitung."""
    data: Optional[PDFProcessingResult] = None

class PDFProcessor(CacheableProcessor[PDFProcessingResult]):
    """
    Prozessor für die Verarbeitung von PDF-Dokumenten.
    
    Unterstützt:
    - Extraktion von Text aus PDFs
    - Extraktion von Metadaten
    - Strukturierte Dokumentenanalyse
    - Vorschaubilder generieren
    - LLM-basierte OCR mit Markdown-Output
    
    Verwendet MongoDB-Caching zur effizienten Wiederverwendung von Verarbeitungsergebnissen.
    """
    
    # Name der MongoDB-Cache-Collection
    cache_collection_name = "pdf_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den PDFProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Lade Konfiguration
        config = Config()
        self.max_file_size = config.get('processors.pdf.max_file_size', 130 * 1024 * 1024)
        self.max_pages = config.get('processors.pdf.max_pages', 200)
        
        # Bildkonfiguration laden
        self.main_image_max_size = config.get('processors.pdf.images.main.max_size', 1280)
        self.main_image_format = config.get('processors.pdf.images.main.format', 'jpg')
        self.main_image_quality = config.get('processors.pdf.images.main.quality', 80)
        
        self.preview_image_max_size = config.get('processors.pdf.images.preview.max_size', 360)
        self.preview_image_format = config.get('processors.pdf.images.preview.format', 'jpg')
        self.preview_image_quality = config.get('processors.pdf.images.preview.quality', 80)
        
        # Debug-Logging der PDF-Konfiguration
        self.logger.debug("PDFProcessor initialisiert mit Konfiguration", 
                         max_file_size=self.max_file_size,
                         max_pages=self.max_pages,
                         temp_dir=str(self.temp_dir),
                         cache_dir=str(self.cache_dir),
                         main_image_max_size=self.main_image_max_size,
                         main_image_format=self.main_image_format,
                         preview_image_max_size=self.preview_image_max_size,
                         preview_image_format=self.preview_image_format)
        
        # Initialisiere Transformer
        self.transformer = TransformerProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Initialisiere ImageOCR Processor für OCR-Aufgaben
        self.imageocr_processor = ImageOCRProcessor(
            resource_calculator,
            process_id
        )
        
        # Initialisiere Image2Text Service für LLM-basierte OCR
        self.image2text_service = Image2TextService(
            processor_name=f"PDFProcessor-{process_id}"
        )
        
    def create_process_dir(self, identifier: str, use_temp: bool = True) -> Path:
        """
        Erstellt und gibt das Verarbeitungsverzeichnis für eine PDF zurück.
        
        Args:
            identifier: Eindeutige Kennung der PDF-Datei
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        process_dir: Path = base_dir / "pdf" / identifier
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir

    def save_page_text(self, text: str, page_num: int, process_dir: Path) -> Path:
        """
        Speichert den extrahierten Text einer Seite in einer Datei und fügt ihn den Metadaten hinzu.
        
        Args:
            text: Der zu speichernde Text
            page_num: Die Seitennummer (0-basiert)
            process_dir: Das Verzeichnis, in dem die Datei gespeichert werden soll
            
        Returns:
            Path: Pfad zur gespeicherten Textdatei
        """
        # Erstelle die Textdatei
        text_path = process_dir / f"page_{page_num+1:03d}.txt"
        text_path.write_text(text, encoding='utf-8')
        
        # Gibt den Pfad zur Textdatei zurück
        return text_path

    def _generate_preview(self, page: Any, page_num: int, working_dir: Path) -> str:
        """Generiert ein Vorschaubild für eine PDF-Seite.
        
        Args:
            page: Die PDF-Seite
            page_num: Die Seitennummer (0-basiert)
            working_dir: Arbeitsverzeichnis
            
        Returns:
            Pfad zum generierten Vorschaubild
        """
        # Diese Methode wird aus Kompatibilitätsgründen beibehalten
        # und ruft die neue _generate_preview_image-Methode auf
        return self._generate_preview_image(page, page_num, working_dir)

    def _generate_main_image(self, page: Any, page_num: int, working_dir: Path) -> str:
        """Generiert ein Hauptbild für eine PDF-Seite mit den konfigurierten Einstellungen.
        
        Args:
            page: Die PDF-Seite
            page_num: Die Seitennummer (0-basiert)
            working_dir: Arbeitsverzeichnis
            
        Returns:
            Pfad zum generierten Hauptbild als String
        """
        # Berechne den Skalierungsfaktor für die gewünschte Größe
        # Standardauflösung anpassen, um ungefähr die gewünschte Maximalgröße zu erreichen
        # Wir erhalten zunächst die Originalgröße der Seite
        page_rect = page.rect
        original_width = page_rect.width
        original_height = page_rect.height
        
        # Berechne Skalierungsfaktor basierend auf der gewünschten Maximalgröße
        scale_factor = min(self.main_image_max_size / original_width, self.main_image_max_size / original_height)
        matrix = fitz.Matrix(scale_factor, scale_factor)
        
        # Erzeuge das Pixmap direkt mit dem berechneten Skalierungsfaktor
        pix = page.get_pixmap(matrix=matrix)
        
        # Speichere als JPG mit konfigurierter Qualität
        image_path = working_dir / f"image_{page_num+1:03d}.{self.main_image_format}"
        # Die JPG-Qualität wird als Parameter an die save-Methode übergeben (0-100)
        pix.save(str(image_path), output="jpeg", jpg_quality=self.main_image_quality)
        
        # Ressourcen freigeben
        del pix
        
        # Explizit als String zurückgeben
        return str(image_path)

    def _generate_preview_image(self, page: Any, page_num: int, working_dir: Path) -> str:
        """Generiert ein kleines Vorschaubild für eine PDF-Seite.
        
        Args:
            page: Die PDF-Seite
            page_num: Die Seitennummer (0-basiert)
            working_dir: Arbeitsverzeichnis
            
        Returns:
            Pfad zum generierten Vorschaubild als String
        """
        # Berechne den Skalierungsfaktor für die gewünschte Vorschaugröße
        page_rect = page.rect
        original_width = page_rect.width
        original_height = page_rect.height
        
        # Berechne Skalierungsfaktor basierend auf der Vorschaumaximalgröße
        scale_factor = min(self.preview_image_max_size / original_width, self.preview_image_max_size / original_height)
        matrix = fitz.Matrix(scale_factor, scale_factor)
        
        # Erzeuge das Pixmap direkt mit dem berechneten Skalierungsfaktor
        pix = page.get_pixmap(matrix=matrix)
        
        # Speichere als JPG mit konfigurierter Qualität
        preview_path = working_dir / f"preview_{page_num+1:03d}.{self.preview_image_format}"
        # Die JPG-Qualität wird als Parameter an die save-Methode übergeben (0-100)
        pix.save(str(preview_path), output="jpeg", jpg_quality=self.preview_image_quality)
        
        # Ressourcen freigeben
        del pix
        
        # Explizit als String zurückgeben
        return str(preview_path)

    def _get_file_extension(self, url: str) -> str:
        """Extrahiert die Dateiendung aus einer URL.
        
        Args:
            url: Die URL der Datei
            
        Returns:
            Die Dateiendung (z.B. '.pdf', '.pptx')
        """
        parsed = urlparse(url)
        path = parsed.path
        # Extrahiere die Dateiendung aus dem Pfad
        ext = os.path.splitext(path)[1].lower()
        if not ext:
            # Wenn keine Endung gefunden wurde, versuche sie aus dem Content-Type zu ermitteln
            try:
                response: requests.Response = requests.head(url)
                content_type: str = response.headers.get('content-type', '').lower()
                if 'powerpoint' in content_type or 'presentation' in content_type:
                    return '.pptx'
                elif 'pdf' in content_type:
                    return '.pdf'
            except:
                pass
        return ext

    def _convert_pptx_to_pdf(self, input_path: Path, output_path: Path) -> None:
        """Konvertiert eine PowerPoint-Datei zu PDF.
        
        Args:
            input_path: Pfad zur PowerPoint-Datei
            output_path: Pfad für die PDF-Ausgabe
            
        Raises:
            ProcessingError: Wenn die Konvertierung fehlschlägt
        """
        try:
            # Prüfe ob LibreOffice installiert ist
            if os.name == 'nt':  # Windows
                libreoffice_path = r"C:\Program Files\LibreOffice\program\soffice.exe"
            else:  # Linux/Mac
                libreoffice_path = "soffice"
                
            if not os.path.exists(libreoffice_path):
                raise ProcessingError("LibreOffice ist nicht installiert. Bitte installieren Sie LibreOffice für die PDF-Konvertierung.")
            
            # Konvertiere PPTX zu PDF
            cmd: list[str] = [
                libreoffice_path,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(output_path.parent),
                str(input_path)
            ]
            
            self.logger.info(f"Starte Konvertierung: {' '.join(cmd)}")
            result: subprocess.CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise ProcessingError(f"Fehler bei der Konvertierung: {result.stderr}")
                
            self.logger.info("Konvertierung erfolgreich")
            
        except Exception as e:
            raise ProcessingError(f"Fehler bei der PPTX zu PDF Konvertierung: {str(e)}")

    def _create_cache_key(self, 
                         file_path: Union[str, Path], 
                         template: Optional[str] = None,
                         context: Optional[Dict[str, Any]] = None,
                         extraction_method: str = EXTRACTION_NATIVE,
                         file_hash: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel für PDF-Verarbeitung.
        
        Args:
            file_path: Pfad zur PDF-Datei
            template: Optional, das verwendete Template
            context: Optional, der Kontext für die Verarbeitung
            extraction_method: Die verwendete Extraktionsmethode
            file_hash: Optional, ein bereits berechneter Hash für die Datei
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Wenn ein vorgefertigter Hash bereitgestellt wurde, verwenden wir diesen
        if file_hash:
            key_parts = [f"hash_{file_hash}"]
        else:
            # Dateistatistik für eindeutige Identifizierung verwenden
            file_size = None
            try:
                file_path_obj = Path(file_path)
                file_size = file_path_obj.stat().st_size
            except:
                pass
            
            # Basis-Schlüssel aus Pfad und Dateigröße
            key_parts: list[str] = [str(file_path)]
            
            if file_size:
                key_parts.append(f"size_{file_size}")
        
        # Extraktionsmethode hinzufügen
        key_parts.append(f"method_{extraction_method}")
        
        # Template hinzufügen, wenn vorhanden
        if template:
            template_hash = hashlib.md5(template.encode()).hexdigest()[:8]
            key_parts.append(f"template_{template_hash}")
            
        # Kontext-Hash hinzufügen, wenn vorhanden
        if context:
            context_str: str = json.dumps(context, sort_keys=True)
            context_hash: str = hashlib.md5(context_str.encode()).hexdigest()[:8]
            key_parts.append(f"context_{context_hash}")
            
        # Schlüssel generieren
        return self.generate_cache_key("_".join(key_parts))
    
    def serialize_for_cache(self, result: PDFProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das PDFProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das Verarbeitungsergebnis
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Wir verwenden die bestehende to_dict Methode
        result_dict = result.to_dict()
        
        # Zusätzliche Cache-Metadaten
        cache_data = {
            "result": result_dict,
            "processed_at": datetime.now(UTC).isoformat(),
            "extraction_method": getattr(result.metadata, "extraction_method", "native"),
            "file_name": getattr(result.metadata, "file_name", ""),
            "file_size": getattr(result.metadata, "file_size", 0),
            "page_count": getattr(result.metadata, "page_count", 0)
        }
        
        return cache_data
        
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> PDFProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein PDFProcessingResult.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            PDFProcessingResult: Das deserialisierte PDFProcessingResult
        """
        # Result-Objekt aus den Daten erstellen
        result_data = cached_data.get('result', {})
        
        # PDFProcessingResult aus Dictionary erstellen
        result: PDFProcessingResult = PDFProcessingResult.from_dict(result_data)
        
        return result
    
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezialisierte Indizes für die Collection.
        Vermeidet Konflikte mit bestehenden Indizes.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Prüfen, ob bereits Indizes existieren
            existing_indices = collection.index_information()
            
            # Indizes nur erstellen, wenn sie noch nicht existieren
            index_definitions: list[tuple[str, int]] = [
                ("file_name", 1),
                ("file_size", 1),
                ("page_count", 1),
                ("extraction_method", 1)
            ]
            
            for field, direction in index_definitions:
                index_name: str = f"{field}_{direction}"
                if index_name not in existing_indices:
                    collection.create_index([(field, direction)], background=True)
                    
        except Exception as e:
            self.logger.warning(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")
            
    def _validate_file_type(self, path: Path) -> None:
        """Überprüft, ob die Datei ein gültiges PDF oder PowerPoint-Format ist.
        
        Args:
            path: Pfad zur Datei
            
        Raises:
            ProcessingError: Wenn die Datei kein unterstütztes Format hat
        """
        # Überprüfe Dateiendung
        file_extension = path.suffix.lower()
        valid_extensions = ['.pdf', '.pptx', '.ppt']
        
        if file_extension not in valid_extensions:
            raise ProcessingError(
                f"Ungültiges Dateiformat: {file_extension} "
                f"(Unterstützte Formate: {', '.join(valid_extensions)})"
            )
        
        # PDF-spezifische Validierung des Dateiinhalts
        if file_extension == '.pdf':
            try:
                with open(path, 'rb') as f:
                    header = f.read(5)
                    # PDF-Dateien beginnen mit %PDF-
                    if header[:4] != b'%PDF':
                        raise ProcessingError(
                            f"Die Datei hat keine gültige PDF-Signatur"
                        )
            except Exception as e:
                if isinstance(e, ProcessingError):
                    raise
                raise ProcessingError(f"Fehler beim Überprüfen der Datei: {str(e)}")

    async def process(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        extraction_method: Union[str, list[str]] = EXTRACTION_NATIVE,
        use_cache: bool = True,
        file_hash: Optional[str] = None,
        force_overwrite: bool = False,
        include_images: bool = False,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None
    ) -> PDFResponse:
        """
        Verarbeitet ein PDF-Dokument.
        
        Args:
            file_path: Pfad zur PDF-Datei
            template: Optional Template für die Verarbeitung
            context: Optionaler Kontext
            extraction_method: Extraktionsmethode (NATIVE, OCR, HYBRID, PREVIEW) oder Liste von Methoden
            use_cache: Ob der Cache verwendet werden soll
            file_hash: Optional, der Hash der Datei (wenn bereits berechnet)
            force_overwrite: Ob die Datei neu heruntergeladen werden soll, auch wenn sie bereits existiert
            include_images: Ob ein Base64-kodiertes ZIP-Archiv mit allen generierten Bildern erstellt werden soll
            
        Returns:
            PDFResponse: Die standardisierte Response
        """
        # Unterstützung für mehrere Extraktionsmethoden
        methods_list: list[str] = []
        if isinstance(extraction_method, list):
            methods_list = extraction_method
        elif extraction_method == EXTRACTION_PREVIEW_AND_NATIVE:
            methods_list = [EXTRACTION_PREVIEW, EXTRACTION_NATIVE]
        else:
            methods_list = [str(extraction_method)]
        
        # Erzeuge einen einfachen Key nur basierend auf dem Dateipfad/Hash für das Arbeitsverzeichnis
        file_key = file_hash or hashlib.md5(str(file_path).encode()).hexdigest()[:16]
        working_dir = Path(self.temp_dir) / "pdf" / file_key
        
        # Voller Cache-Key für die Ergebniscachierung (beinhaltet alle Parameter)
        cache_key = self._create_cache_key(
            file_path=file_path,
            template=template,
            context=context,
            extraction_method="_".join(methods_list),  # Kombinierte Methoden als Teil des Cache-Keys
            file_hash=file_hash
        )
        
        # include_images Parameter zum Cache-Key hinzufügen
        if include_images:
            cache_key += "_with_images"
                
        # Initialisiere LLM-Info außerhalb des try-blocks
        
        try:
            # Cache-Prüfung, wenn aktiviert
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für PDF-Verarbeitung: {cache_key[:8]}...")
                    
                    # Resource-Tracking für den Cache-Hit
                    try:
                        # Expliziter cast zu Any für den Resource Calculator
                        resource_calculator_any = cast(Any, self.resource_calculator)
                        resource_calculator_any.add_resource_usage(
                            processor_type="pdf",
                            resource_type="cache_hit",
                            duration_ms=0,
                            tokens=0,
                            cost=0
                        )
                    except AttributeError:
                        self.logger.debug("ResourceCalculator hat keine add_resource_usage Methode")
                    
                    # Direkte Verwendung von ResponseFactory für Cache-Treffer
                    return self.create_response(
                        processor_name="pdf",
                        result=cached_result,
                        request_info={
                            "file_path": str(file_path),
                            "template": template,
                            "context": context,
                            "extraction_method": extraction_method
                        },
                        response_class=PDFResponse,
                        from_cache=True,  # Hier auf True gesetzt, da aus dem Cache
                        cache_key=cache_key
                    )

            # Validiere alle Extraktionsmethoden
            valid_methods = [
                EXTRACTION_NATIVE, EXTRACTION_OCR, EXTRACTION_BOTH, EXTRACTION_PREVIEW,
                EXTRACTION_LLM, EXTRACTION_LLM_AND_NATIVE, EXTRACTION_LLM_AND_OCR,
                EXTRACTION_MISTRAL_OCR
            ]
            for method in methods_list:
                if method not in valid_methods:
                    raise ProcessingError(f"Ungültige Extraktionsmethode: {method}")

            # Erstelle Arbeitsverzeichnis, falls es nicht existiert
            if not working_dir.exists():
                working_dir.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Arbeitsverzeichnis angelegt: {str(working_dir)}")
            
            # Prüfe ob es sich um eine URL handelt
            if str(file_path).startswith(('http://', 'https://')):
                # Extrahiere Dateiendung aus URL
                file_extension = self._get_file_extension(str(file_path))
                # Validiere die Dateiendung für URLs
                valid_extensions = ['.pdf', '.pptx', '.ppt']
                if file_extension.lower() not in valid_extensions:
                    raise ProcessingError(
                        f"Ungültiges Dateiformat: {file_extension} "
                        f"(Unterstützte Formate: {', '.join(valid_extensions)})"
                    )
                temp_file = working_dir / f"document{file_extension}"
                # Prüfe, ob die Datei bereits existiert und nicht überschrieben werden soll
                if temp_file.exists() and not force_overwrite:
                    self.logger.info(f"Datei existiert bereits, überspringe Download: {temp_file}")
                    path = temp_file
                else:
                    self.logger.info(f"Lade Datei herunter: {file_path} (Dateiendung: {file_extension})")
                # Lade Datei von URL herunter
                download_resp: requests.Response = requests.get(str(file_path), stream=True)
                download_resp.raise_for_status()
                with open(temp_file, 'wb') as f:
                    for chunk in download_resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                    # Speichere den Originalnamen aus der URL
                    original_name_file = working_dir / "original_name.txt"
                    with open(original_name_file, 'w') as f2:
                        f2.write(str(file_path))
                path = temp_file
            else:
                # Lokale Datei wird direkt verwendet
                path = Path(file_path)
                # Speichere den Originalpfad
                original_path_file = working_dir / "original_path.txt"
                if not original_path_file.exists() or force_overwrite:
                    with open(original_path_file, 'w') as f:
                        f.write(str(file_path))

            # Früher Exit: reine Mistral-OCR ohne lokale Seitenrendering-Pipeline
            if methods_list == [EXTRACTION_MISTRAL_OCR]:
                try:
                    import os as _os
                    api_key: str = _os.environ.get("MISTRAL_API_KEY", "")
                    if not api_key:
                        raise ProcessingError("MISTRAL_API_KEY nicht gesetzt")
                    # Upload
                    files_url = "https://api.mistral.ai/v1/files"
                    headers_up: Dict[str, str] = {"Authorization": f"Bearer {api_key}"}
                    mime = "application/pdf"
                    # Fortschritt: Upload startet
                    self.logger.info("Mistral-OCR: Upload startet", progress=10)
                    with open(path, "rb") as fpdf:
                        files = {"file": (path.name, fpdf, mime)}
                        data_form = {"purpose": "ocr"}
                        up_resp = requests.post(files_url, headers=headers_up, files=files, data=data_form, timeout=180)
                    up_resp.raise_for_status()
                    up_json: Dict[str, Any] = up_resp.json() if up_resp.headers.get('content-type','').startswith('application/json') else {}
                    file_id: str = str(up_json.get("id") or up_json.get("file_id") or "")
                    if not file_id:
                        raise ProcessingError("Mistral Files Upload ohne file_id")
                    # Fortschritt: Upload abgeschlossen
                    self.logger.info("Mistral-OCR: Upload abgeschlossen", progress=30)
                    # OCR
                    ocr_url = "https://api.mistral.ai/v1/ocr"
                    headers_json: Dict[str, str] = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                    pages_payload: Optional[List[int]] = None
                    if page_start is not None or page_end is not None:
                        ps0 = max(0, (page_start or 1) - 1)
                        pe0 = (page_end - 1) if page_end is not None else ps0
                        if pe0 < ps0:
                            pe0 = ps0
                        pages_payload = list(range(ps0, pe0 + 1))
                    payload: Dict[str, Any] = {
                        "model": _os.environ.get("MISTRAL_MODEL", "mistral-ocr-2505"),
                        "document": {"type": "file", "file_id": file_id},
                    }
                    if pages_payload is not None:
                        payload["pages"] = pages_payload
                    # Fortschritt: OCR-Anfrage wird gesendet
                    self.logger.info("Mistral-OCR: OCR-Anfrage gesendet", progress=60)
                    ocr_resp = requests.post(ocr_url, headers=headers_json, json=payload, timeout=300)
                    ocr_resp.raise_for_status()
                    # Fortschritt: OCR-Antwort empfangen
                    self.logger.info("Mistral-OCR: OCR-Antwort empfangen", progress=75)
                    ocr_json: Dict[str, Any] = ocr_resp.json()
                    # Markdown joinen
                    pages_any: Any = ocr_json.get("pages", [])
                    text_contents: List[Tuple[int, str]] = []
                    md_parts: List[str] = []
                    if isinstance(pages_any, list):
                        for p_any in pages_any:  # type: ignore[assignment]
                            p_dict = cast(Dict[str, Any], p_any) if isinstance(p_any, dict) else {}
                            idx_val: Any = p_dict.get("index", 0)
                            try:
                                idx = int(idx_val)
                            except Exception:
                                idx = 0
                            md_val: Any = p_dict.get("markdown", "")
                            md = str(md_val)
                            text_contents.append((idx + 1, md))
                            md_parts.append(f"--- Seite {idx + 1} ---\n{md}")
                    result_text = "\n\n".join(md_parts)
                    # Fortschritt: OCR-Ergebnis geparst
                    try:
                        self.logger.info(f"Mistral-OCR: Ergebnis geparst ({len(text_contents)} Seiten)", progress=85)
                    except Exception:
                        self.logger.info("Mistral-OCR: Ergebnis geparst", progress=85)
                    metadata = PDFMetadata(
                        file_name=path.name,
                        file_size=path.stat().st_size,
                        page_count=len(text_contents) if text_contents else 0,
                        process_dir=str(working_dir),
                        extraction_method=EXTRACTION_MISTRAL_OCR,
                        format="pdf"
                    )
                    result = PDFProcessingResult(
                        metadata=metadata,
                        extracted_text=result_text,
                        ocr_text=None,
                        process_id=self.process_id,
                        images_archive_data=None,
                        images_archive_filename=None,
                    )
                    # mistral_ocr_raw ins dict integrieren
                    obj_dict = result.to_dict()
                    obj_dict['mistral_ocr_raw'] = ocr_json
                    # neue Instanz aus dict, damit frozen bleibt
                    result = PDFProcessingResult.from_dict(obj_dict)
                    # Fortschritt: Verarbeitung im Processor abgeschlossen
                    self.logger.info("Mistral-OCR: Verarbeitung abgeschlossen", progress=90)
                    return self.create_response(
                        processor_name=PROCESSOR_TYPE_PDF,
                        result=result,
                        request_info={
                            'file_path': str(file_path),
                            'template': template,
                            'context': context,
                            'extraction_method': EXTRACTION_MISTRAL_OCR
                        },
                        response_class=PDFResponse,
                        from_cache=False,
                        cache_key=cache_key
                    )
                except Exception as e:
                    # Fortschritt: Fehlerfall melden (Observer leitet als failed weiter)
                    try:
                        self.logger.error(f"Mistral-OCR: Fehler {str(e)}", progress=99)
                    except Exception:
                        pass
                    raise ProcessingError(f"Mistral OCR fehlgeschlagen: {str(e)}")

            # Erstelle Arbeitsverzeichnis, falls es nicht existiert
            if not working_dir.exists():
                working_dir.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Arbeitsverzeichnis angelegt: {str(working_dir)}")
            
            # Prüfe ob es sich um eine URL handelt
            if str(file_path).startswith(('http://', 'https://')):
                # Extrahiere Dateiendung aus URL
                file_extension = self._get_file_extension(str(file_path))
                
                # Validiere die Dateiendung für URLs
                valid_extensions = ['.pdf', '.pptx', '.ppt']
                if file_extension.lower() not in valid_extensions:
                    raise ProcessingError(
                        f"Ungültiges Dateiformat: {file_extension} "
                        f"(Unterstützte Formate: {', '.join(valid_extensions)})"
                    )
                    
                temp_file = working_dir / f"document{file_extension}"
                
                # Prüfe, ob die Datei bereits existiert und nicht überschrieben werden soll
                if temp_file.exists() and not force_overwrite:
                    self.logger.info(f"Datei existiert bereits, überspringe Download: {temp_file}")
                    path = temp_file
                else:
                    self.logger.info(f"Lade Datei herunter: {file_path} (Dateiendung: {file_extension})")
                # Lade Datei von URL herunter
                download_resp2 = requests.get(str(file_path), stream=True)
                download_resp2.raise_for_status()
                
                with open(temp_file, 'wb') as f:
                    for chunk in download_resp2.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                    # Speichere den Originalnamen aus der URL
                    original_name_file = working_dir / "original_name.txt"
                    with open(original_name_file, 'w') as f:
                        f.write(str(file_path))
                
                path = temp_file
            else:
                # Lokale Datei wird direkt verwendet
                path = Path(file_path)
                
                # Speichere den Originalpfad
                original_path_file = working_dir / "original_path.txt"
                if not original_path_file.exists() or force_overwrite:
                    with open(original_path_file, 'w') as f:
                        f.write(str(file_path))
            
            self.logger.info(f"Verarbeite Datei: {path.name}",
                           file_size=path.stat().st_size,
                           working_dir=str(working_dir),
                           extraction_methods=methods_list)
            
            # Dateigröße prüfen
            self.check_file_size(path)
            
            # Dateityp validieren
            self._validate_file_type(path)
            
            # PowerPoint-Konvertierung, falls notwendig
            original_format = None
            if path.suffix.lower() in ['.pptx', '.ppt']:
                self.logger.info(f"PowerPoint-Datei erkannt, konvertiere zu PDF: {path.name}")
                original_format = path.suffix.lower()[1:]  # Speichere das Originalformat ohne Punkt
                pdf_path = path.parent / f"{path.stem}.pdf"
                
                # Nur konvertieren, wenn die PDF-Datei nicht existiert oder Überschreiben erzwungen wird
                if not pdf_path.exists() or force_overwrite:
                    try:
                        self._convert_pptx_to_pdf(path, pdf_path)
                        path = pdf_path
                        self.logger.info(f"PowerPoint erfolgreich in PDF konvertiert: {pdf_path}")
                    except Exception as e:
                        raise ProcessingError(f"Fehler bei der PowerPoint-Konvertierung: {str(e)}")
                else:
                    # Vorhandene konvertierte Datei verwenden
                    path = pdf_path
                    self.logger.info(f"Verwende existierende konvertierte PDF-Datei: {pdf_path}")
            
            # Extraktionsverzeichnis für diese spezifische Verarbeitung
            extraction_subdir_name = f"{'_'.join(methods_list)}"
            if template:
                # Extraktionen mit Template bekommen einen eigenen Ordner
                extraction_subdir_name += f"_{hashlib.md5(template.encode()).hexdigest()[:8]}"
            
            extraction_dir = working_dir / extraction_subdir_name
            if not extraction_dir.exists():
                extraction_dir.mkdir(parents=True, exist_ok=True)
                
            # PDF verarbeiten
            with fitz.open(path) as pdf:
                page_count = len(pdf)
                
                # Seitenzahl prüfen
                if page_count > self.max_pages:
                    raise ProcessingError(
                        f"PDF hat zu viele Seiten: {page_count} "
                        f"(Maximum: {self.max_pages})"
                    )
                
                # Text extrahieren und OCR durchführen
                self.logger.info(f"Starte Extraktion (Methoden: {methods_list})")
                full_text = ""
                ocr_text = ""
                metadata = PDFMetadata(
                    file_name=path.name,
                    file_size=path.stat().st_size,
                    page_count=page_count,
                    process_dir=str(extraction_dir),  # Hier das Extraktionsverzeichnis verwenden
                    extraction_method="_".join(methods_list),  # Kombinierte Methoden
                    format=original_format or "pdf"  # Speichere das Originalformat in den Metadaten
                )
                
                # Listen für Bilder und Vorschaubilder
                all_image_paths: List[str] = []
                all_preview_paths: List[str] = []
                
                for page_num in range(page_count):
                    page = pdf[page_num]  # Zugriff auf PDF-Seite
                    page_started_at: float = time.time()
                    self.logger.info(f"verarbeite Seite {page_num+1}")

                    # ZENTRALE BILDGENERIERUNG - unabhängig von der Extraktionsmethode
                    # Generiere Vorschaubilder, falls gewünscht
                    if EXTRACTION_PREVIEW in methods_list or EXTRACTION_PREVIEW_AND_NATIVE in methods_list:
                        # Vorschaubilder generieren
                        preview_path = self._generate_preview_image(page, page_num, extraction_dir)
                        all_preview_paths.append(preview_path)
                        metadata.preview_paths.append(preview_path)
                    
                    # Generiere Hauptbilder für alle Methoden (wird für Archiv und Visualisierung benötigt)
                    image_path = self._generate_main_image(page, page_num, extraction_dir)
                    all_image_paths.append(image_path)
                    metadata.image_paths.append(image_path)
                    
                    # Verarbeite jede gewünschte Extraktionsmethode
                    if EXTRACTION_NATIVE in methods_list or EXTRACTION_PREVIEW_AND_NATIVE in methods_list:
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                        page_text = cast(str, page_text_raw)
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # Textdaten speichern
                        text_path = self.save_page_text(text=page_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Da PDFMetadata jetzt unveränderlich ist, sammeln wir die Inhalte in temporären Listen
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((int(page_num + 1), str(f"{page_text}")))
                        
                        # Neue PDFMetadata-Instanz erstellen mit aktualisierten text_contents und text_paths
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                    if EXTRACTION_OCR in methods_list:
                        # OCR durchführen - verwende das bereits generierte Hauptbild
                        # OCR mit ImageOCR Processor (nutzt Caching)
                        try:
                            # Verwende den ImageOCR Processor für OCR mit Caching
                            ocr_result = await self.imageocr_processor.process(
                                file_path=str(image_path),  # Verwende das bereits generierte Bild
                                template=None,  # Kein Template für PDF-Seiten
                                context=context,
                                extraction_method="ocr",
                                use_cache=use_cache,  # Cache-Nutzung vom PDF-Processor übernehmen
                                file_hash=None  # Hash wird vom ImageOCR Processor berechnet
                            )
                            
                            if ocr_result.data and ocr_result.data.extracted_text:
                                page_ocr = str(ocr_result.data.extracted_text)
                                
                                # OCR-Text speichern
                                text_path = self.save_page_text(page_ocr, page_num, extraction_dir)
                                
                                # Da PDFMetadata jetzt unveränderlich ist, müssen wir eine neue Instanz erstellen
                                text_paths_list = list(metadata.text_paths)
                                text_paths_list.append(str(text_path))
                                
                                text_contents_list = list(metadata.text_contents)
                                text_contents_list.append((page_num + 1, page_ocr))
                                
                                metadata = PDFMetadata(
                                    file_name=metadata.file_name,
                                    file_size=metadata.file_size,
                                    page_count=metadata.page_count,
                                    format=metadata.format,
                                    process_dir=metadata.process_dir,
                                    image_paths=metadata.image_paths,
                                    preview_paths=metadata.preview_paths,
                                    preview_zip=metadata.preview_zip,
                                    text_paths=text_paths_list,
                                    text_contents=text_contents_list,
                                    extraction_method=metadata.extraction_method
                                )
                                
                                ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                            else:
                                self.logger.warning(f"Kein OCR-Text für Seite {page_num+1} extrahiert")
                                page_ocr = ""
                                
                        except Exception as ocr_error:
                            self.logger.error(f"Fehler bei OCR für Seite {page_num+1}: {str(ocr_error)}")
                            page_ocr = ""
                    
                    if EXTRACTION_LLM in methods_list:
                        # LLM-basierte OCR mit Markdown-Output
                        try:
                            # Erstelle erweiterten Prompt basierend auf Kontext
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            # LLM-OCR für diese Seite
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                            # Text speichern
                            text_path = self.save_page_text(text=llm_text, page_num=page_num, process_dir=extraction_dir)
                            
                            # Metadaten aktualisieren
                            text_paths_list = list(metadata.text_paths)
                            text_paths_list.append(str(text_path))
                            
                            text_contents_list = list(metadata.text_contents)
                            text_contents_list.append((page_num + 1, llm_text))
                            
                            metadata = PDFMetadata(
                                file_name=metadata.file_name,
                                file_size=metadata.file_size,
                                page_count=metadata.page_count,
                                format=metadata.format,
                                process_dir=metadata.process_dir,
                                image_paths=metadata.image_paths,
                                preview_paths=metadata.preview_paths,
                                preview_zip=metadata.preview_zip,
                                text_paths=text_paths_list,
                                text_contents=text_contents_list,
                                extraction_method=metadata.extraction_method
                            )
                            
                            # Füge LLM-Text zum Gesamttext hinzu
                            full_text += f"\n--- Seite {page_num+1} ---\n{llm_text}"
                            
                            self.logger.info(f"LLM-OCR für Seite {page_num+1} abgeschlossen")
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            # Fallback auf native Extraktion
                            page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                            page_text = cast(str, page_text_raw)
                            fallback_text = f"LLM-OCR fehlgeschlagen, Fallback auf native Extraktion:\n\n{page_text}"
                            full_text += f"\n--- Seite {page_num+1} ---\n{fallback_text}"
                    
                    if EXTRACTION_LLM_AND_NATIVE in methods_list:
                        # Kombiniere LLM-OCR mit nativer Text-Extraktion
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                        page_text = cast(str, page_text_raw)
                        
                        # LLM-OCR
                        try:
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                            # Kombiniere beide Texte
                            combined_text = f"=== Native Text ===\n{page_text}\n\n=== LLM Markdown ===\n{llm_text}"
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            combined_text = f"=== Native Text ===\n{page_text}\n\n=== LLM-OCR Fehler ===\n{str(llm_error)}"
                        
                        # Text speichern
                        text_path = self.save_page_text(text=combined_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Metadaten aktualisieren
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((page_num + 1, combined_text))
                        
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # Füge kombinierten Text zum Gesamttext hinzu
                        full_text += f"\n--- Seite {page_num+1} ---\n{combined_text}"
                    
                    if EXTRACTION_LLM_AND_OCR in methods_list:
                        # Kombiniere LLM-OCR mit Tesseract OCR
                        llm_text = ""
                        tesseract_text = ""
                        
                        # LLM-OCR
                        try:
                            custom_prompt = None
                            if context:
                                document_type = context.get('document_type')
                                language = context.get('language', 'de')
                                custom_prompt = self.image2text_service.create_enhanced_prompt(
                                    context=context,
                                    document_type=document_type,
                                    language=language
                                )
                            
                            llm_text, llm_request = self.image2text_service.extract_text_from_pdf_page(
                                page=page,
                                page_num=page_num,
                                custom_prompt=custom_prompt,
                                logger=self.logger
                            )
                            
                            # LLM-Request zum Tracking hinzufügen
                            self.add_llm_requests([llm_request])
                            
                        except Exception as llm_error:
                            self.logger.error(f"Fehler bei LLM-OCR für Seite {page_num+1}: {str(llm_error)}")
                            llm_text = f"LLM-OCR Fehler: {str(llm_error)}"
                        
                        # Tesseract OCR - verwende das bereits generierte Hauptbild
                        try:
                            ocr_result = await self.imageocr_processor.process(
                                file_path=str(image_path),  # Verwende das bereits generierte Bild
                                template=None,
                                context=context,
                                extraction_method="ocr",
                                use_cache=use_cache,
                                file_hash=None
                            )
                            
                            if ocr_result.data and ocr_result.data.extracted_text:
                                tesseract_text = str(ocr_result.data.extracted_text)
                            
                        except Exception as ocr_error:
                            self.logger.error(f"Fehler bei Tesseract OCR für Seite {page_num+1}: {str(ocr_error)}")
                            tesseract_text = f"Tesseract OCR Fehler: {str(ocr_error)}"
                        
                        # Kombiniere beide OCR-Ergebnisse
                        combined_ocr_text = f"=== LLM Markdown ===\n{llm_text}\n\n=== Tesseract OCR ===\n{tesseract_text}"
                        
                        # Text speichern
                        text_path = self.save_page_text(text=combined_ocr_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Metadaten aktualisieren
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((page_num + 1, combined_ocr_text))
                        
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # Füge kombinierten Text zum OCR-Text hinzu
                        ocr_text += f"\n--- Seite {page_num+1} ---\n{combined_ocr_text}"
                    
                    if EXTRACTION_BOTH in methods_list:
                        # Beide Extraktionsmethoden (native + OCR)
                        # Native Text-Extraktion
                        page_text_raw = page.get_text()  # type: ignore # PyMuPDF Methode
                        page_text = cast(str, page_text_raw)
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # Textdaten speichern
                        text_path = self.save_page_text(text=page_text, page_num=page_num, process_dir=extraction_dir)
                        
                        # Da PDFMetadata jetzt unveränderlich ist, sammeln wir die Inhalte in temporären Listen
                        text_paths_list = list(metadata.text_paths)
                        text_paths_list.append(str(text_path))
                        
                        text_contents_list = list(metadata.text_contents)
                        text_contents_list.append((int(page_num + 1), str(f"{page_text}")))
                        
                        # Neue PDFMetadata-Instanz erstellen mit aktualisierten text_contents und text_paths
                        metadata = PDFMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            page_count=metadata.page_count,
                            format=metadata.format,
                            process_dir=metadata.process_dir,
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            preview_zip=metadata.preview_zip,
                            text_paths=text_paths_list,
                            text_contents=text_contents_list,
                            extraction_method=metadata.extraction_method
                        )
                        
                        # OCR mit ImageOCR Processor (nutzt Caching) - verwende das bereits generierte Hauptbild
                        try:
                            # Verwende den ImageOCR Processor für OCR mit Caching
                            ocr_result = await self.imageocr_processor.process(
                                file_path=str(image_path),  # Verwende das bereits generierte Bild
                                template=None,  # Kein Template für PDF-Seiten
                                context=context,
                                extraction_method="ocr",
                                use_cache=use_cache,  # Cache-Nutzung vom PDF-Processor übernehmen
                                file_hash=None  # Hash wird vom ImageOCR Processor berechnet
                            )
                            
                            if ocr_result.data and ocr_result.data.extracted_text:
                                page_ocr = str(ocr_result.data.extracted_text)
                                
                                # OCR-Text speichern
                                text_path = self.save_page_text(page_ocr, page_num, extraction_dir)
                                
                                # Da PDFMetadata jetzt unveränderlich ist, müssen wir eine neue Instanz erstellen
                                text_paths_list = list(metadata.text_paths)
                                text_paths_list.append(str(text_path))
                                
                                text_contents_list = list(metadata.text_contents)
                                text_contents_list.append((page_num + 1, page_ocr))
                                
                                metadata = PDFMetadata(
                                    file_name=metadata.file_name,
                                    file_size=metadata.file_size,
                                    page_count=metadata.page_count,
                                    format=metadata.format,
                                    process_dir=metadata.process_dir,
                                    image_paths=metadata.image_paths,
                                    preview_paths=metadata.preview_paths,
                                    preview_zip=metadata.preview_zip,
                                    text_paths=text_paths_list,
                                    text_contents=text_contents_list,
                                    extraction_method=metadata.extraction_method
                                )
                                
                                ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                            else:
                                self.logger.warning(f"Kein OCR-Text für Seite {page_num+1} extrahiert")
                                page_ocr = ""
                                
                        except Exception as ocr_error:
                            self.logger.error(f"Fehler bei OCR für Seite {page_num+1}: {str(ocr_error)}")
                            page_ocr = ""
                    
                    # Logging
                    page_duration: float = time.time() - page_started_at
                    self.logger.info(f"Seite {page_num + 1} verarbeitet",
                                    duration=page_duration,
                                    extraction_methods=methods_list)
                
                # Wenn Vorschaubilder generiert wurden, diese als ZIP verpacken
                preview_zip_path: Optional[str] = None
                if metadata.preview_paths:
                    import zipfile
                    zip_path: Path = extraction_dir / "previews.zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for preview_path_str in metadata.preview_paths:
                            preview_path_obj = Path(str(preview_path_str))
                            zipf.write(str(preview_path_obj), preview_path_obj.name)
                    preview_zip_path = str(zip_path)
                
                # Aktualisierte Metadata-Instanz mit ZIP-Pfad erstellen
                metadata = PDFMetadata(
                    file_name=metadata.file_name,
                    file_size=metadata.file_size,
                    page_count=metadata.page_count,
                    format=metadata.format,
                    process_dir=metadata.process_dir,
                    image_paths=metadata.image_paths,
                    preview_paths=metadata.preview_paths,
                    preview_zip=preview_zip_path,
                    text_paths=metadata.text_paths,
                    text_contents=metadata.text_contents,
                    extraction_method=metadata.extraction_method
                )
                
                # Template-Transformation, falls Template angegeben
                result_text = full_text
                if template and (full_text or ocr_text):
                    try:
                        # Transformiere den Text mit dem angegebenen Template
                        # Bei mehreren Extraktionsmethoden wählen wir den besten verfügbaren Text
                        source_text = ""
                        if EXTRACTION_NATIVE in methods_list or EXTRACTION_BOTH in methods_list:
                            source_text = full_text  # Bevorzuge immer den nativen Text
                        elif EXTRACTION_OCR in methods_list:
                            source_text = ocr_text   # Verwende OCR-Text, wenn kein nativer Text verfügbar
                        
                        if not source_text:
                            self.logger.warning("Kein Text für Template-Transformation verfügbar")
                        else:
                            # Wir passen den Aufruf an die tatsächliche Schnittstelle an
                            transformation_result = await self.transformer.transform(  # type: ignore
                                source_text=source_text,
                                source_language="auto",  # Automatische Erkennung
                                target_language="de",    # Standardmäßig Deutsch
                                template_name=template,  # type: ignore  # Parameter kann unterschiedlich benannt sein
                                context=context or {}
                            )
                            
                            if transformation_result and hasattr(transformation_result, 'data'):  # type: ignore
                                transformed_data = getattr(transformation_result, 'data', None)  # type: ignore
                                if transformed_data and hasattr(transformed_data, 'transformed_text'):
                                    result_text = getattr(transformed_data, 'transformed_text', result_text)
                                
                    except Exception as e:
                        self.logger.warning(f"Fehler bei der Template-Transformation: {str(e)}")
                
                # Bilder-Archiv erstellen, falls gewünscht und Bilder vorhanden
                images_archive_data = None
                images_archive_filename = None
                
                if include_images and (metadata.image_paths or metadata.preview_paths):
                    try:
                        images_archive_data, images_archive_filename = self._create_images_archive(
                            image_paths=metadata.image_paths,
                            preview_paths=metadata.preview_paths,
                            file_name=path.name
                        )
                        self.logger.debug(f"Bilder-Archiv erstellt: {images_archive_filename}")
                    except Exception as e:
                        self.logger.warning(f"Bilder-Archiv konnte nicht erstellt werden: {str(e)}")
                        # Fehlschlag ist nicht kritisch, Verarbeitung fortsetzen
                
                # Erstelle Endergebnis
                result = PDFProcessingResult(
                    metadata=metadata,
                    extracted_text=result_text if (EXTRACTION_NATIVE in methods_list or 
                                                  EXTRACTION_BOTH in methods_list or 
                                                  EXTRACTION_LLM in methods_list or 
                                                  EXTRACTION_LLM_AND_NATIVE in methods_list or 
                                                  EXTRACTION_LLM_AND_OCR in methods_list) else None,
                    ocr_text=ocr_text if EXTRACTION_OCR in methods_list or EXTRACTION_BOTH in methods_list else None,
                    process_id=self.process_id,
                    images_archive_data=images_archive_data,
                    images_archive_filename=images_archive_filename
                )
            
                # Konvertiere Dateipfade in URLs für die API-Antwort
                self._convert_paths_to_urls(result)
                
                # Stelle sicher, dass text_contents vorhanden sind - extrahiere sie aus dem extracted_text, falls notwendig
                if hasattr(result.metadata, 'text_contents') and not result.metadata.text_contents and result.extracted_text:
                    # Da PDFMetadata unveränderlich ist, erstellen wir eine neue Instanz
                    new_text_contents = self._extract_text_contents_from_full_text(result.extracted_text)
                    
                    # Neue Metadata-Instanz erstellen
                    updated_metadata = PDFMetadata(
                        file_name=result.metadata.file_name,
                        file_size=result.metadata.file_size,
                        page_count=result.metadata.page_count,
                        format=result.metadata.format,
                        process_dir=result.metadata.process_dir,
                        image_paths=result.metadata.image_paths,
                        preview_paths=result.metadata.preview_paths,
                        preview_zip=result.metadata.preview_zip,
                        text_paths=result.metadata.text_paths,
                        original_text_paths=result.metadata.original_text_paths,
                        text_contents=new_text_contents,
                        extraction_method=result.metadata.extraction_method
                    )
                    
                    # Da wir ein unveränderliches PDFProcessingResult haben, verwenden wir object.__setattr__
                    object.__setattr__(result, 'metadata', updated_metadata)
                
                # Cache-Speicherung, falls aktiviert
                if use_cache and self.is_cache_enabled():
                    # Cache-Speicherung mit der korrekten Methode aus der Basisklasse
                    self.save_to_cache(cache_key, result)  # type: ignore
                
                # Erstelle und gib Response zurück
                return self.create_response(
                    processor_name=PROCESSOR_TYPE_PDF,
                    result=result,
                    request_info={
                        'file_path': str(file_path),
                        'template': template,
                        'context': context,
                        'extraction_method': "_".join(methods_list)  # Korrekter kombinierter String
                    },
                    response_class=PDFResponse,
                    from_cache=False,
                    cache_key=cache_key
                )

        except Exception as e:
            # Benutzerfreundliche Fehlertexte an der Quelle
            friendly_code = type(e).__name__
            friendly_message = str(e)
            details: Dict[str, Any] = {
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }

            # HTTP-/Netzwerkfehler benutzerfreundlich formulieren
            if isinstance(e, requests.exceptions.HTTPError):
                status_code = None
                try:
                    status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                except Exception:
                    status_code = None
                url_hint = str(file_path)
                if status_code == 404:
                    friendly_code = "URL_NOT_FOUND"
                    friendly_message = (
                        f"Die angegebene URL wurde nicht gefunden (404). "
                        f"Bitte prüfen Sie die Adresse: {url_hint}"
                    )
                else:
                    friendly_code = "HTTP_ERROR"
                    friendly_message = (
                        f"Die Datei konnte nicht heruntergeladen werden"
                        f"{f' (HTTP {status_code})' if status_code else ''}. "
                        f"Bitte prüfen Sie die URL: {url_hint}"
                    )
                details.update({
                    "status_code": status_code,
                    "url": url_hint,
                    "original_error": str(e)
                })
            elif isinstance(e, requests.exceptions.ConnectionError):
                friendly_code = "NETWORK_ERROR"
                friendly_message = (
                    "Es konnte keine Netzwerkverbindung zum Server aufgebaut werden. "
                    "Bitte prüfen Sie Ihre Verbindung oder die Ziel-URL."
                )
            elif isinstance(e, requests.exceptions.Timeout):
                friendly_code = "TIMEOUT"
                friendly_message = (
                    "Der Download der Datei hat zu lange gedauert (Timeout). "
                    "Bitte versuchen Sie es später erneut oder prüfen Sie die URL."
                )

            error_info = ErrorInfo(
                code=friendly_code,
                message=friendly_message,
                details=details
            )
            self.logger.error(f"Fehler bei der Verarbeitung: {friendly_message}")
            
            # Dummy-Result für den Fehlerfall
            dummy_result = PDFProcessingResult(
                metadata=PDFMetadata(
                    file_name=str(file_path).split('/')[-1],
                    file_size=0,
                    page_count=0,
                    process_dir=str(working_dir)
                ),
                extracted_text="",
                process_id=self.process_id
            )
            
            return self.create_response(
                processor_name=PROCESSOR_TYPE_PDF,
                result=dummy_result,
                request_info={
                    'file_path': str(file_path),
                    'template': template,
                    'context': context,
                    'extraction_method': "_".join(methods_list)  # Korrekter kombinierter String
                },
                response_class=PDFResponse,
                error=error_info,
                from_cache=False,
                cache_key=cache_key
            )

    def check_file_size(self, file_path: Path) -> None:
        """Prüft ob die Dateigröße innerhalb der Limits liegt."""
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            raise ProcessingError(
                f"Datei zu groß: {file_size} Bytes "
                f"(Maximum: {self.max_file_size} Bytes)"
            )

    def cleanup_old_files(self, max_age_hours: int = 24):
        """Löscht alte temporäre Dateien.

        Args:
            max_age_hours (int): Maximales Alter der Dateien in Stunden
        """
        try:
            current_time: float = time.time()
            for process_dir in self.temp_dir.glob("*"):
                if process_dir.is_dir():
                    dir_time = float(process_dir.name)  # Verzeichnisname ist Timestamp
                    if current_time - dir_time > max_age_hours * 3600:
                        # Verzeichnis ist älter als max_age_hours
                        for file in process_dir.glob("*"):
                            file.unlink()
                        process_dir.rmdir()
        except Exception as e:
            print(f"Fehler beim Aufräumen: {str(e)}")

    def _convert_paths_to_urls(self, result: PDFProcessingResult) -> None:
        """
        Konvertiert Dateipfade in URLs, die über die API zugänglich sind.
        
        Args:
            result: Das PDFProcessingResult, dessen Pfade konvertiert werden sollen
        """
        # Basis-URL für den Textinhalt
        base_url = "/api/pdf/text-content/"
        
        # Konvertiere text_paths in URLs für API-Zugriffsrouten
        if hasattr(result.metadata, 'text_paths') and result.metadata.text_paths:
            # Da PDFMetadata unveränderlich ist, erstellen wir neue Listen
            new_text_paths: List[str] = []
            original_text_paths = list(result.metadata.original_text_paths)  # Kopie der vorhandenen Liste

            # Konvertiere alle Pfade zu URLs
            for path in result.metadata.text_paths:
                # Speichere den originalen Pfad
                original_text_paths.append(path)
                
                # Ersetze backslashes durch forward slashes und erstelle die URL
                normalized_path = str(path).replace('\\', '/')
                new_text_paths.append(f"{base_url}{normalized_path}")
            
            # Erstelle eine neue Metadata-Instanz mit den aktualisierten Pfaden
            updated_metadata = PDFMetadata(
                file_name=result.metadata.file_name,
                file_size=result.metadata.file_size,
                page_count=result.metadata.page_count,
                format=result.metadata.format,
                process_dir=result.metadata.process_dir,
                image_paths=result.metadata.image_paths,
                preview_paths=result.metadata.preview_paths,
                preview_zip=result.metadata.preview_zip,
                text_paths=new_text_paths,
                original_text_paths=original_text_paths,
                text_contents=result.metadata.text_contents,
                extraction_method=result.metadata.extraction_method
            )
            
            # Erstelle eine neue PDFProcessingResult-Instanz mit der aktualisierten Metadata
            object.__setattr__(result, 'metadata', updated_metadata)
        
        # Wenn text_contents leer ist, aber extracted_text vorhanden ist,
        # extrahiere die text_contents aus dem extracted_text
        if hasattr(result.metadata, 'text_contents') and not result.metadata.text_contents and result.extracted_text:
            # Da PDFMetadata unveränderlich ist, erstellen wir eine neue Instanz
            new_text_contents = self._extract_text_contents_from_full_text(result.extracted_text)
            
            # Neue Metadata-Instanz erstellen
            updated_metadata = PDFMetadata(
                file_name=result.metadata.file_name,
                file_size=result.metadata.file_size,
                page_count=result.metadata.page_count,
                format=result.metadata.format,
                process_dir=result.metadata.process_dir,
                image_paths=result.metadata.image_paths,
                preview_paths=result.metadata.preview_paths,
                preview_zip=result.metadata.preview_zip,
                text_paths=result.metadata.text_paths,
                original_text_paths=result.metadata.original_text_paths,
                text_contents=new_text_contents,
                extraction_method=result.metadata.extraction_method
            )
            
            # Da wir ein unveränderliches PDFProcessingResult haben, verwenden wir object.__setattr__
            object.__setattr__(result, 'metadata', updated_metadata)

    def _extract_text_contents_from_full_text(self, extracted_text: Optional[str]) -> List[Tuple[int, str]]:
        """
        Extrahiert strukturierte Textinhalte aus dem extrahierten Volltext basierend auf den Seitenmarkierungen.
        
        Args:
            extracted_text: Der vollständige extrahierte Text mit Seitenmarkierungen
            
        Returns:
            Eine Liste von Tupeln (Seitennummer, Seiteninhalt)
        """
        if not extracted_text:
            return []
            
        text_contents: List[Tuple[int, str]] = []
        import re
        
        # Regex um Blöcke zu finden, die mit "--- Seite X ---" beginnen
        pattern = r"(?:^|\n)--- Seite (\d+) ---\n(.*?)(?=(?:\n--- Seite \d+ ---|$))"
        matches = re.findall(pattern, extracted_text, re.DOTALL)
        
        for page_num_str, content in matches:
            try:
                page_num = int(page_num_str)
                text_contents.append((page_num, content.strip()))
            except ValueError:
                # Wenn die Seitennummer nicht geparst werden kann, überspringen
                continue
                
        return text_contents

    def _create_images_archive(
        self,
        image_paths: List[str],
        preview_paths: List[str],
        file_name: str
    ) -> Tuple[str, str]:
        """
        Erstellt ein ZIP-Archiv mit allen generierten Bildern.
        
        Args:
            image_paths: Liste der Pfade zu den Hauptbildern
            preview_paths: Liste der Pfade zu den Vorschaubildern
            file_name: Name der ursprünglichen PDF-Datei
            
        Returns:
            Tuple aus (Base64-kodiertes ZIP-Archiv, Archiv-Dateiname)
        """
        import zipfile
        import io
        import base64
        from pathlib import Path
        
        # ZIP-Archiv im Speicher erstellen
        zip_buffer = io.BytesIO()
        
        # Archiv-Dateiname generieren
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_filename = f"{Path(file_name).stem}_images_{timestamp}.zip"
        
        try:
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                
                # 1. Hauptbilder hinzufügen
                successful_main_images = 0
                failed_main_images = 0
                
                for image_path in image_paths:
                    try:
                        image_path_obj = Path(image_path)
                        if image_path_obj.exists():
                            # Bild flach ohne Verzeichnis zum ZIP hinzufügen
                            zip_path = image_path_obj.name
                            zip_file.write(str(image_path_obj), zip_path)
                            successful_main_images += 1
                            self.logger.debug(f"Hauptbild zum ZIP hinzugefügt: {zip_path}")
                        else:
                            self.logger.warning(f"Hauptbild nicht gefunden: {image_path}")
                            failed_main_images += 1
                    except Exception as e:
                        self.logger.warning(f"Fehler beim Hinzufügen des Hauptbilds {image_path}: {str(e)}")
                        failed_main_images += 1
                
                # 2. Vorschaubilder hinzufügen
                successful_preview_images = 0
                failed_preview_images = 0
                
                for preview_path in preview_paths:
                    try:
                        preview_path_obj = Path(preview_path)
                        if preview_path_obj.exists():
                            # Vorschaubild flach ohne Verzeichnis zum ZIP hinzufügen
                            zip_path = preview_path_obj.name
                            zip_file.write(str(preview_path_obj), zip_path)
                            successful_preview_images += 1
                            self.logger.debug(f"Vorschaubild zum ZIP hinzugefügt: {zip_path}")
                        else:
                            self.logger.warning(f"Vorschaubild nicht gefunden: {preview_path}")
                            failed_preview_images += 1
                    except Exception as e:
                        self.logger.warning(f"Fehler beim Hinzufügen des Vorschaubilds {preview_path}: {str(e)}")
                        failed_preview_images += 1
                
                self.logger.info(
                    f"Bilder-Archiv erstellt: {successful_main_images} Hauptbilder, "
                    f"{successful_preview_images} Vorschaubilder, "
                    f"{failed_main_images + failed_preview_images} fehlgeschlagen"
                )
            
            # ZIP-Inhalt als Base64 kodieren
            zip_buffer.seek(0)
            zip_bytes = zip_buffer.read()
            archive_data = base64.b64encode(zip_bytes).decode('utf-8')
            
            return archive_data, archive_filename
            
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen des Bilder-Archives: {str(e)}")
            raise ProcessingError(f"Fehler beim Erstellen des Bilder-Archives: {str(e)}")
        finally:
            zip_buffer.close()

