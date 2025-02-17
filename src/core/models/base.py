"""
Basis-Typen und Interfaces für die Common Secretary Services.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from .enums import ProcessingStatus
from .llm import LLMInfo, LLMRequest

@dataclass
class ProcessingLogger:
    """Logger Interface für die Verarbeitung"""
    def debug(self, message: str, **kwargs: Any) -> None: ...
    def info(self, message: str, **kwargs: Any) -> None: ...
    def warning(self, message: str, **kwargs: Any) -> None: ...
    def error(self, message: str, **kwargs: Any) -> None: ...

@dataclass
class ErrorInfo:
    """Fehlerinformationen für API-Responses"""
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.code.strip():
            raise ValueError("Error code must not be empty")
        if not self.message.strip():
            raise ValueError("Error message must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Error-Info in ein Dictionary."""
        return {
            'code': self.code,
            'message': self.message,
            'details': self.details
        }

@dataclass
class RequestInfo:
    """Informationen über eine Verarbeitungsanfrage"""
    processor: str
    timestamp: str
    parameters: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.processor.strip():
            raise ValueError("Processor must not be empty")
        if not self.timestamp.strip():
            raise ValueError("Timestamp must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Request-Info in ein Dictionary."""
        return {
            'processor': self.processor,
            'timestamp': self.timestamp,
            'parameters': self.parameters
        }

@dataclass
class ProcessInfo:
    """Informationen über einen Verarbeitungsprozess"""
    id: str
    main_processor: str
    started: str
    sub_processors: List[str] = field(default_factory=list)
    completed: Optional[str] = None
    duration: Optional[float] = None
    llm_info: Optional[LLMInfo] = None

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.id.strip():
            raise ValueError("Process ID must not be empty")
        if not self.main_processor.strip():
            raise ValueError("Main processor must not be empty")
        if not self.started.strip():
            raise ValueError("Start timestamp must not be empty")
        if self.completed is not None and not self.completed.strip():
            raise ValueError("Completion timestamp must not be empty if provided")
        if self.duration is not None and self.duration < 0:
            raise ValueError("Duration must be non-negative if provided")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Process-Info in ein Dictionary."""
        return {
            'id': self.id,
            'main_processor': self.main_processor,
            'started': self.started,
            'sub_processors': self.sub_processors,
            'completed': self.completed,
            'duration': self.duration,
            'llm_info': self.llm_info.to_dict() if self.llm_info else None
        }

    def add_llm_requests(self, requests: Union[List[LLMRequest], LLMInfo]) -> None:
        """
        Fügt LLM-Requests hinzu.
        
        Args:
            requests: Liste von LLMRequests oder ein LLMInfo Objekt
        """
        # Initialisiere llm_info wenn nicht vorhanden
        if self.llm_info is None:
            object.__setattr__(self, 'llm_info', LLMInfo(
                model="multi-model",
                purpose="multi-purpose",
                requests=[]
            ))
        
        # Füge Requests hinzu
        if self.llm_info is not None:  # Für Type-Checker
            if isinstance(requests, list):
                self.llm_info.add_request(requests)
            else:
                self.llm_info.add_request(requests.requests)

@dataclass(frozen=True)
class BaseResponse:
    """Basis-Klasse für alle API-Responses"""
    request: RequestInfo
    process: ProcessInfo
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None
    data: Any = None  # Hinzugefügt für spezifische Response-Daten

    def __post_init__(self) -> None:
        """Validiert die Basis-Response."""
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        return {
            'status': self.status.value,
            'request': self.request.to_dict() if self.request else None,
            'process': self.process.to_dict() if self.process else None,
            'error': self.error.to_dict() if self.error else None,
            'data': self.data.to_dict() if hasattr(self.data, 'to_dict') else self.data
        }

    def set_completed(self) -> None:
        """Markiert den Prozess als abgeschlossen."""
        object.__setattr__(self.process, 'completed', datetime.now().isoformat())
        object.__setattr__(self, 'status', ProcessingStatus.SUCCESS)

    def set_error(self, error: ErrorInfo) -> None:
        """Setzt die Fehlerinformation."""
        object.__setattr__(self, 'error', error)
        object.__setattr__(self, 'status', ProcessingStatus.ERROR)

    def add_llm_requests(self, requests: Union[List[LLMRequest], LLMInfo]) -> None:
        """
        Fügt LLM-Requests zum Prozess hinzu.
        
        Args:
            requests: Liste von LLMRequests oder ein LLMInfo Objekt
        """
        self.process.add_llm_requests(requests) 