"""
Base processor module that defines the common interface and functionality for all processors.
"""
import uuid
from pathlib import Path
from typing import Optional
from src.utils.performance_tracker import get_performance_tracker

class BaseProcessor:
    """
    Basis-Klasse für alle Prozessoren.
    Definiert gemeinsame Funktionalität und Schnittstellen.
    
    Attributes:
        process_id (str): Eindeutige ID für den Verarbeitungsprozess
        temp_dir (Path): Temporäres Verzeichnis für Verarbeitungsdateien
    """
    
    def __init__(self, process_id: Optional[str] = None):
        """
        Initialisiert den BaseProcessor.
        
        Args:
            process_id (str, optional): Die zu verwendende Process-ID. 
                                      Wenn None, wird eine neue UUID generiert.
                                      Im Normalfall sollte diese ID vom API-Layer kommen.
        """
        # Wenn keine Process-ID übergeben wurde, generiere eine neue
        # Dies sollte nur in Test-Szenarien oder Standalone-Verwendung passieren
        self.process_id = process_id or str(uuid.uuid4())
        
        # Temporäres Verzeichnis für die Verarbeitung
        self.temp_dir = Path('./temp-processing')
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
    def measure_operation(self, operation_name: str):
        """
        Context Manager zum Messen der Performance einer Operation.
        
        Args:
            operation_name (str): Name der Operation die gemessen werden soll
            
        Returns:
            Context Manager für die Performance-Messung
        """
        tracker = get_performance_tracker()
        if tracker:
            return tracker.measure_operation(operation_name, self.__class__.__name__)
        else:
            # Wenn kein Tracker verfügbar ist, gib einen Dummy-Context-Manager zurück
            from contextlib import nullcontext
            return nullcontext() 