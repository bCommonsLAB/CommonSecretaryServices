# mypy: disable-error-code="attr-defined,valid-type,misc"
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

import traceback
import hashlib
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Any, Optional, Union, cast
from dataclasses import dataclass
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
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.response_factory import ResponseFactory
from src.core.models.transformer import TransformerResponse
from src.core.exceptions import ProcessingError
from src.processors.cacheable_processor import CacheableProcessor
from src.processors.transformer_processor import TransformerProcessor

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
            process_dir=cast(Optional[str], metadata_dict.get('process_dir'))  # type: ignore
        )
        
        # Ergebnis-Objekt erstellen
        return cls(
            metadata=metadata,
            extracted_text=cast(Optional[str], data.get('extracted_text')),
            process_id=cast(Optional[str], data.get('process_id'))
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
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
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
        use_cache: bool = True,
        file_hash: Optional[str] = None
    ) -> ImageOCRResponse:
        """
        Verarbeitet ein Bild mit OCR.
        
        Args:
            file_path: Pfad zur Bilddatei
            template: Optional Template für die Verarbeitung
            context: Optionaler Kontext
            use_cache: Ob der Cache verwendet werden soll
            file_hash: Optional, der Hash der Datei (wenn bereits berechnet)
            
        Returns:
            ImageOCRResponse: Die standardisierte Response
        """
        # Initialisiere working_dir am Anfang
        working_dir = self.get_working_dir()
        
        try:
            # Initialisiere cache_key früh im Code
            cache_key = ""
            
            # Bei Cache-Nutzung, erzeuge den Cache-Key
            if use_cache and self.is_cache_enabled():
                cache_key = self._create_cache_key(
                    file_path=file_path,
                    template=template,
                    context=context,
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
                return ResponseFactory.create_response(
                    processor_name="imageocr",
                    result=cached_result,
                    request_info={
                        "file_path": str(file_path),
                        "template": template,
                        "context": context
                    },
                    response_class=ImageOCRResponse,
                    llm_info=None,
                    from_cache=True
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
            
            # LLM-Info initialisieren (leeres Tracking-Objekt)
            llm_info = LLMInfo(
                model="imageocr-processing",
                purpose="imageocr-processing"
            )
            
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
                
                # Ergebnis im Cache speichern
                if use_cache and self.is_cache_enabled():
                    self.save_to_cache(cache_key, result)
                    self.logger.debug(f"Ergebnis im Cache gespeichert: {cache_key[:8]}...")
                
                # Response erstellen
                self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}")
                
                return ResponseFactory.create_response(
                    processor_name="imageocr",
                    result=result,
                    request_info={
                        "file_path": str(file_path),
                        "template": template,
                        "context": context
                    },
                    response_class=ImageOCRResponse,
                    llm_info=None,
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
                processor_name="imageocr",
                result=dummy_result,
                request_info={
                    'file_path': str(file_path),
                    'template': template,
                    'context': context
                },
                response_class=ImageOCRResponse,
                error=error_info,
                llm_info=None,
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

    def _create_cache_key(self, 
                         file_path: Union[str, Path],
                         template: Optional[str] = None,
                         context: Optional[Dict[str, Any]] = None,
                         file_hash: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel für OCR-Verarbeitung.
        
        Args:
            file_path: Pfad zum Bild
            template: Optional, das verwendete Template
            context: Optional, der Kontext für die Verarbeitung
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
            "dimensions": getattr(result.metadata, "dimensions", "")
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