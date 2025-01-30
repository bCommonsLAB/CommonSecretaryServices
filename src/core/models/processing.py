"""Processing-bezogene Datenmodelle (Legacy Version).

DEPRECATED: Diese Implementierung wird durch src/core/models/processing_steps.py ersetzt.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime
from enum import Enum

class ProcessingStatus(Enum):
    """Status eines Verarbeitungsschritts."""
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"

@dataclass
class ProcessingStep:
    """Ein einzelner Verarbeitungsschritt (Legacy Version).
    
    DEPRECATED: Diese Klasse wird durch die neue Implementierung in processing_steps.py ersetzt.
    """
    name: str
    status: ProcessingStatus = field(default=ProcessingStatus.PENDING)
    started_at: Optional[datetime] = field(default=None)
    completed_at: Optional[datetime] = field(default=None)
    duration_ms: Optional[float] = field(default=None)
    error: Optional[Dict[str, str]] = field(default=None) 
