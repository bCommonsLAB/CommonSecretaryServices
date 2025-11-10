"""
@fileoverview ImageOCR Processor - OCR processing of images with various methods

@description
ImageOCR Processor for processing images with OCR. This processor processes images
(JPG, PNG, WebP) and extracts text with various methods:
- Tesseract OCR (standard)
- LLM-based OCR (OpenAI Vision, Mistral OCR)
- Combined methods (LLM + Tesseract)
- Preview image generation

LLM tracking logic:
The ImageOCRProcessor tracks LLM usage on two levels:
1. Aggregated information (LLMInfo): Total tokens, duration, costs
2. Individual requests (LLMRequest):
   - OCR extraction: tesseract model
   - Template transformation: gpt-4 model (via TransformerProcessor)

Features:
- Multiple OCR methods (Tesseract, LLM-based)
- Automatic image preprocessing (scaling, optimization)
- Preview image generation
- Metadata extraction (dimensions, format, DPI, etc.)
- Integration with TransformerProcessor for template transformation
- Caching of OCR results

@module processors.imageocr_processor

@exports
- ImageOCRProcessor: Class - ImageOCR processing processor
- ImageOCRMetadata: Dataclass - Image metadata

@usedIn
- src.processors.pdf_processor: Uses ImageOCRProcessor for PDF page OCR
- src.api.routes.imageocr_routes: API endpoint for image OCR processing

@dependencies
- External: Pillow (PIL) - Image processing
- External: pytesseract - Tesseract OCR binding
- External: requests - HTTP requests for external APIs
- Internal: src.processors.cacheable_processor - CacheableProcessor base class
- Internal: src.processors.transformer_processor - TransformerProcessor for template transformation
- Internal: src.utils.image2text_utils - Image2TextService for LLM OCR
- Internal: src.core.models.transformer - TransformerResponse
- Internal: src.core.config - Configuration
"""
# mypy: disable-error-code="attr-defined,valid-type,misc"
import traceback
import hashlib
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Optional, Union, cast
from dataclasses import dataclass, field
import time
import requests
import shutil
import os
from urllib.parse import urlparse

from PIL import Image
import pytesseract  # type: ignore

from src.core.resource_tracking import ResourceCalculator
from src.core.config import Config
from src.core.models.base import ErrorInfo, BaseResponse
from src.core.models.transformer import TransformerResponse
from src.core.exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.core.models.enums import ProcessingStatus

# Neue Imports hinzufügen
from src.utils.image2text_utils import Image2TextService

# Konstanten für Processor-Typen
PROCESSOR_TYPE_IMAGEOCR = "imageocr"

# Konstanten für Extraktionsmethoden
EXTRACTION_OCR = "ocr"           # Standard OCR-Methode
EXTRACTION_NATIVE = "native"     # Native Bildanalyse (falls verfügbar)
EXTRACTION_BOTH = "both"         # Kombination von OCR und nativer Analyse
EXTRACTION_PREVIEW = "preview"   # Nur Vorschaubilder generieren
EXTRACTION_PREVIEW_AND_NATIVE = "preview_and_native"  # Vorschaubilder und native Analyse

# Neue Konstanten für LLM-basierte OCR
EXTRACTION_LLM = "llm"  # LLM-basierte OCR mit Markdown-Output
EXTRACTION_LLM_AND_OCR = "llm_and_ocr"  # LLM + Tesseract OCR

