"""
Base processor module that defines the common interface and functionality for all processors.
"""
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from src.utils.performance_tracker import get_performance_tracker
from src.core.config import Config
from src.utils.logger import get_logger
from src.utils.types import RequestInfo, ProcessInfo, ErrorInfo, LLMInfo
from src.core.exceptions import ValidationError

class BaseProcessorResponse:
    """Basis-Klasse für alle Processor-Responses."""
    
    def __init__(self, processor_name: str):
        """
        Initialisiert die Basis-Response.
        
        Args:
            processor_name (str): Name des Processors
        """
        self.request = RequestInfo(
            processor=processor_name,
            timestamp=datetime.now().isoformat(),
            parameters={}
        )
        
        self.process = ProcessInfo(
            id=str(uuid.uuid4()),
            main_processor=processor_name,
            sub_processors=[],
            started=datetime.now().isoformat(),
            llm_info=[]
        )
        
        self.error: Optional[ErrorInfo] = None
        
    def add_parameter(self, key: str, value: Any):
        """Fügt einen Parameter zur Request-Info hinzu."""
        self.request.parameters[key] = value
        
    def add_sub_processor(self, name: str):
        """Fügt einen Sub-Processor zur Process-Info hinzu."""
        if name not in self.process.sub_processors:
            self.process.sub_processors.append(name)
            
    def add_llm_info(self, model: str, purpose: str, tokens: int, duration: float):
        """Fügt LLM-Informationen zur Process-Info hinzu."""
        self.process.llm_info.append(LLMInfo(
            model=model,
            purpose=purpose,
            tokens=tokens,
            duration=duration
        ))
        
    def set_error(self, error: ErrorInfo):
        """Setzt die Fehlerinformation."""
        self.error = error
        
    def set_completed(self):
        """Markiert den Prozess als abgeschlossen."""
        self.process.completed = datetime.now().isoformat()

class BaseProcessor:
    """
    Basis-Klasse für alle Prozessoren.
    Definiert gemeinsame Funktionalität und Schnittstellen.
    
    Attributes:
        process_id (str): Eindeutige ID für den Verarbeitungsprozess
        temp_dir (Path): Temporäres Verzeichnis für Verarbeitungsdateien
        logger: Logger-Instanz für den Processor
        resource_calculator: Calculator für Ressourcenverbrauch
    """
    
    # Konstanten für Validierung
    SUPPORTED_LANGUAGES = {'de', 'en', 'fr', 'es', 'it'}  # Beispiel, sollte aus Config kommen
    SUPPORTED_FORMATS = {'text', 'html', 'markdown'}
    
    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """
        Initialisiert den BaseProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID. 
                                      Wenn None, wird eine neue UUID generiert.
                                      Im Normalfall sollte diese ID vom API-Layer kommen.
        """
        # Wenn keine Process-ID übergeben wurde, generiere eine neue
        # Dies sollte nur in Test-Szenarien oder Standalone-Verwendung passieren
        self.process_id = process_id or str(uuid.uuid4())
        
        # Resource Calculator speichern
        self.resource_calculator = resource_calculator
        
        # Logger initialisieren
        self.logger = None
        
        # Temporäres Verzeichnis für die Verarbeitung
        self.temp_dir = None

    def validate_text(self, text: Optional[str], field_name: str = "text") -> str:
        """
        Validiert einen Text-Input.
        
        Args:
            text: Der zu validierende Text
            field_name: Name des Feldes für Fehlermeldungen
            
        Returns:
            str: Der validierte Text
            
        Raises:
            ValidationError: Wenn der Text ungültig ist
        """
        if not text:
            raise ValidationError(f"{field_name} darf nicht leer sein")
        
        cleaned_text = text.strip()
        if not cleaned_text:
            raise ValidationError(f"{field_name} darf nicht nur aus Whitespace bestehen")
            
        return cleaned_text

    def validate_language_code(self, language_code: Optional[str], field_name: str = "language") -> str:
        """
        Validiert einen Sprach-Code.
        
        Args:
            language_code: Der zu validierende Sprach-Code
            field_name: Name des Feldes für Fehlermeldungen
            
        Returns:
            str: Der validierte Sprach-Code
            
        Raises:
            ValidationError: Wenn der Sprach-Code ungültig ist
        """
        if not language_code:
            raise ValidationError(f"{field_name} muss angegeben werden")
            
        language_code = language_code.lower()  # Konvertiere zu Kleinbuchstaben vor der Validierung
        if language_code not in self.SUPPORTED_LANGUAGES:
            raise ValidationError(f"Nicht unterstützter {field_name}: {language_code}")
            
        return language_code

    def validate_format(self, format_str: Optional[str], default: str = "text") -> str:
        """
        Validiert ein Format.
        
        Args:
            format_str: Das zu validierende Format
            default: Standard-Format wenn keins angegeben
            
        Returns:
            str: Das validierte Format
            
        Raises:
            ValidationError: Wenn das Format ungültig ist
        """
        if not format_str:
            return default
            
        if format_str not in self.SUPPORTED_FORMATS:
            self.logger.warning(f"Ungültiges Format '{format_str}', verwende '{default}'")
            return default
            
        return format_str

    def validate_context(self, context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Validiert einen Kontext.
        
        Args:
            context: Der zu validierende Kontext
            
        Returns:
            Optional[Dict[str, Any]]: Der validierte Kontext oder None
        """
        if context is None:
            return None
            
        if not isinstance(context, dict):
            self.logger.warning("Context ist kein Dictionary, wird ignoriert",
                context_type=type(context).__name__,
                context_value=str(context)[:200] if context else None)
            return None
            
        return context

    def init_temp_dir(self, processor_name: str, config: Optional[Dict[str, Any]] = None) -> Path:
        """
        Initialisiert das temporäre Verzeichnis für den Processor.
        
        Args:
            processor_name (str): Name des Processors für den Unterordner
            config (Dict[str, Any], optional): Processor-Konfiguration, falls vorhanden
            
        Returns:
            Path: Pfad zum temporären Verzeichnis
        """
        if config and 'temp_dir' in config:
            temp_path = config.get('temp_dir')
        else:
            temp_path = f"temp-processing/{processor_name.lower()}"
            
        self.temp_dir = Path(temp_path)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        return self.temp_dir

    def init_logger(self, processor_name: Optional[str] = None):
        """
        Initialisiert den Logger für den Processor.
        
        Args:
            processor_name (str, optional): Name des Processors. 
                                          Wenn None, wird der Klassenname verwendet.
        """
        if processor_name is None:
            processor_name = self.__class__.__name__
        self.logger = get_logger(process_id=self.process_id, processor_name=processor_name)
        return self.logger

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

    def load_processor_config(self, processor_name: str) -> Dict[str, Any]:
        """
        Lädt die Konfiguration für einen spezifischen Processor.
        
        Args:
            processor_name (str): Name des Processors (z.B. 'transformer', 'metadata')
            
        Returns:
            Dict[str, Any]: Processor-spezifische Konfiguration
        """
        config = Config()
        processors_config = config.get('processors', {})
        return processors_config.get(processor_name, {}) 