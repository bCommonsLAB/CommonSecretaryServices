"""
Base processor module that defines the common interface and functionality for all processors.
"""
import uuid
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, ContextManager, Dict, Optional, BinaryIO, Tuple
import os

import yaml

from src.core.exceptions import ValidationError
from src.core.models.base import ErrorInfo, ProcessInfo, RequestInfo
from src.core.config import Config
from src.utils.logger import ProcessingLogger, get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.core.resource_tracking import ResourceCalculator


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
    
    def add_parameter(self, name: str, value: Any) -> None:
        """
        Fügt einen Parameter zur Request hinzu.
        
        Args:
            name (str): Name des Parameters
            value (Any): Wert des Parameters
        """
        self.request.parameters[name] = value
    
    def add_sub_processor(self, processor_name: str) -> None:
        """
        Fügt einen Sub-Processor zur Prozessinfo hinzu.
        
        Args:
            processor_name (str): Name des Sub-Processors
        """
        if processor_name not in self.process.sub_processors:
            self.process.sub_processors.append(processor_name)
    
    def add_llm_info(self, model: str, prompt_template: str, tokens: int, duration: float) -> None:
        """
        Fügt LLM-Informationen zur Prozessinfo hinzu.
        
        Args:
            model (str): Verwendetes LLM-Modell
            prompt_template (str): Name des verwendeten Prompt-Templates
            tokens (int): Anzahl der verwendeten Tokens
            duration (float): Dauer des LLM-Aufrufs in Sekunden
        """
        if not hasattr(self.process, 'llm_info'):
            self.process.llm_info = []  # type: ignore
        
        self.process.llm_info.append({  # type: ignore
            'model': model,
            'prompt_template': prompt_template,
            'tokens': tokens,
            'duration': duration
        })
    
    def set_error(self, error: ErrorInfo) -> None:
        """
        Setzt eine Fehlermeldung.
        
        Args:
            error (ErrorInfo): Fehlerinformation
        """
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
        self.logger = self.init_logger()
        
        # Verwende Prozessor-spezifische Konfiguration für Cache
        processor_name = self.__class__.__name__.lower().replace('processor', '')
        processor_config = self.load_processor_config(processor_name)
        
        # Initialisiere den Cache-Pfad und den Temp-Pfad
        self.cache_dir = self.get_cache_dir(processor_name, processor_config)
        self.temp_dir = self.get_cache_dir(processor_name, processor_config, subdirectory="temp")

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
        DEPRECATED: Diese Methode wird in zukünftigen Versionen entfernt. 
        Bitte verwenden Sie get_cache_dir mit subdirectory="temp".
        
        Behält die Abwärtskompatibilität für bestehende Prozessoren.
        
        Args:
            processor_name (str): Name des Processors (ohne "processor" am Ende)
            config (Dict[str, Any], optional): Processor-Konfiguration, falls vorhanden
            
        Returns:
            Path: Pfad zum temporären Verzeichnis
        """
        self.logger.warning(
            "Die Methode init_temp_dir ist veraltet und wird in zukünftigen Versionen entfernt. "
            "Bitte verwenden Sie get_cache_dir mit subdirectory='temp'."
        )
        
        # Rufe get_cache_dir mit dem Unterverzeichnis 'temp' auf
        return self.get_cache_dir(processor_name, config, subdirectory="temp")

    def get_upload_temp_file(self, suffix: str = "", prefix: str = "upload_", delete: bool = False) -> Tuple[BinaryIO, str]:
        """
        Erstellt eine benannte temporäre Datei im konfigurierten temporären Verzeichnis.
        Diese Methode sollte anstelle von tempfile.NamedTemporaryFile in Route-Handlern verwendet werden.
        
        Args:
            suffix (str): Optionale Dateierweiterung (z.B. ".pdf")
            prefix (str): Optionales Präfix für den Dateinamen
            delete (bool): Ob die Datei automatisch gelöscht werden soll (nicht empfohlen)
            
        Returns:
            Tuple[BinaryIO, str]: Ein Tupel aus (Datei-Objekt, Dateipfad)
            
        Beispiel:
            temp_file, temp_path = processor.get_upload_temp_file(suffix=".pdf")
            with open(temp_path, 'wb') as f:
                f.write(content)
            # oder
            temp_file.write(content)
            temp_file.flush()
        """
        # Erstelle einen eindeutigen Dateinamen
        temp_filename = f"{prefix}{uuid.uuid4().hex}{suffix}"
        
        # Verwende das temp-Unterverzeichnis im Cache
        if not hasattr(self, 'temp_dir'):
            # Fallback für Abwärtskompatibilität, falls temp_dir noch nicht initialisiert ist
            processor_name = self.__class__.__name__.lower().replace('processor', '')
            self.temp_dir = self.get_cache_dir(processor_name, subdirectory="temp")
            
        temp_path = self.temp_dir / "uploads" / temp_filename
        
        # Stelle sicher, dass das Upload-Verzeichnis existiert
        (self.temp_dir / "uploads").mkdir(parents=True, exist_ok=True)
        
        # Erstelle die Datei
        temp_file = open(str(temp_path), 'wb+')
        
        # Wenn delete=True, registriere die Datei zum automatischen Löschen
        if delete:
            temp_file.close()
            temp_file = open(str(temp_path), 'wb+')
            
            # Lösche die Datei beim Schließen
            original_close = temp_file.close
            def new_close():
                original_close()
                try:
                    os.unlink(str(temp_path))
                except Exception as e:
                    # Stille Ausnahme, aber wir könnten hier loggen
                    if self.logger:
                        self.logger.debug(f"Fehler beim Löschen der temporären Datei: {e}")
                    pass
            temp_file.close = new_close
            
        return temp_file, str(temp_path)

    def get_cache_dir(self, processor_name: str, config: Optional[Dict[str, Any]] = None, 
                      subdirectory: Optional[str] = None) -> Path:
        """
        Gibt das Cache-Verzeichnis für den Processor zurück. 
        Optional kann ein Unterverzeichnis angegeben werden, z.B. "temp" für temporäre Dateien
        oder "processed" für verarbeitete Dateien.
        
        Args:
            processor_name (str): Name des Processors für den Unterordner
            config (Dict[str, Any], optional): Processor-Konfiguration, falls vorhanden
            subdirectory (str, optional): Optionales Unterverzeichnis im Cache
            
        Returns:
            Path: Pfad zum Cache-Verzeichnis
        """
        # Lade die Basis-Konfiguration
        app_config = Config()
        cache_base = Path(app_config.get('cache', {}).get('base_dir', './cache'))
        
        if config and 'cache_dir' in config:
            # Verwende konfigurierten Pfad
            cache_path = config.get('cache_dir')
            base_cache_dir = Path(str(cache_path))
        else:
            # Erstelle Standard-Pfad im Cache-Verzeichnis
            base_cache_dir = cache_base / processor_name.lower()
        
        # Wenn ein Unterverzeichnis angegeben ist, füge es zum Pfad hinzu
        if subdirectory:
            cache_dir = base_cache_dir / subdirectory
        else:
            cache_dir = base_cache_dir
            
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

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