"""
Modelle für Language Model (LLM) Interaktionen.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Union

from ..validation import (
    is_non_empty_str, is_non_negative,
    is_positive, is_valid_iso_date
)

@dataclass(frozen=True)
class LLModel:
    """
    Informationen über die Nutzung eines Language Models.
    
    Attributes:
        model: Name des verwendeten Modells (z.B. 'gpt-4')
        duration: Verarbeitungsdauer in Millisekunden
        tokens: Anzahl der verarbeiteten Tokens
        timestamp: Zeitstempel der LLM-Nutzung (ISO 8601)
    """
    model: str
    duration: float
    tokens: int
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not self.model.strip():
            raise ValueError("Model name must not be empty")
        if self.duration < 0:
            raise ValueError("Duration must be non-negative")
        if self.tokens <= 0:
            raise ValueError("Tokens must be positive")
        if not is_valid_iso_date(self.timestamp):
            raise ValueError("timestamp muss ein gültiges ISO 8601 Datum sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Model in ein Dictionary."""
        return {
            "model": self.model,
            "duration": self.duration,
            "tokens": self.tokens,
            "timestamp": self.timestamp
        }

@dataclass(frozen=True)
class LLMRequest:
    """
    Informationen über einen einzelnen LLM-Request.
    
    Attributes:
        model: Name des verwendeten Modells
        purpose: Zweck der Anfrage (z.B. 'transcription', 'translation')
        tokens: Anzahl der verwendeten Tokens
        duration: Verarbeitungsdauer in Millisekunden
        processor: Name des aufrufenden Processors
        timestamp: Zeitstempel der Anfrage (ISO 8601)
    """
    model: str
    purpose: str
    tokens: int
    duration: float
    processor: str
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.model):
            raise ValueError("model darf nicht leer sein")
        if not is_non_empty_str(self.purpose):
            raise ValueError("purpose darf nicht leer sein")
        if not is_positive(self.tokens):
            raise ValueError("tokens muss positiv sein")
        if not is_non_negative(self.duration):
            raise ValueError("duration muss nicht-negativ sein")
        if not is_valid_iso_date(self.timestamp):
            raise ValueError("timestamp muss ein gültiges ISO 8601 Datum sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Request in ein Dictionary."""
        return {
            "model": self.model,
            "purpose": self.purpose,
            "tokens": self.tokens,
            "duration": self.duration,
            "processor": self.processor,
            "timestamp": self.timestamp
        }

@dataclass(frozen=True)
class LLMInfo:
    """
    Zentrale Tracking-Klasse für LLM-Nutzung.
    Sammelt alle LLM-Requests aus verschiedenen Prozessoren.
    
    Attributes:
        requests: Liste aller LLM-Requests
    """
    requests: List[LLMRequest] = field(default_factory=list)
    
    @property
    def requests_count(self) -> int:
        """Anzahl der Requests."""
        return len(self.requests)
        
    @property
    def total_tokens(self) -> int:
        """Gesamtanzahl der Tokens."""
        return sum(r.tokens for r in self.requests)
        
    @property
    def total_duration(self) -> float:
        """Gesamtdauer in Millisekunden."""
        return sum(r.duration for r in self.requests)

    def merge(self, other: 'LLMInfo') -> 'LLMInfo':
        """
        Führt zwei LLMInfo Objekte zusammen.
        
        Args:
            other: Anderes LLMInfo Objekt
            
        Returns:
            Neues LLMInfo Objekt mit kombinierten Requests
        """
        return LLMInfo(requests=[*self.requests, *other.requests])

    def add_request(self, request: Union[LLMRequest, List[LLMRequest]]) -> 'LLMInfo':
        """
        Fügt einen oder mehrere Requests hinzu.
        
        Args:
            request: Einzelner Request oder Liste von Requests
            
        Returns:
            Neues LLMInfo Objekt mit hinzugefügten Requests
        """
        if isinstance(request, list):
            merged_requests: List[LLMRequest] = [*self.requests, *request]
        else:
            merged_requests = [*self.requests, request]
            
        return LLMInfo(requests=merged_requests)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die LLM-Info in ein Dictionary."""
        return {
            'requests': [req.to_dict() for req in self.requests],
            'requests_count': self.requests_count,
            'total_tokens': self.total_tokens,
            'total_duration': self.total_duration
        } 