"""
@fileoverview Protocol Definitions - Type protocols for structural subtyping

@description
Protocols for the application. This file defines Protocol classes used for structural
subtyping (duck typing with type checking).

Protocols allow defining types that must have certain attributes or methods without
requiring explicit inheritance.

Defined protocols:
- CacheableResult: Protocol for cacheable results with status property

@module core.models.protocols

@exports
- CacheableResult: Protocol - Protocol for cacheable results

@usedIn
- src.processors.cacheable_processor: Uses CacheableResult for typing
- Cache system: Uses CacheableResult for generic cache operations

@dependencies
- Standard: typing - Protocol definitions
- Internal: src.core.models.enums - ProcessingStatus
"""
from typing import Protocol

from .enums import ProcessingStatus

class CacheableResult(Protocol):
    """Protokoll für Cache-fähige Ergebnisse."""
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        ... 