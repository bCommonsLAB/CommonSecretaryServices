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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import sys
import os
import yaml

class LoggerService:
    """
    Zentraler Logger-Service für die Anwendung.
    Verwaltet die Logger-Instanzen und Handler für verschiedene Prozesse.
    Stellt sicher, dass die Log-Datei nur einmal initialisiert wird.
    """
    _instance = None
    _shared_handlers_initialized = False
    _loggers = {}
    _console_handler = None
    _detail_handler = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggerService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialisiert den LoggerService"""
        if not self._shared_handlers_initialized:
            self._initialize_handlers()
            
    @classmethod
    def reset(cls):
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
    
    def _load_config(self):
        """Lädt die Logging-Konfiguration aus config.yaml"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.yaml')
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return config.get('logging', {})
        except Exception as e:
            print(f"Warnung: Konnte Logging-Konfiguration nicht laden: {e}")
            return {
                'level': 'INFO',
                'file': 'logs/detailed.log',
                'max_size': 10485760,
                'backup_count': 5
            }

    def _initialize_handlers(self):
        """
        Initialisiert die Log-Handler (Konsole und Datei).
        Lädt die Konfiguration aus der config.yaml und erstellt die notwendigen Verzeichnisse und Dateien.
        """
        if self._shared_handlers_initialized:
            return
            
        # Lade Konfiguration direkt aus der YAML
        log_config = self._load_config()
        
        # Hole Log-Pfad und Level aus der Konfiguration
        log_file = log_config.get('file', 'logs/detailed.log')
        log_level = getattr(logging, log_config.get('level', 'INFO'))
        
        # Console Handler
        self._console_handler = logging.StreamHandler(sys.stdout)
        self._console_handler.setLevel(log_level)

        class RelativePathFormatter(logging.Formatter):
            def format(self, record):
                # Konvertiere den absoluten Pfad in einen relativen Pfad
                if hasattr(record, 'pathname'):
                    try:
                        # Konvertiere zu relativem Pfad
                        workspace_root = Path(__file__).parent.parent.parent
                        
                        # Finde den tatsächlichen Caller
                        frame = sys._getframe()
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

    def get_logger(self, process_id: str, processor_name: str = None) -> 'ProcessingLogger':
        """Get or create a logger instance for the given process_id"""
        if process_id in self._loggers:
            logger = self._loggers[process_id]
            if processor_name and processor_name != logger.processor_name:
                logger.processor_name = processor_name
            return logger
        
        # Stelle sicher, dass die Handler initialisiert sind
        if not self._shared_handlers_initialized:
            self._initialize_handlers()
        
        logger = ProcessingLogger(process_id=process_id, 
                                processor_name=processor_name,
                                console_handler=self._console_handler,
                                detail_handler=self._detail_handler)
        self._loggers[process_id] = logger
        return logger

class ProcessingLogger:
    """
    Logger für einzelne Prozesse
    """
    def __init__(self, process_id: str, processor_name: str = None,
                 console_handler=None, detail_handler=None):
        if not process_id:
            raise ValueError("process_id ist ein Pflichtfeld")
        
        self.process_id = process_id
        self.processor_name = processor_name or ""
        
        # Haupt-Logger Setup
        self.logger = logging.getLogger(f"processing_service.{process_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        
        # Add handlers if not already added
        if not self.logger.handlers:
            self.logger.addHandler(console_handler)
            self.logger.addHandler(detail_handler)
        
        self.debug("Logger initialisiert")
    
    def _clean_process_id(self, data: Any) -> Any:
        """Entfernt process_id rekursiv aus Dictionaries und Listen."""
        if isinstance(data, dict):
            return {k: self._clean_process_id(v) for k, v in data.items() if k != 'process_id'}
        elif isinstance(data, list):
            return [self._clean_process_id(item) for item in data]
        return data

    def _prepare_extra(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Bereitet die Extra-Daten für das Logging vor."""
        extra = {
            'process_id': self.process_id,
            'processor_name': self.processor_name
        }
        if kwargs:
            clean_kwargs = self._clean_process_id(kwargs)
            if clean_kwargs:
                extra['kwargs'] = json.dumps(clean_kwargs)
        return extra

    def debug(self, message: str, **kwargs):
        """Debug-Level Logging mit optionalen strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra.get('kwargs', '{}')}"
        self.logger.debug(message, extra=extra)

    def info(self, message: str, **kwargs):
        """Info-Level Logging mit optionalen strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra.get('kwargs', '{}')}"
        self.logger.info(message, extra=extra)

    def error(self, message: str, error: Optional[Exception] = None, **kwargs):
        """Error-Level Logging mit Exception-Details."""
        if error:
            message = f"{message}\nError: {str(error)}"
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra.get('kwargs', '{}')}"
        self.logger.error(message, extra=extra)

    def warning(self, message: str, **kwargs):
        """Warning-Level Logging mit strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        self.logger.warning(message, extra=extra)

# Globale Instanz des LoggerService
logger_service = LoggerService()

def get_logger(process_id: str = None, processor_name: str = None) -> ProcessingLogger:
    """Helper function to get a logger instance"""
    return logger_service.get_logger(process_id, processor_name)