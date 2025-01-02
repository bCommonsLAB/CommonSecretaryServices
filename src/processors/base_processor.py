import os
import hashlib
import json
import time
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from src.core.resource_tracking import ResourceCalculator, ResourceUsage
from src.core.exceptions import FileSizeLimitExceeded
from src.core.config import Config

class BaseProcessor(ABC):
    """Basis-Klasse für alle Prozessoren im System.
    
    Diese abstrakte Basisklasse definiert die gemeinsame Schnittstelle und Grundfunktionalität
    für alle spezialisierten Prozessoren (Audio, Video, PDF, etc.).
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        calculator (ResourceCalculator): Calculator für Ressourcenverbrauch
        max_file_size (int): Maximale erlaubte Dateigröße in Bytes
        process_id (str): Eindeutige ID für den Verarbeitungsprozess
        logger: Logger-Instanz für diesen Processor
    """
    def __init__(self, resource_calculator: ResourceCalculator):
        # Konfiguration aus Config laden
        config = Config()
        base_config = config.get('processors.base', {})
        
        # Konfigurationswerte mit Validierung laden
        self.max_file_size = base_config.get('max_file_size', 104857600)  # Default: 100MB
        
        # Validierung der erforderlichen Parameter
        if not resource_calculator:
            raise ValueError("resource_calculator muss angegeben werden")
            
        # Basis-Attribute setzen
        self.calculator = resource_calculator
        self.process_id = str(int(time.time() * 1000))
        self.logger = None  # wird von Kindklassen gesetzt

    def check_file_size(self, file_path: Path) -> None:
        """Prüft, ob die Dateigröße das konfigurierte Limit überschreitet.
        
        Args:
            file_path (Path): Pfad zur zu prüfenden Datei
            
        Raises:
            FileSizeLimitExceeded: Wenn die Datei das Größenlimit überschreitet
        """
        if file_path.stat().st_size > self.max_file_size:
            raise FileSizeLimitExceeded(
                f"Datei zu groß: {file_path.stat().st_size} Bytes "
                f"(Maximum: {self.max_file_size} Bytes)"
            )

    @abstractmethod
    async def process(self, file_path: str) -> Dict[str, Any]:
        """Verarbeitet eine Datei und gibt die Ergebnisse zurück.
        
        Diese Methode muss von allen Kindklassen implementiert werden.
        
        Args:
            file_path (str): Pfad zur zu verarbeitenden Datei
            
        Returns:
            Dict[str, Any]: Verarbeitungsergebnisse in einem einheitlichen Format
            
        Raises:
            NotImplementedError: Wenn die Methode nicht von der Kindklasse implementiert wurde
        """
        raise NotImplementedError("process() muss von der Kindklasse implementiert werden") 