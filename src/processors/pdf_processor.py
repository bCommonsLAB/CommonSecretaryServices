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

import uuid
import traceback
import time
import zipfile
import json
import hashlib
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Optional, Union, cast
from dataclasses import dataclass
import subprocess
import os
from urllib.parse import urlparse
import io

from PIL import Image
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

@dataclass
class PDFProcessingResult:
    """Ergebnis der PDF-Verarbeitung."""
    metadata: PDFMetadata
    extracted_text: Optional[str]
    ocr_text: Optional[str] = None
    process_id: Optional[str] = None
    is_from_cache: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'extracted_text': self.extracted_text,
            'ocr_text': self.ocr_text,
            'process_id': self.process_id,
            'is_from_cache': self.is_from_cache
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PDFProcessingResult':
        """Erstellt ein PDFProcessingResult aus einem Dictionary."""
        from src.core.models.pdf import PDFMetadata
        
        # Metadaten direkt aus dem Dictionary extrahieren
        metadata_dict = data.get('metadata', {})
        
        # Einfache Typüberprüfungen für den Linter
        if not isinstance(metadata_dict, dict):
            raise ValueError("metadata muss ein Dictionary sein")
        
        # Vorsichtige Konvertierung für den Linter
        file_name = str(metadata_dict.get('file_name', ''))  # type: ignore
        file_size = int(metadata_dict.get('file_size', 0))  # type: ignore
        page_count = int(metadata_dict.get('page_count', 0))  # type: ignore
        
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
            extraction_method=str(metadata_dict.get('extraction_method', 'native'))  # type: ignore
        )
        
        return cls(
            metadata=metadata,
            extracted_text=data.get('extracted_text'),
            ocr_text=data.get('ocr_text'),
            process_id=data.get('process_id'),
            is_from_cache=data.get('is_from_cache', False)
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
        """Speichert den extrahierten Text einer Seite."""
        text_path = process_dir / f"page_{page_num+1}.txt"
        text_path.write_text(text, encoding='utf-8')
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
        
        # Setze is_from_cache auf True
        result.is_from_cache = True
        
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
            llm_info=None
        )

    async def process(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        extraction_method: str = EXTRACTION_NATIVE,
        use_cache: bool = True,
        file_hash: Optional[str] = None
    ) -> PDFResponse:
        """
        Verarbeitet ein PDF und gibt das Ergebnis zurück.
        
        Args:
            file_path: Pfad zur PDF-Datei
            template: Optional, ein Template für die strukturierte Extraktion
            context: Optional, ein Kontext für die Verarbeitung
            extraction_method: Die zu verwendende Extraktionsmethode
            use_cache: Ob der Cache verwendet werden soll
            file_hash: Optional, ein vorberechneter Hash der Datei für effizienteres Caching
            
        Returns:
            PDFResponse: Die standardisierte API-Response
        """
        # Variable für den Cache-Key initialisieren
        cache_key: str = ""
        
        # Zeitmessung für die Verarbeitung
        start_time: datetime = datetime.now()
        
        # Cache-Schlüssel generieren
        if use_cache and self.is_cache_enabled():
            cache_key = self._create_cache_key(
                file_path=file_path,
                template=template,
                context=context,
                extraction_method=extraction_method,
                file_hash=file_hash
            )
            
            # Prüfen, ob im Cache vorhanden
            cache_hit, cached_result = self.get_from_cache(cache_key)
            
            if cache_hit and cached_result:
                self.logger.info(f"Cache-Hit für PDF-Verarbeitung: {cache_key[:8]}...")
                
                # Response aus dem Cache erstellen
                return self._create_response_from_cached_result(
                    cached_result=cached_result,
                    file_path=file_path,
                    template=template,
                    context=context,
                    extraction_method=extraction_method,
                    file_hash=file_hash
                )
        
        # Validiere Extraktionsmethode
        if extraction_method not in [EXTRACTION_NATIVE, EXTRACTION_OCR, EXTRACTION_BOTH, EXTRACTION_PREVIEW]:
            raise ProcessingError(f"Ungültige Extraktionsmethode: {extraction_method}")

        # Initialisiere Variablen
        working_dir: Path = Path(self.temp_dir) / "pdf" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialisiere LLM-Info
        llm_info = LLMInfo(
            model="pdf-processing",
            purpose="pdf-processing"
        )
        
        try:
            # Prüfe ob es sich um eine URL handelt
            if str(file_path).startswith(('http://', 'https://')):
                # Extrahiere Dateiendung aus URL
                file_extension = self._get_file_extension(str(file_path))
                self.logger.info(f"Erkannte Dateiendung: {file_extension}")
                
                # Lade Datei von URL herunter
                temp_file = working_dir / f"temp{file_extension}"
                response: requests.Response = requests.get(str(file_path), stream=True)
                response.raise_for_status()
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                path = temp_file
            else:
                path = Path(file_path)
            
            self.logger.info(f"Verarbeite Datei: {path.name}",
                           file_size=path.stat().st_size,
                           working_dir=str(working_dir),
                           extraction_method=extraction_method)
            
            # Dateigröße prüfen
            self.check_file_size(path)
            
            # Prüfe Dateityp und konvertiere wenn nötig
            if path.suffix.lower() in ['.pptx', '.ppt']:
                self.logger.info("Konvertiere PowerPoint zu PDF")
                pdf_path: Path = working_dir / "temp.pdf"
                self._convert_pptx_to_pdf(path, pdf_path)
                path: Path = pdf_path
            
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
                self.logger.debug(f"Starte Extraktion (Methode: {extraction_method})")
                start_time: datetime = datetime.now()
                full_text = ""
                ocr_text = ""
                metadata = PDFMetadata(
                    file_name=path.name,
                    file_size=path.stat().st_size,
                    page_count=page_count,
                    process_dir=str(working_dir),
                    extraction_method=extraction_method
                )
                
                for page_num in range(page_count):
                    page: fitz.Page = pdf[page_num]
                    page_start: float = time.time()
                    
                    # Vorschaubild generieren
                    preview_pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # type: ignore
                    img_bytes = preview_pix.tobytes("ppm")  # type: ignore
                    pil_img = Image.open(io.BytesIO(img_bytes))  # type: ignore
                    
                    # Größe für Vorschaubild anpassen
                    preview_max_size = self.preview_image_max_size
                    if pil_img.width > preview_max_size or pil_img.height > preview_max_size:
                        if pil_img.width > pil_img.height:
                            new_width = preview_max_size
                            new_height = int(pil_img.height * (preview_max_size / pil_img.width))
                        else:
                            new_height = preview_max_size
                            new_width = int(pil_img.width * (preview_max_size / pil_img.height))
                        preview_img: Image.Image = pil_img.resize((new_width, new_height))
                    else:
                        preview_img = pil_img
                    
                    # Vorschaubild speichern
                    preview_path = working_dir / f"preview_{page_num+1:03d}.{self.preview_image_format}"
                    format_name = "JPEG" if self.preview_image_format.lower() == "jpg" else self.preview_image_format.upper()
                    preview_img.save(
                        str(preview_path), 
                        format=format_name,
                        quality=self.preview_image_quality
                    )
                    metadata.preview_paths.append(str(preview_path))
                    
                    # Hauptbild generieren (Kopie von pil_img)
                    main_img: Image.Image = pil_img.copy()
                    
                    # Größe für Hauptbild anpassen
                    main_max_size = self.main_image_max_size
                    if main_img.width > main_max_size or main_img.height > main_max_size:
                        if main_img.width > main_img.height:
                            new_width = main_max_size
                            new_height = int(main_img.height * (main_max_size / main_img.width))
                        else:
                            new_height = main_max_size
                            new_width = int(main_img.width * (main_max_size / main_img.height))
                        main_img = main_img.resize((new_width, new_height))
                    
                    # Hauptbild speichern
                    image_path = working_dir / f"image_{page_num+1:03d}.{self.main_image_format}"
                    format_name = "JPEG" if self.main_image_format.lower() == "jpg" else self.main_image_format.upper()
                    main_img.save(
                        str(image_path), 
                        format=format_name,
                        quality=self.main_image_quality
                    )
                    metadata.image_paths.append(str(image_path))
                    
                    # Ressourcen freigeben
                    pil_img.close()
                    preview_img.close()
                    main_img.close()
                    del preview_pix
                    
                    if extraction_method == EXTRACTION_PREVIEW:
                        # Bei EXTRACTION_PREVIEW ist nichts weiter zu tun
                        pass
                    elif extraction_method == EXTRACTION_NATIVE:
                        # Native Text-Extraktion
                        page_text = page.get_text()  # type: ignore
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                    elif extraction_method == EXTRACTION_OCR:
                        # OCR durchführen
                        pix: fitz.Pixmap = cast(fitz.Pixmap, page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72)))  # type: ignore  # 300 DPI
                        
                        # Konvertieren des Pixmap zu PIL Image für OCR (ohne Speichern)
                        img_bytes = pix.tobytes("ppm")  # type: ignore
                        img = Image.open(io.BytesIO(img_bytes))  # type: ignore
                        
                        try:
                            page_ocr = str(pytesseract.image_to_string(  # type: ignore[attr-defined]
                                image=img,
                                lang='deu',  # Deutsche Sprache
                                config='--psm 3'  # Standard Page Segmentation Mode
                            ))
                        except Exception as ocr_error:
                            self.logger.warning(
                                "Fehler bei deutscher OCR, versuche Englisch als Fallback",
                                error=str(ocr_error)
                            )
                            page_ocr = str(pytesseract.image_to_string(  # type: ignore[attr-defined]
                                image=img,
                                lang='eng',  # Englisch als Fallback
                                config='--psm 3'
                            ))
                        
                        # OCR-Text speichern
                        text_path = self.save_page_text(str(page_ocr), page_num, working_dir)
                        metadata.text_paths.append(str(text_path))
                        ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                        
                        # Ressourcen freigeben
                        img.close()
                        del pix
                        
                    else:  # EXTRACTION_BOTH
                        # Native Text-Extraktion
                        page_text = page.get_text()  # type: ignore
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                        # OCR durchführen
                        pix: fitz.Pixmap = cast(fitz.Pixmap, page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72)))  # type: ignore  # 300 DPI
                        
                        # Konvertieren des Pixmap zu PIL Image für OCR (ohne Speichern)
                        img_bytes = pix.tobytes("ppm")  # type: ignore
                        img = Image.open(io.BytesIO(img_bytes))  # type: ignore
                        
                        try:
                            page_ocr = str(pytesseract.image_to_string(  # type: ignore[attr-defined]
                                image=img,
                                lang='deu',  # Deutsche Sprache
                                config='--psm 3'  # Standard Page Segmentation Mode
                            ))
                        except Exception as ocr_error:
                            self.logger.warning(
                                "Fehler bei deutscher OCR, versuche Englisch als Fallback",
                                error=str(ocr_error)
                            )
                            page_ocr = str(pytesseract.image_to_string(  # type: ignore[attr-defined]
                                image=img,
                                lang='eng',  # Englisch als Fallback
                                config='--psm 3'
                            ))
                        
                        # OCR-Text speichern
                        text_path = self.save_page_text(str(page_ocr), page_num, working_dir)
                        metadata.text_paths.append(str(text_path))
                        ocr_text += f"\n--- Seite {page_num+1} ---\n{page_ocr}"
                        
                        # Ressourcen freigeben
                        img.close()
                        del pix
                    
                    # Logging
                    page_duration = time.time() - page_start
                    self.logger.debug(f"Seite {page_num + 1} verarbeitet",
                                    duration=page_duration,
                                    extraction_method=extraction_method)
                
                # Wenn Vorschaubilder generiert wurden, diese als ZIP verpacken
                preview_zip_path: Optional[str] = None
                if metadata.preview_paths:
                    zip_path: Path = working_dir / "previews.zip"
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for preview_path_str in metadata.preview_paths:
                            preview_path_obj = Path(str(preview_path_str))  # Explizite Konvertierung
                            zipf.write(str(preview_path_obj), preview_path_obj.name)
                    preview_zip_path = str(zip_path)
                
                # Metadaten aktualisieren
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
                    extraction_method=metadata.extraction_method
                )
                
                # Ergebnis zusammenstellen
                result = PDFProcessingResult(
                    metadata=metadata,
                    extracted_text=full_text if extraction_method != EXTRACTION_OCR else None,
                    ocr_text=ocr_text if extraction_method != EXTRACTION_NATIVE else None,
                    process_id=self.process_id,
                    is_from_cache=False
                )
                
                # Ergebnis im Cache speichern
                if use_cache and self.is_cache_enabled():
                    self.save_to_cache(cache_key, result)
                    self.logger.debug(f"Ergebnis im Cache gespeichert: {cache_key[:8]}...")
                
                # Response erstellen
                self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}")
                
                # LLM-Tracking abschließen
                if extraction_method == EXTRACTION_NATIVE:
                    llm_info.add_request([LLMRequest(
                        model="pdf-extraction",
                        purpose="text_extraction",
                        tokens=len(full_text.split()),
                        duration=int((time.time() - start_time.timestamp()) * 1000),
                        timestamp=start_time.isoformat()
                    )])
                elif extraction_method == EXTRACTION_OCR:
                    llm_info.add_request([LLMRequest(
                        model="tesseract",
                        purpose="ocr_extraction",
                        tokens=len(ocr_text.split()),
                        duration=int((time.time() - start_time.timestamp()) * 1000),
                        timestamp=start_time.isoformat()
                    )])
                elif extraction_method == EXTRACTION_BOTH:
                    llm_info.add_request([
                        LLMRequest(
                            model="pdf-extraction",
                            purpose="text_extraction",
                            tokens=len(full_text.split()) // 2,
                            duration=int((time.time() - start_time.timestamp()) * 1000),
                            timestamp=start_time.isoformat()
                        ),
                        LLMRequest(
                            model="tesseract",
                            purpose="ocr_extraction",
                            tokens=len(ocr_text.split()) // 2,
                            duration=int((time.time() - start_time.timestamp()) * 1000),
                            timestamp=start_time.isoformat()
                        )
                    ])
                
                # Ergebnis mit dem Template anreichern, falls eines angegeben wurde
                if template:
                    # Logging
                    self.logger.debug("Beginne Template-Transformation")
                    
                    # Template mit Transformer-Prozessor verarbeiten
                    template_processed: Any = await self.process_template(  # type: ignore
                        text=full_text if extraction_method == EXTRACTION_NATIVE else ocr_text if extraction_method == EXTRACTION_OCR else f"{full_text}\n\n{ocr_text}",
                        template=template,
                        context=context
                    )
                    
                    # LLM-Kosten hinzufügen, falls vorhanden
                    if hasattr(template_processed, 'llm_info') and template_processed.llm_info:
                        llm_info.add_llm_info(template_processed.llm_info)  # type: ignore
                
                # Cache-Eintrag speichern, falls aktiviert
                if use_cache and self.is_cache_enabled() and cache_key:
                    # Serialisiere das Ergebnis und speichere es im Cache
                    self.save_to_cache(cache_key, result)
                
                # Response erstellen
                self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}")
                
                return ResponseFactory.create_response(
                    processor_name=PROCESSOR_TYPE_PDF,
                    result=result,
                    request_info={
                        "file_path": str(file_path),
                        "template": template,
                        "extraction_method": extraction_method,
                        "context": context
                    },
                    response_class=PDFResponse,
                    llm_info=llm_info
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
                    'context': context
                },
                response_class=PDFResponse,
                error=error_info,
                llm_info=None
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