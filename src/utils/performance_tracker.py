"""
Performance tracking utility for API calls and processor operations.

This module provides centralized performance tracking functionality to measure and log
the performance of API calls and their underlying processor operations.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import threading
from contextlib import contextmanager

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
        self.measurements: Dict[str, Any] = {
            'process_id': process_id,
            'timestamp': datetime.now().isoformat(),
            'total_duration': 0,
            'status': 'running',
            'endpoint': None,  # Wird von der API gesetzt
            'client_info': {
                'ip': None,  # Wird von der API gesetzt
                'user_agent': None  # Wird von der API gesetzt
            },
            'operations': [],
            'processors': {},
            'resources': {
                'total_tokens': 0,
                'total_cost': 0.0,
                'models_used': set()
            },
            'error': None
        }
        self._local = threading.local()

    def set_endpoint_info(self, endpoint: str, ip: str, user_agent: str):
        """
        Setzt die Endpoint-Informationen für den API-Aufruf.
        
        Args:
            endpoint (str): Der aufgerufene API-Endpoint
            ip (str): IP-Adresse des Clients
            user_agent (str): User-Agent des Clients
        """
        self.measurements['endpoint'] = endpoint
        self.measurements['client_info']['ip'] = ip
        self.measurements['client_info']['user_agent'] = user_agent

    def add_resource_usage(self, tokens: int, cost: float, model: str):
        """
        Fügt Ressourcenverbrauch hinzu (z.B. Token und Kosten von LLM-Aufrufen).
        
        Args:
            tokens (int): Anzahl der verbrauchten Token
            cost (float): Kosten des Aufrufs
            model (str): Name des verwendeten Modells
        """
        self.measurements['resources']['total_tokens'] += tokens
        self.measurements['resources']['total_cost'] += cost
        self.measurements['resources']['models_used'].add(model)

    def eval_result(self, result: Any) -> None:
        """
        Evaluiert das Ergebnis eines Prozessors und fügt die Ressourcennutzung hinzu.
        
        Args:
            result: Das Ergebnis des Prozessors (AudioProcessingResult, TranscriptionResult, etc.)
        """
        try:
            # Für AudioProcessingResult
            if hasattr(result, 'audio_result') and hasattr(result.audio_result, 'transcription') and hasattr(result.audio_result.transcription, 'llms'):
                llms = result.audio_result.transcription.llms
                total_tokens = sum(llm.tokens for llm in llms)
                # Verwende das erste Modell als Hauptmodell
                model = llms[0].model if llms else 'unknown'
                cost = total_tokens * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=total_tokens,
                    cost=cost,
                    model=model
                )
            if hasattr(result, 'transcription') and hasattr(result.transcription, 'llms'):
                llms = result.transcription.llms
                total_tokens = sum(llm.tokens for llm in llms)
                # Verwende das erste Modell als Hauptmodell
                model = llms[0].model if llms else 'unknown'
                cost = total_tokens * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=total_tokens,
                    cost=cost,
                    model=model
                )
            # Für TranscriptionResult/TranslationResult
            elif hasattr(result, 'llms'):
                llms = result.llms
                total_tokens = sum(llm.tokens for llm in llms)
                model = llms[0].model if llms else 'unknown'
                cost = total_tokens * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=total_tokens,
                    cost=cost,
                    model=model
                )
            # Für alte Dictionary-Struktur (Abwärtskompatibilität)
            elif isinstance(result, dict) and 'tokens' in result:
                cost = result['tokens'] * 0.0001  # Standardkosten pro Token
                self.add_resource_usage(
                    tokens=result['tokens'],
                    cost=cost,
                    model=result.get('model', 'unknown')
                )
        except Exception as e:
            self.logger.error(f"Fehler beim Evaluieren des Ergebnisses: {str(e)}")
            # Fehler nicht weiterwerfen, da dies eine optionale Operation ist

    def set_error(self, error: str, error_type: str = None):
        """
        Setzt Fehlerinformationen für den API-Aufruf.
        
        Args:
            error (str): Fehlermeldung
            error_type (str, optional): Typ des Fehlers
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
            operation_name (str): Name der zu messenden Operation
            processor_name (str, optional): Name des Prozessors, falls zutreffend
            
        Yields:
            None
        
        Example:
            ```python
            with performance_tracker.measure_operation('text_extraction', 'PDFProcessor'):
                # Code der Operation
                extracted_text = pdf.extract_text()
            ```
        """
        start_time = time.time()
        operation = {
            'name': operation_name,
            'start_time': datetime.now().isoformat(),
            'duration': 0,
            'processor': processor_name,
            'status': 'running'
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
                        'total_duration': 0,
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

    def complete_tracking(self):
        """
        Schließt die Performance-Messung ab und speichert die Ergebnisse.
        
        Returns:
            Dict: Die gesammelten Performance-Metriken
        """
        self.measurements['total_duration'] = time.time() - self.start_time
        if not self.measurements.get('error'):
            self.measurements['status'] = 'success'
        
        # Konvertiere set zu list für JSON-Serialisierung
        self.measurements['resources']['models_used'] = list(self.measurements['resources']['models_used'])
        
        # Speichere die Messung in der Performance-Log-Datei
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / 'performance.json'
        try:
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            else:
                logs = []
                
            # Entferne alte Logs (älter als 30 Tage)
            thirty_days_ago = datetime.now() - timedelta(days=30)
            logs = [log for log in logs if datetime.fromisoformat(log['timestamp']) > thirty_days_ago]
            
            logs.append(self.measurements)
            
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2)
                
        except Exception as e:
            print(f"Fehler beim Speichern der Performance-Messung: {e}")
        
        return self.measurements

    def _calculate_llm_cost(self, llms: List[Any]) -> float:
        """Berechnet die Kosten für LLM-Nutzung."""
        total_tokens = sum(llm.tokens for llm in llms)
        return total_tokens * 0.0001  # Standardkosten pro Token

    def _calculate_llm_cost_from_result(self, result: Any) -> float:
        """Berechnet die LLM-Kosten aus einem Ergebnis."""
        if hasattr(result, 'llms'):
            total_tokens = sum(llm.tokens for llm in result.llms)
            return total_tokens * 0.0001
        elif hasattr(result, 'process') and hasattr(result.process, 'llm_info'):
            total_tokens = sum(llm.tokens for llm in result.process.llm_info.requests)
            return total_tokens * 0.0001
        elif isinstance(result, dict) and 'tokens' in result:
            cost = result['tokens'] * 0.0001  # Standardkosten pro Token
            self.logger.info("LLM-Kosten berechnet",
                tokens=result['tokens'],
                cost=cost)
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