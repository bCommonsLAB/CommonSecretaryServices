from PIL import Image
import pytesseract
from typing import Dict, Any
from pathlib import Path
import time

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import ProcessingLogger

class ImageProcessor(BaseProcessor):
    def __init__(self, resource_calculator, max_file_size: int, max_resolution: int = 4096):
        super().__init__(resource_calculator, max_file_size)
        self.max_resolution = max_resolution
        self.logger = ProcessingLogger(process_id=self.process_id)
        self.temp_dir = Path("temp-processing/image")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @ProcessingLogger.track_performance("image_processing")
    async def process(self, file_path: str) -> Dict[str, Any]:
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
                            error=e,
                            file_path=str(path) if 'path' in locals() else None)
            raise ProcessingError(f"Bild Verarbeitungsfehler: {str(e)}") 