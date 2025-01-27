"""
Logger implementation for the processing service.

Die Logger-Klasse implementiert ein zentrales Logging-System mit folgenden Hauptfunktionen:
- Einheitliches Logging-Format über alle Prozesse
- Session-Tracking über process_id
- Strukturierte Logs mit zusätzlichen Metadaten
- Automatische Rotation der Logfiles
"""
import logging
import json
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict, cast, TypeVar, Union, Mapping, Sequence, TypeGuard, overload
import sys
import os
import yaml
from logging import Handler, LogRecord, Logger

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')

class LogConfig(TypedDict):
    """Konfigurationstyp für das Logging."""
    level: str
    file: str
    max_size: int
    backup_count: int

class YAMLConfig(TypedDict, total=False):
    """Konfigurationstyp für die YAML-Datei."""
    logging: Dict[str, Union[str, int]]

class ExtraDict(TypedDict):
    """Typ für zusätzliche Logging-Informationen."""
    process_id: str
    processor_name: str
    kwargs: Optional[str]

class LoggerService:
    """
    Zentraler Logger-Service für die Anwendung.
    Verwaltet die Logger-Instanzen und Handler für verschiedene Prozesse.
    Stellt sicher, dass die Log-Datei nur einmal initialisiert wird.
    """
    _instance: Optional['LoggerService'] = None
    _shared_handlers_initialized: bool = False
    _loggers: Dict[str, 'ProcessingLogger'] = {}
    _console_handler: Optional[Handler] = None
    _detail_handler: Optional[Handler] = None

    def __new__(cls) -> 'LoggerService':
        if cls._instance is None:
            cls._instance = super(LoggerService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Initialisiert den LoggerService"""
        if not self._shared_handlers_initialized:
            self._initialize_handlers()
            
    @classmethod
    def reset(cls) -> 'LoggerService':
        """Setzt alle Logger zurück und initialisiert sie neu."""
        # Entferne alle existierenden Handler
        for logger_name in logging.root.manager.loggerDict:
            logger = logging.getLogger(logger_name)
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
        
        # Setze die Klassen-Attribute zurück
        cls._shared_handlers_initialized = False
        cls._loggers = {}
        cls._console_handler = None
        cls._detail_handler = None
        
        # Erstelle eine neue Instanz
        return cls()
    
    def _load_config(self) -> LogConfig:
        """Lädt die Logging-Konfiguration aus config.yaml"""
        default_config: LogConfig = {
            'level': 'INFO',
            'file': 'logs/detailed.log',
            'max_size': 10485760,
            'backup_count': 5
        }
        
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.yaml')
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                
            if not isinstance(config_data, dict):
                return default_config
                
            yaml_config: YAMLConfig = cast(YAMLConfig, config_data)
            logging_config = yaml_config.get('logging', {})
            
            # Da wir bereits wissen, dass es ein Dict ist, brauchen wir keine weitere Prüfung
            return LogConfig(
                level=str(logging_config.get('level', default_config['level'])),
                file=str(logging_config.get('file', default_config['file'])),
                max_size=int(logging_config.get('max_size', default_config['max_size'])),
                backup_count=int(logging_config.get('backup_count', default_config['backup_count']))
            )
        except Exception as e:
            print(f"Warnung: Konnte Logging-Konfiguration nicht laden: {e}")
            return default_config

    def is_mapping_type(self, data: Any) -> TypeGuard[Mapping[str, Any]]:
        """Typ-Guard für Mapping-Typen"""
        return isinstance(data, Mapping)

    def is_sequence_type(self, data: Any) -> TypeGuard[Sequence[Any]]:
        """Typ-Guard für Sequence-Typen (außer str und bytes)"""
        return isinstance(data, Sequence) and not isinstance(data, (str, bytes))

    def _clean_process_id(self, data: T) -> T:
        """
        Entfernt process_id rekursiv aus Dictionaries und Listen.
        
        Args:
            data: Die zu bereinigenden Daten
            
        Returns:
            Die bereinigten Daten vom gleichen Typ
        """
        if self.is_mapping_type(data):
            cleaned_dict: Dict[str, Any] = {}
            for key, val in data.items():
                if key != 'process_id':
                    cleaned_dict[str(key)] = self._clean_process_id(val)
            return cast(T, cleaned_dict)
        elif self.is_sequence_type(data):
            cleaned_list: list[Any] = []
            for item in data:
                cleaned_list.append(self._clean_process_id(item))
            return cast(T, cleaned_list)
        return data

    def _initialize_handlers(self) -> None:
        """
        Initialisiert die Log-Handler (Konsole und Datei).
        Lädt die Konfiguration aus der config.yaml und erstellt die notwendigen Verzeichnisse und Dateien.
        """
        if self._shared_handlers_initialized:
            return
            
        # Lade Konfiguration direkt aus der YAML
        log_config = self._load_config()
        
        # Hole Log-Pfad und Level aus der Konfiguration
        log_file = log_config['file']
        log_level = getattr(logging, log_config['level'])
        
        # Console Handler
        self._console_handler = logging.StreamHandler(sys.stdout)
        self._console_handler.setLevel(log_level)

        class RelativePathFormatter(logging.Formatter):
            def format(self, record: LogRecord) -> str:
                # Konvertiere den absoluten Pfad in einen relativen Pfad
                if hasattr(record, 'pathname'):
                    try:
                        # Finde den tatsächlichen Caller
                        frame = sys._getframe()  # type: ignore
                        found_logging = False
                        
                        # Gehe durch den Stack bis wir den ersten Frame nach dem Logger finden
                        while frame:
                            code = frame.f_code
                            filename = code.co_filename
                            
                            # Wenn wir im logging-Modul sind, markiere das
                            if 'logging' in filename or 'logger.py' in filename:
                                found_logging = True
                            # Wenn wir das logging-Modul verlassen haben, ist dies unser Caller
                            elif found_logging:
                                try:
                                    caller_path = Path(filename)
                                    record.pathname = str(caller_path)
                                    record.funcName = code.co_name
                                    record.lineno = frame.f_lineno
                                    break
                                except Exception:
                                    pass
                            frame = frame.f_back
                        
                        # Verwende nur den Dateinamen ohne Pfad
                        record.source_path = Path(record.pathname).name
                    except (ValueError, AttributeError):
                        record.source_path = Path(record.pathname).name
                return super().format(record)

        formatter = RelativePathFormatter(
            '%(asctime)s - %(levelname)s - [%(source_path)s:%(funcName)s:%(lineno)d] - [%(processor_name)s] Process[%(process_id)s] - %(message)s'
        )
        self._console_handler.setFormatter(formatter)
        
        # File Handler für detaillierte Logs
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not log_path.exists():
            log_path.touch()
            print(f"Log-Datei wurde erstellt: {log_path}")
        
        self._detail_handler = logging.FileHandler(
            log_path,
            encoding='utf-8'
        )
        self._detail_handler.setLevel(logging.DEBUG)
        self._detail_handler.setFormatter(formatter)
        
        self._shared_handlers_initialized = True

    def get_logger(self, process_id: str, processor_name: Optional[str] = None) -> 'ProcessingLogger':
        """Get or create a logger instance for the given process_id"""
        if process_id in self._loggers:
            logger = self._loggers[process_id]
            if processor_name and processor_name != logger.processor_name:
                logger.processor_name = processor_name
            return logger
        
        # Stelle sicher, dass die Handler initialisiert sind
        if not self._shared_handlers_initialized:
            self._initialize_handlers()
        
        if self._console_handler is None or self._detail_handler is None:
            raise RuntimeError("Handler wurden nicht korrekt initialisiert")
            
        logger = ProcessingLogger(
            process_id=process_id, 
            processor_name=processor_name or "",
            console_handler=self._console_handler,
            detail_handler=self._detail_handler
        )
        self._loggers[process_id] = logger
        return logger

class ProcessingLogger:
    """
    Logger für einzelne Prozesse
    """
    def __init__(self, process_id: str, processor_name: str,
                 console_handler: Handler, detail_handler: Handler) -> None:
        if not process_id:
            raise ValueError("process_id ist ein Pflichtfeld")
        
        self.process_id: str = process_id
        self.processor_name: str = processor_name
        
        # Haupt-Logger Setup
        self.logger: Logger = logging.getLogger(f"processing_service.{process_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        
        # Add handlers if not already added
        if not self.logger.handlers:
            self.logger.addHandler(console_handler)
            self.logger.addHandler(detail_handler)
        
        self.debug("Logger initialisiert")
    
    def _is_mapping_type(self, data: Any) -> TypeGuard[Mapping[str, Any]]:
        """Typ-Guard für Mapping-Typen"""
        return isinstance(data, Mapping)

    def _is_sequence_type(self, data: Any) -> TypeGuard[Sequence[Any]]:
        """Typ-Guard für Sequence-Typen (außer str und bytes)"""
        return isinstance(data, Sequence) and not isinstance(data, (str, bytes))

    @overload
    def _clean_process_id(self, data: Dict[str, Any]) -> Dict[str, Any]: ...
    
    @overload
    def _clean_process_id(self, data: list[Any]) -> list[Any]: ...
    
    @overload
    def _clean_process_id(self, data: T) -> T: ...

    def _clean_process_id(self, data: Any) -> Any:
        """
        Entfernt process_id rekursiv aus Dictionaries und Listen.
        
        Args:
            data: Die zu bereinigenden Daten
            
        Returns:
            Die bereinigten Daten vom gleichen Typ
        """
        if self._is_mapping_type(data):
            cleaned_dict: Dict[str, Any] = {}
            for key, val in data.items():
                if key != 'process_id':
                    cleaned_dict[str(key)] = self._clean_process_id(val)
            return cleaned_dict
        elif self._is_sequence_type(data):
            cleaned_list: list[Any] = []
            for item in data:
                cleaned_list.append(self._clean_process_id(item))
            return cleaned_list
        return data
    
    def _prepare_extra(self, kwargs: Dict[str, Any]) -> ExtraDict:
        """Bereitet die Extra-Daten für das Logging vor."""
        extra: ExtraDict = {
            'process_id': self.process_id,
            'processor_name': self.processor_name,
            'kwargs': None
        }
        if kwargs:
            clean_kwargs = self._clean_process_id(kwargs)
            if clean_kwargs:  # Da wir wissen, dass es ein Dict ist
                extra['kwargs'] = json.dumps(clean_kwargs)
        return extra

    def debug(self, message: str, **kwargs: Any) -> None:
        """Debug-Level Logging mit optionalen strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra.get('kwargs', '{}')}"
        self.logger.debug(message, extra=extra)

    def info(self, message: str, **kwargs: Any) -> None:
        """Info-Level Logging mit optionalen strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra.get('kwargs', '{}')}"
        self.logger.info(message, extra=extra)

    def error(self, message: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
        """Error-Level Logging mit Exception-Details."""
        if error:
            message = f"{message}\nError: {str(error)}"
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra.get('kwargs', '{}')}"
        self.logger.error(message, extra=extra)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Warning-Level Logging mit strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        self.logger.warning(message, extra=extra)

# Globale Instanz des LoggerService
logger_service = LoggerService()

def get_logger(process_id: str, processor_name: Optional[str] = None) -> ProcessingLogger:
    """Helper function to get a logger instance"""
    return logger_service.get_logger(process_id, processor_name)