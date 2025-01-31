"""
Base processor module that defines the common interface and functionality for all processors.
"""
import uuid
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, ContextManager, Dict, Optional

import yaml

from src.core.exceptions import ValidationError
from src.core.models.base import ErrorInfo, ProcessInfo, RequestInfo
from src.core.models.llm import LLMInfo
from src.utils.logger import ProcessingLogger, get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.utils.resource_calculator import ResourceCalculator


class BaseProcessorResponse:
    """Basis-Klasse für alle Processor-Responses."""
    
    def __init__(self, processor_name: str) -> None:
        """
        Initialisiert die Basis-Response.
        
        Args:
            processor_name (str): Name des Processors
        """
        self.request: RequestInfo = RequestInfo(
            processor=processor_name,
            timestamp=datetime.now().isoformat(),
            parameters={}
        )
        
        self.process: ProcessInfo = ProcessInfo(
            id=str(uuid.uuid4()),
            main_processor=processor_name,
            sub_processors=[],
            started=datetime.now().isoformat()
        )
        
        self.error: Optional[ErrorInfo] = None
        
    def add_parameter(self, key: str, value: Any) -> None:
        """Fügt einen Parameter zur Request-Info hinzu."""
        self.request.parameters[key] = value
        
    def add_sub_processor(self, name: str) -> None:
        """Fügt einen Sub-Processor zur Process-Info hinzu."""
        if name not in self.process.sub_processors:
            self.process.sub_processors.append(name)
            
    def add_llm_info(self, model: str, purpose: str, tokens: int, duration: float) -> None:
        """Fügt LLM-Informationen zur Process-Info hinzu."""
        llm_info = LLMInfo(
            model=model,
            purpose=purpose,
            tokens=tokens,
            duration=duration
        )
        if not hasattr(self.process, 'llm_info'):
            setattr(self.process, 'llm_info', [])
        getattr(self.process, 'llm_info').append(llm_info)
        
    def set_error(self, error: ErrorInfo) -> None:
        """Setzt die Fehlerinformation."""
        self.error = error
        
    def set_completed(self) -> None:
        """Markiert den Prozess als abgeschlossen."""
        self.process.completed = datetime.now().isoformat()

class BaseProcessor:
    """
    Basis-Klasse für alle Prozessoren.
    Definiert gemeinsame Funktionalität und Schnittstellen.
    
    Attributes:
        process_id (str): Eindeutige ID für den Verarbeitungsprozess
        temp_dir (Path): Temporäres Verzeichnis für Verarbeitungsdateien
        logger (ProcessingLogger): Logger-Instanz für den Processor
        resource_calculator (ResourceCalculator): Calculator für Ressourcenverbrauch
    """
    
    # Konstanten für Validierung
    SUPPORTED_LANGUAGES = {'de', 'en', 'fr', 'es', 'it'}  # Beispiel, sollte aus Config kommen
    SUPPORTED_FORMATS = {'text', 'html', 'markdown'}
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den BaseProcessor.
        
        Args:
            resource_calculator (ResourceCalculator): Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID. 
                                      Wenn None, wird eine neue UUID generiert.
                                      Im Normalfall sollte diese ID vom API-Layer kommen.
        """
        self.process_id = process_id or str(uuid.uuid4())
        self.resource_calculator = resource_calculator
        self.logger: Optional[ProcessingLogger] = None
        self.temp_dir: Optional[Path] = None

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
            
        language_code = language_code.lower()
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
            if self.logger:
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
            
        try:
            # Versuche auf dict-spezifische Methoden zuzugreifen
            context.keys()
            context.values()
            return context
        except AttributeError:
            if self.logger:
                self.logger.warning("Context ist kein Dictionary, wird ignoriert",
                    context_type=type(context).__name__,
                    context_value=str(context)[:200] if context else None)
            return None

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
            
        self.temp_dir = Path(str(temp_path))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        return self.temp_dir

    def init_logger(self, processor_name: Optional[str] = None) -> ProcessingLogger:
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

    def measure_operation(self, operation_name: str) -> ContextManager[object]:
        """
        Context Manager zum Messen der Performance einer Operation.
        
        Args:
            operation_name (str): Name der Operation die gemessen werden soll
            
        Returns:
            ContextManager[object]: Context Manager für die Performance-Messung
        """
        tracker = get_performance_tracker()
        if tracker:
            return tracker.measure_operation(operation_name, self.__class__.__name__)
        return nullcontext()

    def load_processor_config(self, processor_name: str) -> Dict[str, Any]:
        """
        Lädt die Konfiguration für einen spezifischen Processor aus der config.yaml.
        
        Args:
            processor_name (str): Name des Processors (z.B. 'transformer', 'metadata')
            
        Returns:
            Dict[str, Any]: Processor-spezifische Konfiguration
            
        Raises:
            KeyError: Wenn keine Konfiguration für den Processor gefunden wurde
        """
        try:
            # Lade die Konfigurationsdatei
            config_path = Path("config/config.yaml")
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            
            # Hole die processor-spezifische Konfiguration
            processor_config = config.get("processors", {}).get(processor_name, {})
            
            if not processor_config and self.logger:
                self.logger.warning(
                    f"Keine Konfiguration für Processor '{processor_name}' gefunden",
                    processor=processor_name
                )
            
            return processor_config
            
        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Fehler beim Laden der Processor-Konfiguration",
                    error=e,
                    processor=processor_name
                )
            return {} 