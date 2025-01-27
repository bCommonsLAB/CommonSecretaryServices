"""
Performance tracking utility for API calls and processor operations.

This module provides centralized performance tracking functionality to measure and log
the performance of API calls and their underlying processor operations.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, TypedDict, Protocol, cast
from datetime import datetime, timedelta
import threading
from contextlib import contextmanager
import logging
from logging import Logger

from src.core.models.llm import LLMInfo as CoreLLMInfo

class LLMMetrics(Protocol):
    """Protocol für grundlegende LLM-Metriken"""
    tokens: int
    model: str

class ClientInfo(TypedDict):
    """Client-Informationen"""
    ip: Optional[str]
    user_agent: Optional[str]

class ResourceInfo(TypedDict):
    """Ressourcen-Informationen"""
    total_tokens: int
    total_cost: float
    models_used: List[str]

class ErrorInfo(TypedDict):
    """Fehler-Informationen"""
    message: str
    type: str

class ProcessorStats(TypedDict):
    """Statistiken für einen Prozessor"""
    total_duration: float
    operation_count: int
    success_count: int
    error_count: int

class OperationInfo(TypedDict, total=False):
    """Informationen über eine Operation"""
    name: str
    start_time: str
    duration: float
    processor: Optional[str]
    status: str
    error: Optional[str]
    end_time: str

class StoredLog(TypedDict):
    """Gespeicherter Log-Eintrag"""
    timestamp: str
    process_id: str
    measurements: Dict[str, Any]

class Measurements(TypedDict):
    """Performance-Messungen"""
    process_id: str
    timestamp: str
    total_duration: float
    status: str
    endpoint: Optional[str]
    client_info: ClientInfo
    operations: List[OperationInfo]
    processors: Dict[str, ProcessorStats]
    resources: ResourceInfo
    error: Optional[ErrorInfo]

class PerformanceResult(TypedDict):
    """Ergebnis eines Performance-Trackings"""
    tokens: int
    model: str

class PerformanceTracker:
    """
    Zentraler Performance-Tracker für API-Aufrufe und Prozessor-Operationen.
    
    Diese Klasse sammelt Performance-Metriken für einen gesamten API-Aufruf,
    einschließlich aller Unterprozesse und Operationen.
    
    Attributes:
        process_id (str): Eindeutige ID des API-Aufrufs
        start_time (float): Zeitstempel des Starts der Messung
        measurements (Dict): Dictionary mit allen Performance-Messungen
        _local = threading.local(): Thread-lokaler Speicher für verschachtelte Messungen
    """
    
    def __init__(self, process_id: str):
        """
        Initialisiert einen neuen Performance-Tracker.
        
        Args:
            process_id (str): Eindeutige ID des API-Aufrufs
        """
        self.process_id = process_id
        self.start_time = time.time()
        self.logger: Logger = logging.getLogger(f"performance_tracker.{process_id}")
        
        self.measurements: Measurements = {
            'process_id': process_id,
            'timestamp': datetime.now().isoformat(),
            'total_duration': 0.0,
            'status': 'running',
            'endpoint': None,
            'client_info': {
                'ip': None,
                'user_agent': None
            },
            'operations': [],
            'processors': {},
            'resources': {
                'total_tokens': 0,
                'total_cost': 0.0,
                'models_used': []
            },
            'error': None
        }
        self._local = threading.local()

    def set_endpoint_info(self, endpoint: str, ip: str, user_agent: str) -> None:
        """
        Setzt die Endpoint-Informationen für den API-Aufruf.
        
        Args:
            endpoint: Der aufgerufene API-Endpoint
            ip: IP-Adresse des Clients
            user_agent: User-Agent des Clients
        """
        self.measurements['endpoint'] = endpoint
        self.measurements['client_info']['ip'] = ip
        self.measurements['client_info']['user_agent'] = user_agent

    def add_resource_usage(self, tokens: int, cost: float, model: str) -> None:
        """
        Fügt Ressourcenverbrauch hinzu (z.B. Token und Kosten von LLM-Aufrufen).
        
        Args:
            tokens: Anzahl der verbrauchten Token
            cost: Kosten des Aufrufs
            model: Name des verwendeten Modells
        """
        resources = self.measurements['resources']
        resources['total_tokens'] += tokens
        resources['total_cost'] += cost
        resources['models_used'].append(model)

    def eval_result(self, result: Any) -> None:
        """
        Evaluiert das Ergebnis eines Prozessors und fügt die Ressourcennutzung hinzu.
        
        Args:
            result: Das Ergebnis des Prozessors (AudioProcessingResult, TranscriptionResult, etc.)
        """
        try:
            # Für AudioProcessingResult
            if hasattr(result, 'audio_result') and hasattr(result.audio_result, 'transcription') and hasattr(result.audio_result.transcription, 'requests'):
                requests = result.audio_result.transcription.requests
                total_tokens = sum(req.tokens for req in requests)
                # Verwende das erste Modell als Hauptmodell
                model = requests[0].model if requests else 'unknown'
                cost = total_tokens * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=total_tokens,
                    cost=cost,
                    model=model
                )
            # Für TransformerResponse mit LLMInfo
            elif hasattr(result, 'llm_info') and result.llm_info is not None:
                llm_info: CoreLLMInfo = result.llm_info
                total_tokens = sum(req.tokens for req in llm_info.requests)
                # Verwende das erste Modell als Hauptmodell
                model = llm_info.model
                cost = total_tokens * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=total_tokens,
                    cost=cost,
                    model=model
                )
            # Für TranslationResult/TransformationResult mit requests
            elif hasattr(result, 'requests') and result.requests is not None:
                requests = result.requests
                total_tokens = sum(req.tokens for req in requests)
                # Verwende das erste Modell als Hauptmodell
                model = requests[0].model if requests else 'unknown'
                cost = total_tokens * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=total_tokens,
                    cost=cost,
                    model=model
                )
            # Für alte Dictionary-Struktur (Abwärtskompatibilität)
            elif isinstance(result, dict) and 'tokens' in result:
                perf_result = cast(PerformanceResult, result)
                cost = float(perf_result['tokens']) * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=perf_result['tokens'],
                    cost=cost,
                    model=perf_result.get('model', 'unknown')
                )
        except Exception as e:
            self.logger.error(f"Fehler beim Evaluieren des Ergebnisses: {str(e)}")
            # Fehler nicht weiterwerfen, da dies eine optionale Operation ist

    def set_error(self, error: str, error_type: Optional[str] = None) -> None:
        """
        Setzt Fehlerinformationen für den API-Aufruf.
        
        Args:
            error: Fehlermeldung
            error_type: Typ des Fehlers
        """
        self.measurements['status'] = 'error'
        self.measurements['error'] = {
            'message': str(error),
            'type': error_type or type(error).__name__
        }

    @contextmanager
    def measure_operation(self, operation_name: str, processor_name: Optional[str] = None):
        """
        Context Manager zum Messen der Ausführungszeit einer Operation.
        
        Args:
            operation_name: Name der zu messenden Operation
            processor_name: Name des Prozessors, falls zutreffend
            
        Yields:
            None
        """
        start_time = time.time()
        operation: OperationInfo = {
            'name': operation_name,
            'start_time': datetime.now().isoformat(),
            'duration': 0.0,
            'processor': processor_name,
            'status': 'running',
            'error': None,
            'end_time': ''
        }
        self.measurements['operations'].append(operation)
        
        try:
            yield
            operation['status'] = 'success'
        except Exception as e:
            operation['status'] = 'error'
            operation['error'] = str(e)
            raise
        finally:
            duration = time.time() - start_time
            operation['duration'] = duration
            operation['end_time'] = datetime.now().isoformat()
            
            if processor_name:
                if processor_name not in self.measurements['processors']:
                    self.measurements['processors'][processor_name] = {
                        'total_duration': 0.0,
                        'operation_count': 0,
                        'success_count': 0,
                        'error_count': 0
                    }
                proc_stats = self.measurements['processors'][processor_name]
                proc_stats['total_duration'] += duration
                proc_stats['operation_count'] += 1
                if operation['status'] == 'success':
                    proc_stats['success_count'] += 1
                else:
                    proc_stats['error_count'] += 1

    def complete_tracking(self) -> Measurements:
        """
        Schließt die Performance-Messung ab und speichert die Ergebnisse.
        
        Returns:
            Die gesammelten Performance-Metriken
        """
        self.measurements['total_duration'] = time.time() - self.start_time
        if not self.measurements.get('error'):
            self.measurements['status'] = 'success'
        
        # Konvertiere set zu list für JSON-Serialisierung
        resources = self.measurements['resources']
        resources['models_used'] = resources['models_used']
        
        # Speichere die Messung in der Performance-Log-Datei
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / 'performance.json'
        try:
            logs: List[StoredLog] = []
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                    
            # Entferne alte Logs (älter als 30 Tage)
            thirty_days_ago = datetime.now() - timedelta(days=30)
            logs = [
                log for log in logs 
                if datetime.fromisoformat(log['timestamp']) > thirty_days_ago
            ]
            
            logs.append(cast(StoredLog, {
                'timestamp': self.measurements['timestamp'],
                'process_id': self.measurements['process_id'],
                'measurements': self.measurements
            }))
            
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern der Performance-Messung: {e}")
        
        return self.measurements

    def _calculate_llm_cost(self, llms: List[LLMMetrics]) -> float:
        """
        Berechnet die Kosten für LLM-Nutzung.
        
        Args:
            llms: Liste von LLM-Informationen
            
        Returns:
            Berechnete Kosten
        """
        total_tokens = sum(llm.tokens for llm in llms)
        return total_tokens * 0.0001  # Standardkosten pro Token

    def _calculate_llm_cost_from_result(self, result: Any) -> float:
        """
        Berechnet die LLM-Kosten aus einem Ergebnis.
        
        Args:
            result: Ergebnis eines LLM-Aufrufs
            
        Returns:
            Berechnete Kosten
        """
        if hasattr(result, 'requests') and result.requests is not None:
            total_tokens = sum(req.tokens for req in result.requests)
            return total_tokens * 0.0001
        elif hasattr(result, 'llm_info') and result.llm_info is not None:
            total_tokens = sum(req.tokens for req in result.llm_info.requests)
            return total_tokens * 0.0001
        elif isinstance(result, dict) and 'tokens' in result:
            perf_result = cast(PerformanceResult, result)
            cost = float(perf_result['tokens']) * 0.0001
            self.logger.info(
                "LLM-Kosten berechnet",
                extra={
                    'process_id': self.process_id,
                    'processor_name': 'cost_calculator',
                    'tokens': perf_result['tokens'],
                    'cost': cost
                }
            )
            return cost
        return 0.0

# Globaler Performance-Tracker für den aktuellen Thread
_performance_trackers = threading.local()

def get_performance_tracker(process_id: Optional[str] = None) -> Optional[PerformanceTracker]:
    """
    Gibt den Performance-Tracker für den aktuellen Thread zurück.
    
    Args:
        process_id (str, optional): Process-ID für einen neuen Tracker
        
    Returns:
        PerformanceTracker: Der aktuelle Performance-Tracker oder None
    """
    if not hasattr(_performance_trackers, 'tracker'):
        if process_id:
            _performance_trackers.tracker = PerformanceTracker(process_id)
        else:
            return None
    return _performance_trackers.tracker

def clear_performance_tracker():
    """Entfernt den Performance-Tracker für den aktuellen Thread."""
    if hasattr(_performance_trackers, 'tracker'):
        delattr(_performance_trackers, 'tracker') 