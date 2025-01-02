import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import sys
import time
from functools import wraps

class ProcessingLogger:
    _shared_handlers_initialized = False
    
    def __init__(self, log_dir: str = "logs", process_id: str = None, processor_name: str = None):
        if not process_id:
            raise ValueError("process_id ist ein Pflichtfeld")
            
        self.process_id = process_id
        self.processor_name = processor_name or ""  # Fallback wenn kein Name angegeben
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Haupt-Logger Setup mit eindeutigem Namen für jeden Prozessor
        self.logger = logging.getLogger(f"processing_service.{process_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False  # Verhindert Weiterleitung an Parent-Logger
        
        # Shared Handler Konfiguration, nur einmal erstellen
        if not ProcessingLogger._shared_handlers_initialized:
            # Console Handler
            ProcessingLogger._console_handler = logging.StreamHandler(sys.stdout)
            ProcessingLogger._console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - [%(processor_name)s] Process[%(process_id)s] - %(message)s - Args: %(kwargs)s'
            )
            ProcessingLogger._console_handler.setFormatter(formatter)
            
            # File Handler für detaillierte Logs
            ProcessingLogger._detail_handler = logging.FileHandler(
                self.log_dir / "detailed.log",
                encoding='utf-8'
            )
            ProcessingLogger._detail_handler.setLevel(logging.DEBUG)
            detail_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - [%(processor_name)s] Process[%(process_id)s] - %(message)s'
            )
            ProcessingLogger._detail_handler.setFormatter(detail_formatter)
            
            # Performance Log (JSON)
            self.perf_log_path = self.log_dir / "performance.json"
            if not self.perf_log_path.exists():
                self.perf_log_path.write_text("[]")
            
            ProcessingLogger._shared_handlers_initialized = True
        
        # Füge die Handler zum Logger hinzu
        if not self.logger.handlers:
            self.logger.addHandler(ProcessingLogger._console_handler)
            self.logger.addHandler(ProcessingLogger._detail_handler)
        
        # Hole die gemeinsamen Handler vom Root-Logger
        self.perf_log_path = self.log_dir / "performance.json"
        
        # Initialisierungs-Log
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
            'kwargs': '{}'  # Default leeres JSON wenn keine kwargs vorhanden
        }
        if kwargs:
            # Entferne process_id rekursiv aus kwargs
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

    @staticmethod
    def track_performance(operation: str):
        """Decorator für Performance-Tracking von Funktionen."""
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