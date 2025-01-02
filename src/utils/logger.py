"""
Logger implementation for the processing service.
"""
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import sys
import time
from functools import wraps
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
    
    @staticmethod
    def track_performance(operation: str):
        """
        Decorator für Performance-Tracking von Funktionen.
        
        Args:
            operation (str): Name der Operation die getrackt werden soll
            
        Returns:
            Decorator-Funktion die die Performance misst und loggt
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Hole die Instanz des Processors (erstes Argument der Methode)
                processor_instance = args[0]
                logger = processor_instance.logger
                start_time = time.time()
                
                try:
                    # Führe die eigentliche Funktion aus
                    result = await func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    # Basis-Details für alle Operationen
                    details = {
                        "success": True,
                        "function": func.__name__
                    }
                    
                    # Füge spezifische Details hinzu
                    if isinstance(result, dict):
                        # Entferne process_id aus dem Result für die Details
                        result_clean = {k: v for k, v in result.items() if k != 'process_id'}
                        details.update(result_clean)
                    
                    # Logge Performance
                    logger.log_performance(operation, duration, details)
                    return result
                    
                except Exception as e:
                    duration = time.time() - start_time
                    logger.log_performance(operation, duration, {
                        "success": False,
                        "error": str(e),
                        "function": func.__name__
                    })
                    raise
                
            return wrapper
        return decorator
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggerService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._shared_handlers_initialized:
            self._initialize_handlers()
    
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
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - [%(processor_name)s] Process[%(process_id)s] - %(message)s - Args: %(kwargs)s'
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
        self._detail_handler.setLevel(log_level)
        detail_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - [%(processor_name)s] Process[%(process_id)s] - %(message)s'
        )
        self._detail_handler.setFormatter(detail_formatter)
        
        # Performance Log (JSON)
        perf_log_path = log_path.parent / "performance.json"
        if not perf_log_path.exists():
            perf_log_path.write_text("[]")
        
        self._shared_handlers_initialized = True
    
    def get_logger(self, process_id: str, processor_name: str = None) -> 'ProcessingLogger':
        """Get or create a logger instance for the given process_id"""
        if process_id in self._loggers:
            logger = self._loggers[process_id]
            if processor_name and processor_name != logger.processor_name:
                logger.processor_name = processor_name
            return logger
        
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
        self.log_dir = Path("logs")
        
        # Haupt-Logger Setup
        self.logger = logging.getLogger(f"processing_service.{process_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        
        # Add handlers if not already added
        if not self.logger.handlers:
            self.logger.addHandler(console_handler)
            self.logger.addHandler(detail_handler)
        
        self.perf_log_path = self.log_dir / "performance.json"
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
            'processor_name': self.processor_name,
            'kwargs': '{}'
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
            message = f"{message} - Args: {extra['kwargs']}"
        self.logger.debug(message, extra=extra)

    def info(self, message: str, **kwargs):
        """Info-Level Logging mit optionalen strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        if kwargs:  # Nur wenn kwargs vorhanden sind
            message = f"{message} - Args: {extra['kwargs']}"
        self.logger.info(message, extra=extra)

    def error(self, message: str, error: Optional[Exception] = None, **kwargs):
        """Error-Level Logging mit Exception-Details."""
        if error:
            message = f"{message}\nError: {str(error)}"
        extra = self._prepare_extra(kwargs)
        self.logger.error(message, extra=extra)

    def warning(self, message: str, **kwargs):
        """Warning-Level Logging mit strukturierten Daten."""
        extra = self._prepare_extra(kwargs)
        self.logger.warning(message, extra=extra)

    def log_performance(self, operation: str, duration: float, details: Dict[str, Any]):
        """Loggt Performance-Daten in JSON-Format."""
        # Entferne process_id rekursiv aus den Details
        clean_details = self._clean_process_id(details)
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "duration_seconds": duration,
            "processor": operation.split('_')[0].capitalize(),
            "process_id": self.process_id,
            "details": clean_details
        }
        
        try:
            if not self.perf_log_path.exists() or self.perf_log_path.stat().st_size == 0:
                self.perf_log_path.write_text("[]")
            
            try:
                logs = json.loads(self.perf_log_path.read_text())
            except json.JSONDecodeError:
                self.logger.warning("Ungültige performance.json gefunden, erstelle neue")
                logs = []
            
            logs.append(entry)
            
            with self.perf_log_path.open('w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Fehler beim Schreiben der Performance-Logs: {str(e)}")

# Globale Instanz des LoggerService
logger_service = LoggerService()

def get_logger(process_id: str, processor_name: str = None) -> ProcessingLogger:
    """Helper function to get a logger instance"""
    return logger_service.get_logger(process_id, processor_name)

# Export the track_performance decorator for easier access
track_performance = LoggerService.track_performance