@dataclass(frozen=True)
class ImageOCRMetadata:
    """Metadaten eines verarbeiteten Bildes."""
    file_name: str
    file_size: int
    dimensions: str
    format: str
    color_mode: str
    dpi: Optional[tuple[int, int]] = None
    process_dir: Optional[str] = None
    extraction_method: str = EXTRACTION_OCR
    preview_paths: list[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Validiert die Metadaten nach der Initialisierung."""
        if not self.file_name:
            raise ValueError("file_name darf nicht leer sein")
        if self.file_size < 0:
            raise ValueError("file_size muss größer oder gleich 0 sein")
        if not self.dimensions:
            raise ValueError("dimensions darf nicht leer sein")
        if not self.format:
            raise ValueError("format darf nicht leer sein")
        if not self.color_mode:
            raise ValueError("color_mode darf nicht leer sein")
        if not self.extraction_method:
            raise ValueError("extraction_method darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'file_name': self.file_name,
            'file_size': self.file_size,
            'dimensions': self.dimensions,
            'format': self.format,
            'color_mode': self.color_mode,
            'dpi': self.dpi,
            'process_dir': self.process_dir,
            'extraction_method': self.extraction_method,
            'preview_paths': self.preview_paths
        }

@dataclass(frozen=True)
class ImageOCRProcessingResult:
    """Ergebnis der Bildverarbeitung mit OCR."""
    metadata: ImageOCRMetadata
    extracted_text: Optional[str] = None
    process_id: Optional[str] = None
    processed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    
    def __post_init__(self) -> None:
        """Validiert das Ergebnis nach der Initialisierung."""
        if not self.metadata:
            raise ValueError("metadata darf nicht leer sein")

    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.extracted_text else ProcessingStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict(),
            'extracted_text': self.extracted_text,
            'process_id': self.process_id,
            'processed_at': self.processed_at,
            'status': self.status.value
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImageOCRProcessingResult':
        """Erstellt ein ImageOCRProcessingResult aus einem Dictionary."""
        # Metadaten direkt aus dem Dictionary extrahieren
        metadata_dict = data.get('metadata', {})
        
        # Einfache Typüberprüfungen
        if not isinstance(metadata_dict, dict):
            raise ValueError("metadata muss ein Dictionary sein")
        
        # Metadaten-Objekt erstellen
        metadata = ImageOCRMetadata(
            file_name=str(metadata_dict.get('file_name', '')),  # type: ignore
            file_size=int(metadata_dict.get('file_size', 0)),  # type: ignore
            dimensions=str(metadata_dict.get('dimensions', '')),  # type: ignore
            format=str(metadata_dict.get('format', '')),  # type: ignore
            color_mode=str(metadata_dict.get('color_mode', '')),  # type: ignore
            dpi=cast(Optional[tuple[int, int]], metadata_dict.get('dpi')),  # type: ignore
            process_dir=cast(Optional[str], metadata_dict.get('process_dir')),  # type: ignore
            extraction_method=str(metadata_dict.get('extraction_method', EXTRACTION_OCR)),  # type: ignore
            preview_paths=cast(list[str], metadata_dict.get('preview_paths', []))  # type: ignore
        )
        
        # Ergebnis-Objekt erstellen
        return cls(
            metadata=metadata,
            extracted_text=cast(Optional[str], data.get('extracted_text')),
            process_id=cast(Optional[str], data.get('process_id')),
            processed_at=data.get('processed_at', datetime.now(UTC).isoformat())
        )

@dataclass(frozen=True)
class ImageOCRResponse(BaseResponse):
    """Standardisierte Response für die Bildverarbeitung mit OCR."""
    data: Optional[ImageOCRProcessingResult] = None

class ImageOCRProcessor(CacheableProcessor[ImageOCRProcessingResult]):
    """
    Prozessor für OCR-Verarbeitung von Bildern.
    
    Unterstützt:
    - Texterkennung in Bildern
    - Strukturerkennung (Tabellen, Listen)
    - Spracherkennung
    - LLM-basierte OCR mit Markdown-Output
    
    Verwendet MongoDB-Caching zur effizienten Wiederverwendung von OCR-Ergebnissen.
    """
    
    # Name der MongoDB-Cache-Collection
    cache_collection_name = "ocr_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        """Initialisiert den ImageOCRProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Lade Konfiguration
        config = Config()
        processor_config = config.get('processors.imageocr', {})
        self.max_file_size = processor_config.get('max_file_size', 10 * 1024 * 1024)
        self.max_resolution = processor_config.get('max_resolution', 4096)
        
        # Das temp_dir und cache_dir werden jetzt vollständig vom BaseProcessor verwaltet
        # und basieren auf der Konfiguration in config.yaml
        self.logger.debug("ImageOCRProcessor initialisiert mit Konfiguration", 
                         max_file_size=self.max_file_size,
                         max_resolution=self.max_resolution,
                         temp_dir=str(self.temp_dir),
                         cache_dir=str(self.cache_dir))
        
        # Initialisiere Transformer
        self.transformer = TransformerProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Initialisiere Image2Text Service für LLM-basierte OCR
        self.image2text_service = Image2TextService(
            processor_name=f"ImageOCRProcessor-{process_id}"
        )
        
    def create_process_dir(self, identifier: str, use_temp: bool = True) -> Path:
        """
        Erstellt und gibt das Verarbeitungsverzeichnis für ein Bild zurück.
        
        Args:
            identifier: Eindeutige Kennung des Bildes
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        process_dir = base_dir / "process" / identifier
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir
    
    def get_working_dir(self, use_temp: bool = True) -> Path:
        """
        Gibt das zentrale Working-Verzeichnis für Bilder zurück.
        
        Args:
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Working-Verzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        working_dir = base_dir / "working"
        working_dir.mkdir(parents=True, exist_ok=True)
        return working_dir
        
    def save_uploaded_file(self, uploaded_file_path: Union[str, Path], original_filename: str) -> str:
        """
        Speichert eine hochgeladene Datei im Working-Verzeichnis.
        
        Args:
            uploaded_file_path: Temporärer Pfad der hochgeladenen Datei
            original_filename: Ursprünglicher Dateiname
            
        Returns:
            str: Pfad der gespeicherten Datei im Working-Verzeichnis
        """
        working_dir = self.get_working_dir()
        
        # Originalen Dateinamen beibehalten, aber Zeitstempel hinzufügen um Konflikte zu vermeiden
        filename = f"{int(time.time())}_{Path(original_filename).name}"
        target_path = working_dir / filename
        
        # Kopiere die Datei
        shutil.copy2(uploaded_file_path, target_path)
        
        return str(target_path)

    async def process(
        self,
        file_path: Union[str, Path],
        template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        extraction_method: str = EXTRACTION_OCR,
        use_cache: bool = True,
        file_hash: Optional[str] = None
    ) -> ImageOCRResponse:
        """
        Verarbeitet ein Bild mit OCR.
        
        Args:
            file_path: Pfad zur Bilddatei
            template: Optional Template für die Verarbeitung
            context: Optionaler Kontext
            extraction_method: Extraktionsmethode (OCR, NATIVE, BOTH, PREVIEW)
            use_cache: Ob der Cache verwendet werden soll
            file_hash: Optional, der Hash der Datei (wenn bereits berechnet)
            
        Returns:
            ImageOCRResponse: Die standardisierte Response
        """
        # Initialisiere working_dir am Anfang
        working_dir = self.get_working_dir()
        
        try:
            # Validiere die Extraktionsmethode
            valid_methods = [
                EXTRACTION_OCR, EXTRACTION_NATIVE, EXTRACTION_BOTH, EXTRACTION_PREVIEW, 
                EXTRACTION_PREVIEW_AND_NATIVE, EXTRACTION_LLM, EXTRACTION_LLM_AND_OCR
            ]
            if extraction_method not in valid_methods:
                raise ProcessingError(f"Ungültige Extraktionsmethode: {extraction_method}")
            
            # Initialisiere cache_key früh im Code
            cache_key = ""
            
            # Bei Cache-Nutzung, erzeuge den Cache-Key
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
                self.logger.info(f"Cache-Hit für OCR-Verarbeitung: {cache_key[:8]}...")
                
                # Resource-Tracking für den Cache-Hit
                try:
                    # Expliziter cast zu Any für den Resource Calculator
                    resource_calculator_any = cast(Any, self.resource_calculator)
                    resource_calculator_any.add_resource_usage(
                        processor_type="imageocr",
                        resource_type="cache_hit",
                        duration_ms=0,
                        tokens=0,
                        cost=0
                    )
                except AttributeError:
                    self.logger.debug("ResourceCalculator hat keine add_resource_usage Methode")
                
                # Direkte Verwendung von ResponseFactory für Cache-Treffer
                return self.create_response(
                    processor_name="imageocr",
                    result=cached_result,
                    request_info={
                        "file_path": str(file_path),
                        "template": template,
                        "context": context,
                        "extraction_method": extraction_method
                    },
                    response_class=ImageOCRResponse,
                    from_cache=True,
                    cache_key=cache_key
                )
        
            # Initialisiere Variablen
            working_dir.mkdir(parents=True, exist_ok=True)
            
            # Prüfen, ob file_path eine URL ist
            is_url = isinstance(file_path, str) and file_path.startswith(('http://', 'https://'))
            local_file_path = file_path
            
            if is_url:
                # Da wir überprüft haben, dass file_path ein String ist, können wir es sicher als str behandeln
                url_str = str(file_path)  # Cast für den Linter
                self.logger.info(f"URL erkannt, lade Bild herunter: {url_str}")
                try:
                    # URL-Pfad parsen für den Dateinamen
                    parsed_url = urlparse(url_str)
                    url_path = parsed_url.path
                    url_parts = url_path.split('/')
                    file_name = url_parts[-1] if url_parts else ""
                    
                    # Prüfe, ob der Dateiname gültig ist und eine unterstützte Erweiterung hat
                    if not file_name or not any(file_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif']):
                        file_name = f"downloaded_image_{int(time.time())}.jpg"
                    
                    # Temporären Pfad für das heruntergeladene Bild erstellen
                    local_file_path = str(working_dir / file_name)
                    
                    # Bild herunterladen
                    response = requests.get(url_str, timeout=30)
                    response.raise_for_status()  # Fehler werfen, wenn Download fehlschlägt
                    
                    # Bild speichern
                    with open(local_file_path, 'wb') as f:
                        f.write(response.content)
                    
                    self.logger.info(f"Bild erfolgreich heruntergeladen nach: {local_file_path}")
                except Exception as e:
                    self.logger.error(f"Fehler beim Herunterladen des Bildes: {str(e)}")
                    raise ProcessingError(f"Fehler beim Herunterladen des Bildes: {str(e)}")
            
            self.logger.info(f"Verarbeite Bild: {Path(local_file_path).name}",
                           file_size=Path(local_file_path).stat().st_size if not is_url else "URL - Größe unbekannt",
                           working_dir=str(working_dir))
            
            # Dateigröße prüfen - für alle Dateien (lokale und heruntergeladene)
            self.check_file_size(Path(local_file_path))
            
            # Bild verarbeiten
            with Image.open(Path(local_file_path)) as img:
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
                # Prüfe, ob es eine URL ist
                is_url = isinstance(file_path, str) and file_path.startswith(('http://', 'https://'))
                file_name = str(file_path) if is_url else str(Path(file_path).name)
                file_size = 0 if is_url else Path(file_path).stat().st_size
                
                metadata = ImageOCRMetadata(
                    file_name=file_name,
                    file_size=file_size,
                    dimensions=f"{width}x{height}",
                    format=img.format or "unknown",
                    color_mode=img.mode,
                    dpi=dpi_tuple,
                    process_dir=str(working_dir),
                    extraction_method=extraction_method
                )
                
                # Text extrahieren
                self.logger.debug("Starte Bildverarbeitung mit Methode: {extraction_method}")

                # Variablen für Ergebnisse initialisieren
                extracted_text = ""
                preview_path = None

                # Vorschaubilder generieren, wenn benötigt
                if extraction_method in [EXTRACTION_PREVIEW, EXTRACTION_PREVIEW_AND_NATIVE]:
                    try:
                        # Erstelle ein Verzeichnis für Vorschaubilder
                        preview_dir = working_dir / "previews"
                        preview_dir.mkdir(exist_ok=True)
                        
                        # Erzeuge ein kleineres Vorschaubild
                        preview_size = (300, 300)
                        preview_img = img.copy()
                        preview_img.thumbnail(preview_size)
                        
                        # Speichere das Vorschaubild
                        preview_path = str(preview_dir / f"preview_{int(time.time())}.jpg")
                        preview_img.save(preview_path, "JPEG")
                        
                        # Füge den Pfad zu den Metadaten hinzu
                        metadata = ImageOCRMetadata(
                            file_name=metadata.file_name,
                            file_size=metadata.file_size,
                            dimensions=metadata.dimensions,
                            format=metadata.format,
                            color_mode=metadata.color_mode,
                            dpi=metadata.dpi,
                            process_dir=metadata.process_dir,
                            extraction_method=extraction_method,
                            preview_paths=[preview_path]
                        )
                        
                        self.logger.debug(f"Vorschaubild generiert: {preview_path}")
                    except Exception as e:
                        self.logger.warning(f"Fehler beim Generieren des Vorschaubilds: {str(e)}")

                # OCR durchführen, wenn benötigt
                if extraction_method in [EXTRACTION_OCR, EXTRACTION_BOTH]:
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
                    self.logger.debug(f"OCR-Text extrahiert ({len(extracted_text)} Zeichen)")

                # LLM-basierte OCR durchführen, wenn benötigt
                if extraction_method in [EXTRACTION_LLM, EXTRACTION_LLM_AND_OCR]:
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
                        
                        # LLM-OCR für dieses Bild
                        llm_text, llm_request = self.image2text_service.extract_text_from_image_file(
                            image_path=Path(local_file_path),
                            custom_prompt=custom_prompt,
                            logger=self.logger
                        )
                        
                        # LLM-Request zum Tracking hinzufügen
                        self.add_llm_requests([llm_request])
                        
                        if extraction_method == EXTRACTION_LLM:
                            # Nur LLM-OCR
                            extracted_text = llm_text
                        else:
                            # LLM + Tesseract OCR kombinieren
                            # Tesseract OCR
                            try:
                                tesseract_text = pytesseract.image_to_string(
                                    image=img,
                                    lang='deu',
                                    config='--psm 3',
                                    output_type=pytesseract.Output.STRING
                                )
                            except Exception as ocr_error:
                                self.logger.warning(f"Fehler bei Tesseract OCR: {str(ocr_error)}")
                                tesseract_text = f"Tesseract OCR Fehler: {str(ocr_error)}"
                            
                            # Kombiniere beide Ergebnisse
                            extracted_text = f"=== LLM Markdown ===\n{llm_text}\n\n=== Tesseract OCR ===\n{tesseract_text}"
                        
                        self.logger.debug(f"LLM-OCR-Text extrahiert ({len(extracted_text)} Zeichen)")
                        
                    except Exception as llm_error:
                        self.logger.warning(f"Fehler bei LLM-OCR: {str(llm_error)}")
                        if extraction_method == EXTRACTION_LLM:
                            # Bei reinem LLM-Modus Fallback auf Tesseract
                            try:
                                raw_text = pytesseract.image_to_string(
                                    image=img,
                                    lang='deu',
                                    config='--psm 3',
                                    output_type=pytesseract.Output.STRING
                                )
                                extracted_text = f"LLM-OCR fehlgeschlagen, Fallback auf Tesseract:\n\n{str(raw_text)}"
                            except Exception as fallback_error:
                                self.logger.error(f"Auch Tesseract-Fallback fehlgeschlagen: {str(fallback_error)}")
                                extracted_text = f"Beide OCR-Methoden fehlgeschlagen:\nLLM: {str(llm_error)}\nTesseract: {str(fallback_error)}"
                        else:
                            # Bei Kombination nur den LLM-Fehler dokumentieren
                            extracted_text = f"LLM-OCR Fehler: {str(llm_error)}"

                # Native Analyse durchführen, falls benötigt
                if extraction_method in [EXTRACTION_NATIVE, EXTRACTION_BOTH, EXTRACTION_PREVIEW_AND_NATIVE]:
                    # Hier könnte in Zukunft eine native Bildanalyse implementiert werden
                    # Aktuell wird für NATIVE als Fallback OCR verwendet
                    if not extracted_text and extraction_method != EXTRACTION_BOTH:  # Nur wenn noch kein Text vorhanden ist
                        try:
                            raw_text = pytesseract.image_to_string(  # type: ignore[attr-defined]
                                image=img,
                                lang='deu',  # Deutsche Sprache
                                config='--psm 3',  # Standard Page Segmentation Mode
                                output_type=pytesseract.Output.STRING
                            )
                            extracted_text = str(raw_text)
                            self.logger.debug("Native Analyse durch OCR-Fallback ersetzt")
                        except Exception as e:
                            self.logger.warning(f"Fehler bei der nativen Extraktion: {str(e)}")

                # Template-Transformation wenn gewünscht
                if template and extracted_text:
                    transform_result: TransformerResponse = self.transformer.transformByTemplate(
                        text=extracted_text,
                        template=template,
                        source_language="de",  # Default Deutsch
                        target_language="de",  # Default Deutsch
                        context=context or {}
                    )
                    
                    if transform_result.data and transform_result.data.text:
                        extracted_text = str(transform_result.data.text)
                        self.logger.debug("Text durch Template transformiert")
                
                # Ergebnis erstellen
                result = ImageOCRProcessingResult(
                    metadata=metadata,
                    extracted_text=extracted_text,
                    process_id=self.process_id
                )
                
                # Ergebnis im Cache speichern
                if use_cache and self.is_cache_enabled():
                    self.save_to_cache(cache_key, result)
                    self.logger.debug(f"Ergebnis im Cache gespeichert: {cache_key[:8]}...")
                
                
                return self.create_response(
                    processor_name="imageocr",
                    result=result,
                    request_info={
                        "file_path": str(file_path),
                        "template": template,
                        "context": context,
                        "extraction_method": extraction_method
                    },
                    response_class=ImageOCRResponse,
                    from_cache=False,
                    cache_key=cache_key
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
                    process_dir=str(working_dir),
                    extraction_method=extraction_method
                ),
                process_id=self.process_id
            )
            
            # Error-Response
            return self.create_response(
                processor_name="imageocr",
                result=dummy_result,
                request_info={
                    'file_path': str(file_path),
                    'template': template,
                    'context': context,
                    'extraction_method': extraction_method
                },
                response_class=ImageOCRResponse,
                error=error_info,
                from_cache=False,
                cache_key=""    
            )

    def check_file_size(self, file_path: Path) -> None:
        """Prüft ob die Dateigröße innerhalb der Limits liegt."""
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            raise ProcessingError(
                f"Datei zu groß: {file_size} Bytes "
                f"(Maximum: {self.max_file_size} Bytes)"
            ) 

    def _create_cache_key(self, 
                         file_path: Union[str, Path],
                         template: Optional[str] = None,
                         context: Optional[Dict[str, Any]] = None,
                         extraction_method: str = EXTRACTION_OCR,
                         file_hash: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel für OCR-Verarbeitung.
        
        Args:
            file_path: Pfad zum Bild
            template: Optional, das verwendete Template
            context: Optional, der Kontext für die Verarbeitung
            extraction_method: Die verwendete Extraktionsmethode
            file_hash: Optional, der Hash der Datei (wenn bereits berechnet)
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Wenn ein File-Hash übergeben wurde, diesen verwenden
        if file_hash:
            key_parts = [f"hash_{file_hash}"]
        else:
            # Dateistatistik für eindeutige Identifizierung verwenden
            file_size = None
            try:
                file_path_obj = Path(file_path)
                file_size = file_path_obj.stat().st_size
            except:
                # Fehlerbehandlung falls stat nicht möglich ist
                pass
                
            # Bei Bildern einen Hash-Wert des Bildinhalts generieren
            image_hash = None
            try:
                with open(file_path, 'rb') as f:
                    image_bytes = f.read(1024 * 1024)  # Ersten MB für Hash verwenden
                    image_hash = hashlib.md5(image_bytes).hexdigest()
            except:
                pass
            
            # Basis-Schlüssel aus Pfad, Dateigröße und Bildhash
            key_parts = [str(file_path)]
            
            if file_size:
                key_parts.append(f"size_{file_size}")
                
            if image_hash:
                key_parts.append(f"hash_{image_hash[:8]}")
        
        # Extraktionsmethode hinzufügen
        key_parts.append(f"method_{extraction_method}")
        
        # Template hinzufügen, wenn vorhanden
        if template:
            template_hash = hashlib.md5(template.encode()).hexdigest()[:8]
            key_parts.append(f"template_{template_hash}")
            
        # Kontext-Hash hinzufügen, wenn vorhanden
        if context:
            context_str = json.dumps(context, sort_keys=True)
            context_hash = hashlib.md5(context_str.encode()).hexdigest()[:8]
            key_parts.append(f"context_{context_hash}")
            
        # Schlüssel generieren
        return self.generate_cache_key("_".join(key_parts))
    
    def serialize_for_cache(self, result: ImageOCRProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das ImageOCRProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das OCR-Ergebnis
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Wir verwenden die bestehende to_dict Methode
        result_dict = result.to_dict()
        
        # Zusätzliche Cache-Metadaten
        cache_data = {
            "result": result_dict,
            "processed_at": datetime.now(UTC).isoformat(),
            "file_name": getattr(result.metadata, "file_name", ""),
            "file_size": getattr(result.metadata, "file_size", 0),
            "format": getattr(result.metadata, "format", ""),
            "dimensions": getattr(result.metadata, "dimensions", ""),
            "extraction_method": getattr(result.metadata, "extraction_method", EXTRACTION_OCR)
        }
        
        return cache_data
        
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> ImageOCRProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein ImageOCRProcessingResult.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            ImageOCRProcessingResult: Das deserialisierte ImageOCRProcessingResult
        """
        # Result-Objekt aus den Daten erstellen
        result_data = cached_data.get('result', {})
        
        # ImageOCRProcessingResult aus Dictionary erstellen
        result = ImageOCRProcessingResult.from_dict(result_data)
        
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
            index_definitions = [
                ("file_name", 1),
                ("file_size", 1),
                ("format", 1),
                ("dimensions", 1)
            ]
            
            for field, direction in index_definitions:
                index_name = f"{field}_{direction}"
                if index_name not in existing_indices:
                    collection.create_index([(field, direction)], background=True)
                    
        except Exception as e:
            self.logger.warning(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")
            
    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        Bereinigt alte Dateien im Working-Verzeichnis.
        
        Args:
            max_age_hours: Maximales Alter der Dateien in Stunden
            
        Returns:
            int: Anzahl der gelöschten Dateien
        """
        working_dir = self.get_working_dir()
        if not working_dir.exists():
            return 0
            
        count = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for file_path in working_dir.iterdir():
            if not file_path.is_file():
                continue
                
            # Prüfe Dateialter
            file_age = current_time - os.path.getmtime(file_path)
            if file_age > max_age_seconds:
                try:
                    os.unlink(file_path)
                    count += 1
                    self.logger.debug(f"Alte Datei gelöscht: {file_path}")
                except Exception as e:
                    self.logger.warning(f"Konnte Datei nicht löschen: {file_path}, Fehler: {str(e)}")
                    
        return count 