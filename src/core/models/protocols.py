"""
Protokolle für die Anwendung.
"""
from typing import Protocol

from .enums import ProcessingStatus

class CacheableResult(Protocol):
    """Protokoll für Cache-fähige Ergebnisse."""
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        ... 