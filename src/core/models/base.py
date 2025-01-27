"""
Basis-Typen und Interfaces für die Common Secretary Services.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime
from .enums import ProcessingStatus

@dataclass
class ProcessingLogger:
    """Logger Interface für die Verarbeitung"""
    def debug(self, message: str, **kwargs: Any) -> None: ...
    def info(self, message: str, **kwargs: Any) -> None: ...
    def warning(self, message: str, **kwargs: Any) -> None: ...
    def error(self, message: str, **kwargs: Any) -> None: ...

@dataclass
class ResourceCalculator:
    """Interface für Resource-Berechnungen"""
    def calculate_cost(self, tokens: int, model: str) -> float: ...
    def track_usage(self, tokens: int, model: str, duration: float) -> None: ...

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

@dataclass
class ProcessInfo:
    """Informationen über einen Verarbeitungsprozess"""
    id: str
    main_processor: str
    started: str
    sub_processors: List[str] = field(default_factory=list)
    completed: Optional[str] = None
    duration: Optional[float] = None
    llm_info: Optional[Dict[str, Any]] = None

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

@dataclass(frozen=True)
class BaseResponse:
    """Basis-Klasse für alle API-Responses"""
    request: RequestInfo
    process: ProcessInfo
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None

    def set_completed(self) -> None:
        """Markiert den Prozess als abgeschlossen."""
        object.__setattr__(self.process, 'completed', datetime.now().isoformat())
        object.__setattr__(self, 'status', ProcessingStatus.SUCCESS)

    def set_error(self, error: ErrorInfo) -> None:
        """Setzt die Fehlerinformation."""
        object.__setattr__(self, 'error', error)
        object.__setattr__(self, 'status', ProcessingStatus.ERROR) 