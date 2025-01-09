import os
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
import pytesseract
import time
import traceback

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.core.config import Config

class ImageProcessor(BaseProcessor):
    """
    Prozessor für die Verarbeitung von Bildern.
    Extrahiert Text mittels OCR und berechnet Ressourcenverbrauch.
    """
    
    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """
        Initialisiert den ImageProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Process-ID für Tracking
        """
        super().__init__(process_id)
        self.calculator = resource_calculator
        self.logger = get_logger(process_id, self.__class__.__name__)
        
        # Lade Konfiguration
        config = Config()
        self.max_file_size = config.get('processors.image.max_file_size', 10 * 1024 * 1024)  # 10MB
        self.max_resolution = config.get('processors.image.max_resolution', 4096)  # 4K
        
    def check_file_size(self, file_path: Path) -> None:
        """Prüft ob die Dateigröße innerhalb der Limits liegt."""
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            raise ProcessingError(
                f"Datei zu groß: {file_size} Bytes "
                f"(Maximum: {self.max_file_size} Bytes)"
            )

    async def process(self, file_path: str) -> Dict[str, Any]:
        """Verarbeitet ein Bild und extrahiert Text mittels OCR.
        
        Args:
            file_path (str): Pfad zur Bilddatei
            
        Returns:
            Dict[str, Any]: Verarbeitungsergebnisse mit extrahiertem Text und Metadaten
            
        Raises:
            ProcessingError: Bei Fehlern während der Verarbeitung
        """
        try:
            path = Path(file_path)
            self.logger.info("Starte Bildverarbeitung", 
                           file_path=str(path),
                           file_size=path.stat().st_size)
            
            with self.measure_operation('image_processing'):
                self.check_file_size(path)
                start_time = time.time()
                
                # Bild öffnen und prüfen
                with Image.open(file_path) as img:
                    width, height = img.size
                    self.logger.debug("Bild geöffnet", 
                                    dimensions=f"{width}x{height}",
                                    format=img.format)
                    
                    if width > self.max_resolution or height > self.max_resolution:
                        raise ProcessingError(
                            f"Bildauflösung zu groß: {width}x{height} "
                            f"(Maximum: {self.max_resolution}x{self.max_resolution})"
                        )
                    
                    # Text extrahieren
                    self.logger.debug("Starte OCR-Verarbeitung")
                    text = pytesseract.image_to_string(img)
                    self.logger.debug("OCR abgeschlossen", 
                                    text_length=len(text))

                processing_time = time.time() - start_time

                # Ressourcenverbrauch berechnen
                resources = [
                    ResourceUsage("storage", self.calculator.calculate_storage_units(path.stat().st_size), "MB"),
                    ResourceUsage("compute", self.calculator.calculate_compute_units(processing_time), "seconds")
                ]
                
                result = {
                    "file_name": str(path),
                    "file_size": path.stat().st_size,
                    "dimensions": f"{width}x{height}",
                    "text": text,
                    "resources_used": resources,
                    "total_units": self.calculator.calculate_total_units(resources)
                }
                
                self.logger.info("Bildverarbeitung abgeschlossen", 
                               processing_time=processing_time,
                               text_length=len(text))
                
                return result
                
        except Exception as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'stack_trace': traceback.format_exc(),
                'stage': 'image_processing',
                'file_path': str(path) if 'path' in locals() else None,
                'dimensions': f"{width}x{height}" if 'width' in locals() and 'height' in locals() else None
            }
            
            self.logger.error("Bildverarbeitungsfehler", 
                            **error_context)
            raise ProcessingError(f"Bild Verarbeitungsfehler: {str(e)}") 