"""
@fileoverview Processor Registry - Registry for generic job handlers

@description
Processor registry for generic job handlers. This module provides a registry system
that maps job_type strings to asynchronous handler functions. Handlers are registered
at module import time and can be retrieved by job_type.

Main functionality:
- Register handlers for specific job types
- Retrieve handlers by job_type
- List available job types
- Type-safe handler function signatures

Handler signature:
    handler(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> Awaitable[None]

Features:
- Centralized handler registration
- Type-safe handler function signatures
- Read-only access to registered handlers
- Default handler fallback (session)

@module core.processing.registry

@exports
- HandlerType: TypeAlias - Type alias for handler function signature
- register(): None - Register a handler for a job_type
- get_handler(): Optional[HandlerType] - Get handler for a job_type
- available_job_types(): Dict[str, HandlerType] - Get all registered job types

@usedIn
- src.core.mongodb.secretary_worker_manager: Uses registry to route jobs to handlers
- Handler modules: Register themselves via register() function

@dependencies
- Internal: src.core.models.job_models - Job model
- Internal: src.core.resource_tracking - ResourceCalculator
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


