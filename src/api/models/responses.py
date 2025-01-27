"""
Response-Modelle für die API.
"""
from dataclasses import dataclass, asdict
from typing import Optional, Generic, TypeVar, Dict, Any

from src.core.models.base import ErrorInfo, RequestInfo, ProcessInfo

# Basis-Typen für die API-Responses
@dataclass(frozen=True)
class BaseModel:
    """Basis-Klasse für alle API-Modelle."""
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Modell in ein Dictionary."""
        return asdict(self)

T = TypeVar('T', bound=BaseModel)

@dataclass(frozen=True, slots=True)
class BaseResponse(BaseModel, Generic[T]):
    """Basis-Response für alle API-Antworten."""
    status: str
    request: RequestInfo
    process: ProcessInfo
    data: Optional[T] = None
    error: Optional[ErrorInfo] = None

    def __post_init__(self):
        """Validiert die Response."""
        if not self.status.strip():
            raise ValueError("Status must not be empty")
        if self.status not in ('success', 'error'):
            raise ValueError("Status must be either 'success' or 'error'")
        if self.status == 'success' and self.error is not None:
            raise ValueError("Error info must not be set for successful response")
        if self.status == 'error' and self.error is None:
            raise ValueError("Error info must be set for error response")

    @classmethod
    def success(cls, request: RequestInfo, process: ProcessInfo, data: Optional[T] = None) -> 'BaseResponse[T]':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            status='success',
            request=request,
            process=process,
            data=data
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error_info: ErrorInfo) -> 'BaseResponse[T]':
        """Erstellt eine Fehler-Response."""
        return cls(
            status='error',
            request=request,
            process=process,
            error=error_info
        ) 