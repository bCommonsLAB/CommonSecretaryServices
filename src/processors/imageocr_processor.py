"""
ImageOCR Processor für die Verarbeitung von Bildern mit OCR.

LLM-Tracking Logik:
-----------------
Der ImageOCRProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
   a) OCR-Extraktion:
      - Model: tesseract
      - Purpose: ocr_extraction
      
   b) Template-Transformation (wenn Template verwendet):
      - Model: gpt-4
      - Purpose: template_transform
"""

import uuid
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass

from PIL import Image
import pytesseract  # type: ignore

from src.core.resource_tracking import ResourceCalculator
from src.core.config import Config
from src.core.models.base import ErrorInfo, BaseResponse
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.response_factory import ResponseFactory
from src.core.models.transformer import TransformerResponse
from src.core.exceptions import ProcessingError
from .base_processor import BaseProcessor
from .transformer_processor import TransformerProcessor

# Konstanten für Processor-Typen
PROCESSOR_TYPE_IMAGEOCR = "imageocr"

@dataclass
class ImageOCRMetadata:
    """Metadaten eines verarbeiteten Bildes."""
    file_name: str
    file_size: int
    dimensions: str
    format: str
    color_mode: str
    dpi: Optional[tuple[int, int]] = None
    process_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'file_name': self.file_name,
            'file_size': self.file_size,
            'dimensions': self.dimensions,
            'format': self.format,
            'color_mode': self.color_mode,
            'dpi': self.dpi,
            'process_dir': self.process_dir
        }

@dataclass
class ImageOCRProcessingResult:
    """Ergebnis der Bildverarbeitung mit OCR."""
    metadata: ImageOCRMetadata
    extracted_text: Optional[str] = None
    process_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'extracted_text': self.extracted_text,
            'process_id': self.process_id
        }

@dataclass(frozen=True)
class ImageOCRResponse(BaseResponse):
    """Standardisierte Response für die Bildverarbeitung mit OCR."""
    data: Optional[ImageOCRProcessingResult] = None

class ImageOCRProcessor(BaseProcessor):
    """Prozessor für die Verarbeitung von Bildern mit OCR."""
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        """Initialisiert den ImageOCRProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Lade Konfiguration
        config = Config()
        self.max_file_size = config.get('processors.imageocr.max_file_size', 10 * 1024 * 1024)
        self.max_resolution = config.get('processors.imageocr.max_resolution', 4096)
        
        # Initialisiere Transformer
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
    def create_process_dir(self, identifier: str) -> Path:
        """Erstellt und gibt das Verarbeitungsverzeichnis für ein Bild zurück."""
        process_dir = self.temp_dir / "imageocr" / identifier
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir

    async def process(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ImageOCRResponse:
        """
        Verarbeitet ein Bild mit OCR.
        
        Args:
            file_path: Pfad zur Bilddatei
            template: Optional Template für die Verarbeitung
            context: Optionaler Kontext
            
        Returns:
            ImageOCRResponse: Die standardisierte Response
        """
        # Initialisiere Variablen
        working_dir: Path = Path(self.temp_dir) / "imageocr" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialisiere LLM-Info
        llm_info = LLMInfo(
            model="imageocr-processing",
            purpose="imageocr-processing"
        )
        
        try:
            path = Path(file_path)
            self.logger.info(f"Verarbeite Bild: {path.name}",
                           file_size=path.stat().st_size,
                           working_dir=str(working_dir))
            
            # Dateigröße prüfen
            self.check_file_size(path)
            
            # Bild verarbeiten
            with Image.open(path) as img:
                width, height = img.size
                
                # Auflösung prüfen
                if width > self.max_resolution or height > self.max_resolution:
                    raise ProcessingError(
                        f"Bildauflösung zu groß: {width}x{height} "
                        f"(Maximum: {self.max_resolution}x{self.max_resolution})"
                    )
                
                # DPI-Information sicher extrahieren
                dpi_info: Optional[tuple[float, float]] = img.info.get('dpi')
                dpi_tuple = None
                if isinstance(dpi_info, tuple) and len(dpi_info) == 2:
                    try:
                        dpi_tuple = (int(dpi_info[0]), int(dpi_info[1]))
                    except (ValueError, TypeError):
                        dpi_tuple = None
                
                # Metadaten extrahieren
                metadata = ImageOCRMetadata(
                    file_name=path.name,
                    file_size=path.stat().st_size,
                    dimensions=f"{width}x{height}",
                    format=img.format or "unknown",
                    color_mode=img.mode,
                    dpi=dpi_tuple,
                    process_dir=str(working_dir)
                )
                
                # Text extrahieren
                self.logger.debug("Starte OCR-Verarbeitung")
                start_time = datetime.now()
                try:
                    raw_text = pytesseract.image_to_string(  # type: ignore[attr-defined]
                        image=img,
                        lang='deu',  # Deutsche Sprache
                        config='--psm 3',  # Standard Page Segmentation Mode
                        output_type=pytesseract.Output.STRING
                    )
                except Exception as ocr_error:
                    self.logger.warning(
                        "Fehler bei deutscher OCR, versuche Englisch als Fallback",
                        error=str(ocr_error)
                    )
                    # Fallback auf Englisch wenn Deutsch nicht verfügbar
                    raw_text = pytesseract.image_to_string(  # type: ignore[attr-defined]
                        image=img,
                        lang='eng',  # Englisch als Fallback
                        config='--psm 3',
                        output_type=pytesseract.Output.STRING
                    )
                extracted_text = str(raw_text)  # Explizite Konvertierung zu str
                duration = (datetime.now() - start_time).total_seconds() * 1000
                
                # OCR-Request tracken
                llm_info.add_request([LLMRequest(
                    model="tesseract",
                    purpose="ocr_extraction",
                    tokens=len(extracted_text.split()),
                    duration=int(duration),
                    timestamp=start_time.isoformat()
                )])
                
                # Template-Transformation wenn gewünscht
                if template and extracted_text:
                    transform_result: TransformerResponse = self.transformer.transformByTemplate(
                        source_text=extracted_text,
                        source_language="de",  # Default Deutsch
                        target_language="de",  # Default Deutsch
                        template=template,
                        context=context or {}
                    )
                    
                    if transform_result.process and transform_result.process.llm_info:
                        llm_info.add_request(transform_result.process.llm_info.requests)
                        
                    if transform_result.data and transform_result.data.output:
                        extracted_text = str(transform_result.data.output.text)
                
                # Ergebnis erstellen
                result = ImageOCRProcessingResult(
                    metadata=metadata,
                    extracted_text=extracted_text,
                    process_id=self.process_id
                )
                
                # Response erstellen
                self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}")
                
                return ResponseFactory.create_response(
                    processor_name=PROCESSOR_TYPE_IMAGEOCR,
                    result=result,
                    request_info={
                        'file_path': str(file_path),
                        'template': template,
                        'context': context
                    },
                    response_class=ImageOCRResponse,
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
            dummy_result = ImageOCRProcessingResult(
                metadata=ImageOCRMetadata(
                    file_name=Path(file_path).name,
                    file_size=0,
                    dimensions="0x0",
                    format="unknown",
                    color_mode="unknown",
                    process_dir=str(working_dir)
                ),
                process_id=self.process_id
            )
            
            # Error-Response
            return ResponseFactory.create_response(
                processor_name=PROCESSOR_TYPE_IMAGEOCR,
                result=dummy_result,
                request_info={
                    'file_path': str(file_path),
                    'template': template,
                    'context': context
                },
                response_class=ImageOCRResponse,
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