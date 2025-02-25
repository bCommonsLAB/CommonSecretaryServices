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
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union, cast
from dataclasses import dataclass

from PIL.ImageFile import ImageFile
import fitz  # type: ignore
from PIL import Image
import pytesseract  # type: ignore
import requests

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.core.config import Config
from src.core.models.base import ErrorInfo, BaseResponse
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.response_factory import ResponseFactory
from src.core.models.transformer import TransformerResponse
from src.core.models.pdf import PDFMetadata
from .transformer_processor import TransformerProcessor

# Konstanten für Processor-Typen
PROCESSOR_TYPE_PDF = "pdf"

# Konstanten für Extraktionsmethoden
EXTRACTION_NATIVE = "native"  # Nur native Text-Extraktion
EXTRACTION_OCR = "ocr"       # Nur OCR
EXTRACTION_BOTH = "both"     # Beide Methoden kombinieren
EXTRACTION_PREVIEW = "preview"  # Nur Vorschaubilder

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

@dataclass(frozen=True)
class PDFResponse(BaseResponse):
    """Standardisierte Response für die PDF-Verarbeitung."""
    data: Optional[PDFProcessingResult] = None

class PDFProcessor(BaseProcessor):
    """Prozessor für die Verarbeitung von PDF-Dateien."""
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        """Initialisiert den PDFProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Lade Konfiguration
        config = Config()
        self.max_file_size = config.get('processors.pdf.max_file_size', 50 * 1024 * 1024)
        self.max_pages = config.get('processors.pdf.max_pages', 100)
        
        # Initialisiere Transformer
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
    def create_process_dir(self, identifier: str) -> Path:
        """Erstellt und gibt das Verarbeitungsverzeichnis für eine PDF zurück."""
        process_dir = self.temp_dir / "pdf" / identifier
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
        pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # 300 DPI
        preview_path = working_dir / f"preview_{page_num+1:03d}.png"  # Dreistellige Nummerierung
        pix.save(str(preview_path))
        return str(preview_path)

    async def process(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        extraction_method: str = EXTRACTION_NATIVE
    ) -> PDFResponse:
        """
        Verarbeitet eine PDF-Datei.
        
        Args:
            file_path: Pfad oder URL zur PDF-Datei
            template: Optional Template für die Verarbeitung
            context: Optionaler Kontext
            extraction_method: Extraktionsmethode (native/ocr/both/preview)
            
        Returns:
            PDFResponse: Die standardisierte Response
        """
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
                # Lade PDF von URL herunter
                temp_file = working_dir / "temp.pdf"
                response = requests.get(str(file_path), stream=True)
                response.raise_for_status()
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                path = temp_file
            else:
                path = Path(file_path)
            
            self.logger.info(f"Verarbeite PDF: {path.name}",
                           file_size=path.stat().st_size,
                           working_dir=str(working_dir),
                           extraction_method=extraction_method)
            
            # Dateigröße prüfen
            self.check_file_size(path)
            
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
                start_time = datetime.now()
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
                    page = pdf[page_num]
                    page_start = time.time()
                    
                    if extraction_method == EXTRACTION_PREVIEW:
                        # Nur Vorschaubilder generieren
                        preview_path = self._generate_preview(page, page_num, working_dir)
                        metadata.preview_paths.append(preview_path)
                        
                    elif extraction_method == EXTRACTION_NATIVE:
                        # Native Text-Extraktion
                        page_text = page.get_text()  # type: ignore
                        full_text += f"\n--- Seite {page_num+1} ---\n{page_text}"
                        
                    elif extraction_method == EXTRACTION_OCR:
                        # OCR durchführen
                        pix: fitz.Pixmap = cast(fitz.Pixmap, page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72)))  # type: ignore  # 300 DPI
                        image_path: Path = working_dir / f"page_{page_num+1}.png"
                        pix.save(str(image_path))  # type: ignore
                        metadata.image_paths.append(str(image_path))
                        
                        # OCR mit Tesseract
                        img = Image.open(image_path)
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
                        image_path: Path = working_dir / f"page_{page_num+1}.png"
                        pix.save(str(image_path))  # type: ignore
                        metadata.image_paths.append(str(image_path))
                        
                        # OCR mit Tesseract
                        img: ImageFile = Image.open(image_path)
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
                
                # Neue Metadata-Instanz mit ZIP-Pfad erstellen
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
                
                duration: float = (datetime.now() - start_time).total_seconds() * 1000
                
                # LLM-Tracking
                if extraction_method == EXTRACTION_PREVIEW:
                    llm_info.add_request([LLMRequest(
                        model="pdf-preview",
                        purpose="preview_generation",
                        tokens=page_count,  # Ein Token pro Seite
                        duration=int(duration),
                        timestamp=start_time.isoformat()
                    )])
                elif extraction_method == EXTRACTION_NATIVE:
                    llm_info.add_request([LLMRequest(
                        model="pdf-extraction",
                        purpose="text_extraction",
                        tokens=len(full_text.split()),
                        duration=int(duration),
                        timestamp=start_time.isoformat()
                    )])
                elif extraction_method == EXTRACTION_OCR:
                    llm_info.add_request([LLMRequest(
                        model="tesseract",
                        purpose="ocr_extraction",
                        tokens=len(ocr_text.split()),
                        duration=int(duration),
                        timestamp=start_time.isoformat()
                    )])
                else:  # EXTRACTION_BOTH
                    llm_info.add_request([
                        LLMRequest(
                            model="pdf-extraction",
                            purpose="text_extraction",
                            tokens=len(full_text.split()),
                            duration=int(duration/2),
                            timestamp=start_time.isoformat()
                        ),
                        LLMRequest(
                            model="tesseract",
                            purpose="ocr_extraction",
                            tokens=len(ocr_text.split()),
                            duration=int(duration/2),
                            timestamp=start_time.isoformat()
                        )
                    ])
                
                # Wähle den Text für die Template-Transformation
                processing_text = ""
                if extraction_method == EXTRACTION_NATIVE:
                    processing_text = full_text
                elif extraction_method == EXTRACTION_OCR:
                    processing_text = ocr_text
                elif extraction_method == EXTRACTION_BOTH:
                    processing_text = f"=== Native Extraktion ===\n{full_text}\n\n=== OCR Extraktion ===\n{ocr_text}"
                
                # Template-Transformation wenn gewünscht
                if template and processing_text:
                    transform_result: TransformerResponse = self.transformer.transformByTemplate(
                        source_text=processing_text,
                        source_language="de",
                        target_language="de",
                        template=template,
                        context=context or {}
                    )
                    
                    if transform_result.process and transform_result.process.llm_info:
                        llm_info.add_request(transform_result.process.llm_info.requests)
                        
                    if transform_result.data and transform_result.data.output:
                        processing_text = str(transform_result.data.output.text)
                
                # Ergebnis erstellen
                result = PDFProcessingResult(
                    metadata=metadata,
                    extracted_text=full_text if extraction_method != EXTRACTION_OCR else None,
                    ocr_text=ocr_text if extraction_method != EXTRACTION_NATIVE else None,
                    process_id=self.process_id
                )
                
                # Response erstellen
                self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}")
                
                return ResponseFactory.create_response(
                    processor_name=PROCESSOR_TYPE_PDF,
                    result=result,
                    request_info={
                        'file_path': str(file_path),
                        'template': template,
                        'context': context,
                        'extraction_method': extraction_method
                    },
                    response_class=PDFResponse,
                    llm_info=llm_info if llm_info.requests else None
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
            current_time = time.time()
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