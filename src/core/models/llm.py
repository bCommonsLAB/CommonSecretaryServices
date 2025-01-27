"""
Modelle für Language Model (LLM) Interaktionen.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

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

@dataclass(frozen=True)
class LLMRequest:
    """
    Informationen über einen einzelnen LLM-Request.
    
    Attributes:
        model: Name des verwendeten Modells
        purpose: Zweck der Anfrage (z.B. 'transcription', 'translation')
        tokens: Anzahl der verwendeten Tokens
        duration: Verarbeitungsdauer in Millisekunden
        timestamp: Zeitstempel der Anfrage (ISO 8601)
    """
    model: str
    purpose: str
    tokens: int
    duration: int
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

@dataclass(frozen=True)
class LLMInfo:
    """
    Aggregierte Informationen über LLM-Nutzung.
    
    Attributes:
        model: Name des hauptsächlich verwendeten Modells
        purpose: Hauptzweck der LLM-Nutzung
        tokens: Gesamtanzahl der verwendeten Tokens
        duration: Gesamtdauer der Verarbeitung in Millisekunden
        requests: Liste aller LLM-Requests
        requests_count: Anzahl der Requests
        total_tokens: Summe aller Tokens
        total_duration: Summe aller Verarbeitungszeiten
    """
    model: str
    purpose: str
    tokens: int = 0
    duration: float = 0.0
    requests: List[LLMRequest] = field(default_factory=list)
    requests_count: int = 0
    total_tokens: int = 0
    total_duration: float = 0.0

    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.model):
            raise ValueError("model darf nicht leer sein")
        if not is_non_empty_str(self.purpose):
            raise ValueError("purpose darf nicht leer sein")
        if not is_non_negative(self.tokens):
            raise ValueError("tokens muss nicht-negativ sein")
        if not is_non_negative(self.duration):
            raise ValueError("duration muss nicht-negativ sein")
        if not is_non_negative(self.requests_count):
            raise ValueError("requests_count muss nicht-negativ sein")
        if not is_non_negative(self.total_tokens):
            raise ValueError("total_tokens muss nicht-negativ sein")
        if not is_non_negative(self.total_duration):
            raise ValueError("total_duration muss nicht-negativ sein")

    def add_request(self, request: LLMRequest) -> None:
        """
        Fügt einen neuen Request hinzu und aktualisiert die Gesamtwerte.
        
        Args:
            request: Der hinzuzufügende LLM-Request
        """
        # Da die Klasse frozen ist, müssen wir object.__setattr__ verwenden
        object.__setattr__(self, 'requests', [*self.requests, request])
        object.__setattr__(self, 'requests_count', self.requests_count + 1)
        object.__setattr__(self, 'total_tokens', self.total_tokens + request.tokens)
        object.__setattr__(self, 'total_duration', self.total_duration + request.duration)

@dataclass(frozen=True)
class TranscriptionSegment:
    """Ein Segment einer Transkription mit Zeitstempeln."""
    text: str
    segment_id: int
    title: Optional[str] = None

    def __post_init__(self):
        if not self.text.strip():
            raise ValueError("Text must not be empty")
        if self.segment_id <= 0:
            raise ValueError("Segment ID must be positive")
        if self.title is not None and not self.title.strip():
            raise ValueError("Title must not be empty if provided")

@dataclass(frozen=True)
class TranscriptionResult:
    """Ergebnis einer Transkription."""
    text: str
    detected_language: Optional[str]
    segments: List[TranscriptionSegment] = field(default_factory=list)
    llms: List[LLModel] = field(default_factory=list)

    def __post_init__(self):
        if not self.text.strip():
            raise ValueError("Text must not be empty")
        if self.detected_language is not None and len(self.detected_language) != 2:
            raise ValueError("Language code must be ISO 639-1 (2 characters)")
        
        # Validiere Segment IDs
        if self.segments:
            segment_ids = [s.segment_id for s in self.segments]
            if len(set(segment_ids)) != len(segment_ids):
                raise ValueError("Segment IDs must be unique")
            if sorted(segment_ids) != list(range(min(segment_ids), max(segment_ids) + 1)):
                raise ValueError("Segment IDs must be consecutive") 