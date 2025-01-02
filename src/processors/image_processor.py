import os
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
import pytesseract
import time

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger, track_performance
from src.core.config import Config

class ImageProcessor(BaseProcessor):
    """Image Processor für die Verarbeitung von Bilddateien.
    
    Diese Klasse verarbeitet Bilder und extrahiert Text mittels OCR.
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        max_resolution (int): Maximale erlaubte Auflösung in Pixeln
        temp_dir (Path): Verzeichnis für temporäre Verarbeitung
        process_id (str): Eindeutige ID für den Verarbeitungsprozess
        logger: Logger-Instanz für diesen Processor
    """
    def __init__(self, resource_calculator):
        # Basis-Klasse initialisieren
        super().__init__(resource_calculator)
        
        # Konfiguration aus Config laden
        config = Config()
        image_config = config.get('processors.image', {})
        
        # Konfigurationswerte mit Validierung laden
        self.max_resolution = image_config.get('max_resolution', 4096)
        
        # Validierung der erforderlichen Konfigurationswerte
        if not self.max_resolution:
            raise ValueError("max_resolution muss in der Konfiguration angegeben werden")
        
        # Weitere Konfigurationswerte laden
        self.logger = get_logger(process_id=self.process_id, processor_name="ImageProcessor")
        self.temp_dir = Path(image_config.get('temp_dir', "temp-processing/image"))
        
        # Verzeichnisse erstellen
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.debug("Image Processor initialisiert",
                         max_resolution=self.max_resolution,
                         temp_dir=str(self.temp_dir))

    @track_performance("image_processing")
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
            self.logger.error("Bildverarbeitungsfehler", 
                            error=str(e),
                            file_path=str(path) if 'path' in locals() else None)
            raise ProcessingError(f"Bild Verarbeitungsfehler: {str(e)}") 