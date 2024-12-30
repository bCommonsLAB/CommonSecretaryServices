from pathlib import Path
from typing import Dict, Any
from abc import ABC, abstractmethod
import time

# Absolute Imports
from core.resource_tracking import ResourceCalculator, ResourceUsage
from core.exceptions import FileSizeLimitExceeded

class BaseProcessor(ABC):
    def __init__(self, resource_calculator: ResourceCalculator, max_file_size: int):
        self.calculator = resource_calculator
        self.max_file_size = max_file_size
        # Generiere eine eindeutige Process ID beim Erstellen
        self.process_id = str(int(time.time() * 1000))
        self.logger = None  # wird von Kindklassen gesetzt

    def check_file_size(self, file_path: Path) -> None:
        """Prüft, ob die Dateigröße das Limit überschreitet"""
        if file_path.stat().st_size > self.max_file_size:
            raise FileSizeLimitExceeded(
                f"Datei zu groß: {file_path.stat().st_size} Bytes "
                f"(Maximum: {self.max_file_size} Bytes)"
            )

    @abstractmethod
    async def process(self, file_path: str) -> Dict[str, Any]:
        """Verarbeitet eine Datei und gibt die Ergebnisse zurück"""
        pass 