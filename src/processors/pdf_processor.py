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
from dataclasses import dataclass
import subprocess
import os
from urllib.parse import urlparse
import fitz  # type: ignore
import pytesseract  # type: ignore
import requests

from src.processors.cacheable_processor import CacheableProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.core.config import Config
from src.core.models.base import ErrorInfo, BaseResponse
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.response_factory import ResponseFactory
from src.core.models.pdf import PDFMetadata
from src.processors.transformer_processor import TransformerProcessor

# Konstanten für Processor-Typen
PROCESSOR_TYPE_PDF = "pdf"

# Konstanten für Extraktionsmethoden
EXTRACTION_NATIVE = "native"  # Nur native Text-Extraktion
EXTRACTION_OCR = "ocr"       # Nur OCR
EXTRACTION_BOTH = "both"     # Beide Methoden kombinieren
EXTRACTION_PREVIEW = "preview"
EXTRACTION_PREVIEW_AND_NATIVE = "preview_and_native"  # Vorschaubilder und native Text-Extraktion

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

@dataclass
class PDFProcessingResult:
    """Ergebnis der PDF-Verarbeitung."""
    metadata: PDFMetadata
    extracted_text: Optional[str]
    ocr_text: Optional[str] = None
    process_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'extracted_text': self.extracted_text,
            'ocr_text': self.ocr_text,
            'process_id': self.process_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PDFProcessingResult':
        """Erstellt ein PDFProcessingResult aus einem Dictionary."""
        from src.core.models.pdf import PDFMetadata
        
        # Metadaten direkt aus dem Dictionary extrahieren
        metadata_dict: Dict[str, Any] = data.get('metadata', {})
        
        # Vorsichtige Konvertierung für den Linter
        file_name = str(metadata_dict.get('file_name', ''))  # type: ignore
        file_size = int(metadata_dict.get('file_size', 0))  # type: ignore
        page_count = int(metadata_dict.get('page_count', 0))  # type: ignore
        
        # Text contents verarbeiten, falls vorhanden
        text_contents: List[Tuple[int, str]] = []
        raw_text_contents: List[Any] = metadata_dict.get('text_contents', [])
        
        # Hilfsfunktion zur typensicheren Konvertierung
        def create_typed_content(page: Any, content: Any) -> Tuple[int, str]:
            """Erstellt ein typensicheres Tuple aus Seitennummer und Inhalt."""
            return (int(page), str(content))
        
        # Verarbeite jedes Element in raw_text_contents
        for item in raw_text_contents:
            if isinstance(item, dict) and 'page' in item and 'content' in item:
                text_contents.append(create_typed_content(item['page'], item['content']))
            elif isinstance(item, tuple) and len(cast(Tuple[Any, ...], item)) == 2:
                text_contents.append(create_typed_content(item[0], item[1]))
        
        # PDFMetadata erstellen
        metadata = PDFMetadata(
            file_name=file_name,
            file_size=file_size,
            page_count=page_count,
            format=str(metadata_dict.get('format', 'pdf')),  # type: ignore
            process_dir=metadata_dict.get('process_dir'),  # type: ignore
            image_paths=list(metadata_dict.get('image_paths', [])),  # type: ignore
            preview_paths=list(metadata_dict.get('preview_paths', [])),  # type: ignore
            preview_zip=metadata_dict.get('preview_zip'),  # type: ignore
            text_paths=list(metadata_dict.get('text_paths', [])),  # type: ignore
            text_contents=text_contents,
            extraction_method=str(metadata_dict.get('extraction_method', 'native'))  # type: ignore
        )
        
        return cls(
            metadata=metadata,
            extracted_text=data.get('extracted_text'),
            ocr_text=data.get('ocr_text'),
            process_id=data.get('process_id')
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
    
    Verwendet MongoDB-Caching zur effizienten Wiederverwendung von Verarbeitungsergebnissen.
    """
    
    # Name der MongoDB-Cache-Collection
    cache_collection_name = "pdf_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        """Initialisiert den PDFProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
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
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
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
        text_path = process_dir / f"page_{page_num+1}.txt"
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
            
    def _create_response_from_cached_result(self, 
                                           cached_result: PDFProcessingResult,
                                           file_path: Union[str, Path],
                                           template: Optional[str] = None,
                                           context: Optional[Dict[str, Any]] = None,
                                           extraction_method: str = EXTRACTION_NATIVE,
                                           file_hash: Optional[str] = None) -> PDFResponse:
        """
        Erstellt eine PDFResponse aus einem gecachten Ergebnis.
        
        Args:
            cached_result: Das gecachte PDFProcessingResult
            file_path: Der ursprüngliche Dateipfad
            template: Optional, das verwendete Template
            context: Optional, der Kontext für die Verarbeitung
            extraction_method: Die verwendete Extraktionsmethode
            file_hash: Optional, ein vorberechneter Hash der Datei
            
        Returns:
            PDFResponse: Die Response mit dem gecachten Ergebnis
        """
        # Resource-Tracking für den Cache-Hit
        # Tracking der Cache-Hit-Zeit (praktisch 0)
        if hasattr(self.resource_calculator, 'add_processing_time'):
            self.resource_calculator.add_processing_time("pdf_cache_hit", 0.0)
        
        # Tracking des Cache-Zugriffs
        if hasattr(self.resource_calculator, 'add_api_call'):
            self.resource_calculator.add_api_call("pdf_cache_retrieval")
        
        # Response erstellen
        return ResponseFactory.create_response(
            processor_name="pdf",
            result=cached_result,
            request_info={
                "file_path": str(file_path),
                "template": template,
                "extraction_method": extraction_method,
                "context": context
            },
            response_class=PDFResponse,
            llm_info=None,
            from_cache=True
        )

    async def process(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        extraction_method: Union[str, list[str]] = EXTRACTION_NATIVE,
        use_cache: bool = True,
        file_hash: Optional[str] = None,
        force_overwrite: bool = False
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
        
        # Initialisiere LLM-Info außerhalb des try-blocks
        llm_info = LLMInfo(
            model="pdf-processing",
            purpose="pdf-processing"
        )
        
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
                    return ResponseFactory.create_response(
                        processor_name="pdf",
                        result=cached_result,
                        request_info={
                            "file_path": str(file_path),
                            "template": template,
                            "context": context,
                            "extraction_method": extraction_method
                        },
                        response_class=PDFResponse,
                        llm_info=None,
                        from_cache=True  # Hier auf True gesetzt, da aus dem Cache
                    )

            # Validiere alle Extraktionsmethoden
            valid_methods = [EXTRACTION_NATIVE, EXTRACTION_OCR, EXTRACTION_BOTH, EXTRACTION_PREVIEW]
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
                temp_file = working_dir / f"document{file_extension}"
                
                # Prüfe, ob die Datei bereits existiert und nicht überschrieben werden soll
                if temp_file.exists() and not force_overwrite:
                    self.logger.info(f"Datei existiert bereits, überspringe Download: {temp_file}")
                    path = temp_file
                else:
                    self.logger.info(f"Lade Datei herunter: {file_path} (Dateiendung: {file_extension})")
                # Lade Datei von URL herunter
                response: requests.Response = requests.get(str(file_path), stream=True)
                response.raise_for_status()
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
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
            
            # Extraktionsverzeichnis für diese spezifische Verarbeitung
            # Unterschiedlich je nach Extraktionsmethode, Template und Kontext
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
                self.logger.debug(f"Starte Extraktion (Methoden: {methods_list})")
                start_time = datetime.now()
                full_text = ""
                ocr_text = ""
                metadata = PDFMetadata(
                    file_name=path.name,
                    file_size=path.stat().st_size,
                    page_count=page_count,
                    process_dir=str(extraction_dir),  # Hier das Extraktionsverzeichnis verwenden
                    extraction_method="_".join(methods_list)  # Kombinierte Methoden
                )
                
                for page_num in range(page_count):
                    page = pdf[page_num]  # Zugriff auf PDF-Seite
                    page_start = time.time()
                    
                    # Verarbeite jede gewünschte Extraktionsmethode
                    if EXTRACTION_PREVIEW in methods_list or EXTRACTION_PREVIEW_AND_NATIVE in methods_list:
                        # Vorschaubilder generieren
                        preview_path = self._generate_preview_image(page, page_num, extraction_dir)
                        metadata.preview_paths.append(preview_path)
                        
                    if EXTRACTION_NATIVE in methods_list or EXTRACTION_PREVIEW_AND_NATIVE in methods_list:
                        # Native Text-Extraktion
                        page_text = page.get_text()  # type: ignore # PyMuPDF Methode
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # Speichere den extrahierten Text
                        text_path = self.save_page_text(page_text, page_num, extraction_dir)  # type: ignore
                        metadata.text_paths.append(str(text_path))
                        # Speichere auch den Textinhalt direkt in den Metadaten
                        metadata.text_contents.append((int(page_num + 1), str(f"{page_text}")))
                        
                        # Generiere auch Hauptbilder für die Visualisierung
                        image_path = self._generate_main_image(page, page_num, extraction_dir)
                        metadata.image_paths.append(image_path)
                        
                    if EXTRACTION_OCR in methods_list:
                        # OCR durchführen
                        # Generiere Hauptbild mit höherer Auflösung für OCR
                        page_rect = page.rect  # type: ignore
                        # 300 DPI für OCR
                        scale_factor = 300/72
                        matrix = fitz.Matrix(scale_factor, scale_factor)
                        
                        pix = page.get_pixmap(matrix=matrix)  # type: ignore # PyMuPDF Methode
                        image_path = extraction_dir / f"page_{page_num+1}.png"
                        pix.save(str(image_path))  # type: ignore
                        metadata.image_paths.append(str(image_path))
                        
                        # OCR mit Tesseract
                        try:
                            import PIL.Image as Image
                            img = Image.open(image_path)
                            try:
                                # Hinweis: pytesseract.image_to_string wird mit type-ignore markiert,
                                # da die Typdefinitionen nicht mit der tatsächlichen Implementierung übereinstimmen
                                page_ocr = str(pytesseract.image_to_string(  # type: ignore
                                    image=img,
                                    lang='deu',  # Deutsche Sprache
                                    config='--psm 3'  # Standard Page Segmentation Mode
                                ))
                            except Exception as ocr_error:
                                self.logger.warning(
                                    "Fehler bei deutscher OCR, versuche Englisch als Fallback",
                                    error=str(ocr_error)
                                )
                                page_ocr = str(pytesseract.image_to_string(  # type: ignore
                                    image=img,
                                    lang='eng',  # Englisch als Fallback
                                    config='--psm 3'
                                ))
                            
                            # OCR-Text speichern
                            text_path = self.save_page_text(str(page_ocr), page_num, extraction_dir)
                            metadata.text_paths.append(str(text_path))
                            # Speichere auch den OCR-Textinhalt direkt in den Metadaten
                            metadata.text_contents.append((page_num + 1, str(page_ocr)))
                            ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                            
                            # Ressourcen freigeben
                            img.close()
                        except ImportError:
                            self.logger.error("PIL nicht installiert, OCR nicht möglich")
                            raise ProcessingError("PIL nicht installiert, OCR nicht möglich")
                        
                        # Ressourcen freigeben
                        del pix
                    
                    if EXTRACTION_BOTH in methods_list:
                        # Beide Extraktionsmethoden (native + OCR)
                        # Native Text-Extraktion
                        page_text = page.get_text()  # type: ignore # PyMuPDF Methode
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # Speichere den extrahierten Text
                        text_path = self.save_page_text(page_text, page_num, extraction_dir)  # type: ignore
                        metadata.text_paths.append(str(text_path))
                        
                        # Generiere auch Hauptbilder mit höherer Auflösung für OCR
                        page_rect = page.rect  # type: ignore
                        # 300 DPI für OCR
                        scale_factor = 300/72
                        matrix = fitz.Matrix(scale_factor, scale_factor)
                        
                        pix = page.get_pixmap(matrix=matrix)  # type: ignore # PyMuPDF Methode
                        image_path = extraction_dir / f"page_{page_num+1}.png"
                        pix.save(str(image_path))  # type: ignore
                        metadata.image_paths.append(str(image_path))
                        
                        # OCR mit Tesseract
                        try:
                            import PIL.Image as Image
                            img = Image.open(image_path)
                            try:
                                page_ocr = str(pytesseract.image_to_string(  # type: ignore
                                    image=img,
                                    lang='deu',  # Deutsche Sprache
                                    config='--psm 3'  # Standard Page Segmentation Mode
                                ))
                            except Exception as ocr_error:
                                self.logger.warning(
                                    "Fehler bei deutscher OCR, versuche Englisch als Fallback",
                                    error=str(ocr_error)
                                )
                                page_ocr = str(pytesseract.image_to_string(  # type: ignore
                                    image=img,
                                    lang='eng',  # Englisch als Fallback
                                    config='--psm 3'
                                ))
                            
                            # OCR-Text speichern
                            # Prüfen, ob das Verzeichnis existiert
                            ocr_dir = extraction_dir / "ocr"
                            if not ocr_dir.exists():
                                ocr_dir.mkdir(parents=True)
                            ocr_text_path = self.save_page_text(str(page_ocr), page_num, ocr_dir)
                            metadata.text_paths.append(str(ocr_text_path))
                            ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                            
                            # Ressourcen freigeben
                            img.close()
                        except ImportError:
                            self.logger.error("PIL nicht installiert, OCR nicht möglich")
                            raise ProcessingError("PIL nicht installiert, OCR nicht möglich")
                        
                        # Ressourcen freigeben
                        del pix
                    
                    # Logging
                    page_duration = time.time() - page_start
                    self.logger.debug(f"Seite {page_num + 1} verarbeitet",
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
                
                # LLM-Tracking für OCR berechnen, wenn OCR verwendet wurde
                if EXTRACTION_OCR in methods_list or EXTRACTION_BOTH in methods_list:
                    try:
                        # Einfaches Tracking für OCR-Kosten
                        # Wir gehen von einem symbolischen Wert aus, der später angepasst werden kann
                        ocr_token_estimate = len(ocr_text.split()) * 1.5  # Grobe Schätzung
                        ocr_duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                        
                        # Erstelle ein LLMRequest-Objekt mit den richtigen Parametern
                        llm_request = LLMRequest(
                            model="tesseract",
                            purpose="ocr_extraction",
                            tokens=int(ocr_token_estimate),
                            duration=int(ocr_duration_ms)
                        )
                        
                        # Füge das Objekt zur LLMInfo hinzu
                        llm_info.add_request([llm_request])
                    except Exception as e:
                        self.logger.warning(f"Fehler beim LLM-Tracking für OCR: {str(e)}")
                
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
                                
                                # LLM-Tracking für Template-Transformation
                                process_info = getattr(transformation_result, 'process', None)  # type: ignore
                                if process_info and hasattr(process_info, 'llm_info'):
                                    transform_llm_info = getattr(process_info, 'llm_info', None)
                                    if transform_llm_info and hasattr(transform_llm_info, 'requests'):
                                        transform_requests = getattr(transform_llm_info, 'requests', [])
                                        if transform_requests:
                                            # Die Requests direkt hinzufügen, wenn es LLMRequest-Objekte sind
                                            llm_info.add_request(transform_requests)
                    except Exception as e:
                        self.logger.warning(f"Fehler bei der Template-Transformation: {str(e)}")
                
                # Erstelle Endergebnis
                result = PDFProcessingResult(
                    metadata=metadata,
                    extracted_text=result_text if EXTRACTION_NATIVE in methods_list or EXTRACTION_BOTH in methods_list else None,
                    ocr_text=ocr_text if EXTRACTION_OCR in methods_list or EXTRACTION_BOTH in methods_list else None,
                    process_id=self.process_id
                )
            
                # Konvertiere Dateipfade in URLs für die API-Antwort
                self._convert_paths_to_urls(result)
                
                # Stelle sicher, dass text_contents vorhanden sind - extrahiere sie aus dem extracted_text, falls notwendig
                if not result.metadata.text_contents and result.extracted_text:
                    result.metadata.text_contents = self._extract_text_contents_from_full_text(result.extracted_text)
                
                # Cache-Speicherung, falls aktiviert
                if use_cache and self.is_cache_enabled():
                    # Cache-Speicherung mit der korrekten Methode aus der Basisklasse
                    self.save_to_cache(cache_key, result)  # type: ignore
                
                # Erstelle und gib Response zurück
                return ResponseFactory.create_response(
                    processor_name=PROCESSOR_TYPE_PDF,
                    result=result,
                    request_info={
                        'file_path': str(file_path),
                        'template': template,
                        'context': context,
                        'extraction_method': "_".join(methods_list)  # Korrekter kombinierter String
                    },
                    response_class=PDFResponse,
                    llm_info=llm_info,
                    from_cache=False
                )

        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            self.logger.error(f"Fehler bei der Verarbeitung: {str(e)}")
            
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
            
            return ResponseFactory.create_response(
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
                llm_info=llm_info,
                from_cache=False
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
            for i, path in enumerate(result.metadata.text_paths):
                # Ersetze backslashes durch forward slashes
                normalized_path = str(path).replace('\\', '/')
                # Speichere die ursprünglichen Pfade in einem neuen Attribut
                if not hasattr(result.metadata, 'original_text_paths'):
                    result.metadata.original_text_paths = []  # type: ignore
                result.metadata.original_text_paths.append(path)  # type: ignore
                # Aktualisiere den Pfad zur URL
                result.metadata.text_paths[i] = f"{base_url}{normalized_path}"
        
        # Wenn text_contents leer ist, aber extracted_text vorhanden ist,
        # extrahiere die text_contents aus dem extracted_text
        if hasattr(result.metadata, 'text_contents') and not result.metadata.text_contents and result.extracted_text:
            result.metadata.text_contents = self._extract_text_contents_from_full_text(result.extracted_text)

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