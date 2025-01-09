import fitz  # PyMuPDF
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import time
from PIL import Image
import pytesseract
import json
import traceback

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.core.config import Config

class PDFProcessor(BaseProcessor):
    """
    Prozessor für die Verarbeitung von PDF-Dateien.
    Extrahiert Text mittels OCR und berechnet Ressourcenverbrauch.
    """
    
    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """
        Initialisiert den PDFProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Process-ID für Tracking
        """
        super().__init__(process_id)
        self.calculator = resource_calculator
        self.logger = get_logger(process_id, self.__class__.__name__)
        
        # Lade Konfiguration
        config = Config()
        self.max_file_size = config.get('processors.pdf.max_file_size', 50 * 1024 * 1024)  # 50MB
        self.max_pages = config.get('processors.pdf.max_pages', 100)  # 100 Seiten
        
    def check_file_size(self, file_path: Path) -> None:
        """Prüft ob die Dateigröße innerhalb der Limits liegt."""
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            raise ProcessingError(
                f"Datei zu groß: {file_size} Bytes "
                f"(Maximum: {self.max_file_size} Bytes)"
            )
            
    def save_page_text(self, text: str, page_num: int, process_dir: Path) -> Path:
        """Speichert den extrahierten Text einer Seite."""
        text_path = process_dir / f"page_{page_num+1}.txt"
        text_path.write_text(text, encoding='utf-8')
        return text_path

    async def process(self, file_path: str) -> Dict[str, Any]:
        """Verarbeitet eine PDF-Datei und extrahiert Text mittels OCR.
        
        Args:
            file_path (str): Pfad zur PDF-Datei
            
        Returns:
            Dict[str, Any]: Verarbeitungsergebnisse mit extrahiertem Text und Metadaten
            
        Raises:
            ProcessingError: Bei Fehlern während der Verarbeitung
        """
        try:
            path = Path(file_path)
            self.logger.info("Starte PDF-Verarbeitung", 
                           file_path=str(path),
                           file_size=path.stat().st_size)
            
            with self.measure_operation('pdf_processing'):
                self.check_file_size(path)
                start_time = time.time()
                
                # Erstelle Verarbeitungsverzeichnis
                process_dir = self.temp_dir / self.process_id
                process_dir.mkdir(parents=True, exist_ok=True)
                
                # PDF öffnen und prüfen
                pdf_document = fitz.open(file_path)
                page_count = len(pdf_document)
                
                if page_count > self.max_pages:
                    raise ProcessingError(
                        f"PDF hat zu viele Seiten: {page_count} "
                        f"(Maximum: {self.max_pages})"
                    )
                
                self.logger.info(f"PDF geöffnet: {page_count} Seiten")
                
                # Verarbeite jede Seite
                full_text = ""
                image_paths = []
                text_paths = []   # Speichert Pfade zu den Textdateien
                
                for page_num in range(page_count):
                    page_start_time = time.time()
                    
                    # Seite in Bild umwandeln
                    self.logger.debug(f"Verarbeite Seite {page_num + 1}/{page_count}")
                    page = pdf_document[page_num]
                    pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))  # 300 DPI
                    
                    # Bild speichern
                    image_path = process_dir / f"page_{page_num+1}.png"
                    pix.save(str(image_path))
                    image_paths.append(image_path)
                    
                    # OCR durchführen
                    img = Image.open(image_path)
                    page_text = pytesseract.image_to_string(img)
                    
                    # Text speichern
                    text_path = self.save_page_text(page_text, page_num, process_dir)
                    text_paths.append(text_path)
                    
                    page_processing_time = time.time() - page_start_time
                    self.logger.debug(f"Seite {page_num + 1} verarbeitet",
                                    duration=page_processing_time,
                                    image_path=str(image_path),
                                    text_path=str(text_path))
                    
                    # Text zum Gesamttext hinzufügen
                    full_text += f"\n--- Seite {page_num+1} ---\n{page_text}\n"
                    
                    # Speicher freigeben
                    del pix
                    img.close()
                    page = None
                
                pdf_document.close()
                processing_time = time.time() - start_time
                
                # Ressourcenverbrauch berechnen
                resources = [
                    ResourceUsage("storage", self.calculator.calculate_storage_units(path.stat().st_size), "MB"),
                    ResourceUsage("compute", self.calculator.calculate_compute_units(processing_time), "seconds")
                ]
                
                # Zusammenfassung in JSON speichern
                summary = {
                    "original_file": str(path),
                    "page_count": page_count,
                    "process_time": processing_time,
                    "resources": [{"type": r.type, "amount": r.amount, "unit": r.unit} for r in resources]
                }
                summary_path = process_dir / "summary.json"
                with open(summary_path, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, indent=2)
                
                result = {
                    "title": Path(file_path).stem,  # PDF-Dateiname ohne Erweiterung
                    "file_name": str(path),
                    "file_size": path.stat().st_size,
                    "text": full_text,
                    "page_count": page_count,
                    "process_id": self.process_id,
                    "image_paths": [str(p) for p in image_paths],
                    "text_paths": [str(p) for p in text_paths],
                    "summary_path": str(summary_path),
                    "resources_used": resources,
                    "total_units": self.calculator.calculate_total_units(resources)
                }
                
                return result
                
        except Exception as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'stack_trace': traceback.format_exc(),
                'stage': 'pdf_processing',
                'file_path': str(path) if 'path' in locals() else None,
                'page_count': page_count if 'page_count' in locals() else None
            }
            
            self.logger.error("PDF Verarbeitungsfehler", 
                            **error_context)
            raise ProcessingError(f"PDF Verarbeitungsfehler: {str(e)}")

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