"""
Registry für generische Job-Handler.

Mappt `job_type` auf asynchrone Handlerfunktionen mit Signatur:
    handler(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> Awaitable[None]
"""

from typing import Awaitable, Callable, Dict, Optional, Any

from src.core.models.job_models import Job
from src.core.resource_tracking import ResourceCalculator


HandlerType = Callable[[Job, Any, ResourceCalculator], Awaitable[None]]


_REGISTRY: Dict[str, HandlerType] = {}


def register(job_type: str, handler: HandlerType) -> None:
    """Registriert einen Handler für einen job_type."""
    _REGISTRY[job_type] = handler


def get_handler(job_type: Optional[str]) -> Optional[HandlerType]:
    """Gibt den Handler für einen job_type zurück (oder None)."""
    if not job_type:
        return _REGISTRY.get("session")
    return _REGISTRY.get(job_type)


def available_job_types() -> Dict[str, HandlerType]:
    """Liefert die registrierten job_types (readonly Kopie)."""
    return dict(_REGISTRY)


