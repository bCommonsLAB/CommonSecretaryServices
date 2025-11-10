"""
@fileoverview Track Models - Dataclasses for track processing and session aggregation

@description
Track-specific types and models for event track processing. This file defines all
dataclasses for track processing, including session aggregation and track summarization.

Main classes:
- TrackInput: Input data for track processing (frozen=True)
- TrackOutput: Output data of track processing
- TrackData: Container for input/output data with sessions
- TrackResponse: API response for track processing

Features:
- Validation of all fields in __post_init__
- Serialization to dictionary (to_dict)
- Session aggregation (list of SessionData)
- Integration with BaseResponse for standardized API responses

@module core.models.track

@exports
- TrackInput: Dataclass - Track input data (frozen=True)
- TrackOutput: Dataclass - Track output data
- TrackData: Dataclass - Track data container
- TrackResponse: Dataclass - API response for track processing

@usedIn
- src.processors.track_processor: Uses all track models
- src.processors.event_processor: Uses TrackData for event tracks
- src.api.routes.track_routes: Uses TrackResponse for API responses

@dependencies
- Internal: src.core.models.base - BaseResponse
- Internal: src.core.models.session - SessionData
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any

from .base import BaseResponse
from .session import SessionData

@dataclass(frozen=True)
class TrackInput:
    """
    Eingabedaten für den TrackProzessor.
    
    Attributes:
        track_name: Name des Tracks
        template: Name des Templates für die Zusammenfassung
        target_language: Zielsprache für die Zusammenfassung
    """
    track_name: str
    template: str
    target_language: str
    
    def __post_init__(self) -> None:
        """Validiert die Eingabedaten."""
        if not self.track_name:
            raise ValueError("Track-Name darf nicht leer sein")
        if not self.template:
            raise ValueError("Template darf nicht leer sein")
        if not self.target_language:
            raise ValueError("Zielsprache darf nicht leer sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Eingabedaten in ein Dictionary."""
        return {
            "track_name": self.track_name,
            "template": self.template,
            "target_language": self.target_language
        }


@dataclass(frozen=True)
class TrackOutput:
    """
    Ausgabedaten des TrackProzessors.
    
    Attributes:
        summary: Generierte Zusammenfassung
        metadata: Metadaten zur Zusammenfassung
        structured_data: Strukturierte Daten aus der Zusammenfassung
    """
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    structured_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Ausgabedaten in ein Dictionary."""
        return {
            "summary": self.summary,
            "metadata": self.metadata,
            "structured_data": self.structured_data
        }


@dataclass(frozen=True)
class TrackData:
    """
    Container für Ein- und Ausgabedaten des TrackProzessors.
    
    Attributes:
        input: Eingabedaten
        output: Ausgabedaten
        sessions: Liste der Session-Daten
        session_count: Anzahl der Sessions
        query: Der an das LLM gesendete Text
        context: Der an das LLM gesendete Kontext
    """
    input: TrackInput
    output: TrackOutput
    sessions: List[SessionData]
    session_count: int = 0
    query: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Daten in ein Dictionary."""
        # Behandle input: entweder TrackInput-Objekt oder Dictionary
        if isinstance(self.input, dict):
            input_dict = self.input
        else:
            input_dict = self.input.to_dict()
            
        # Behandle output: entweder TrackOutput-Objekt oder Dictionary
        if isinstance(self.output, dict):
            output_dict = self.output
        else:
            output_dict = self.output.to_dict()
            
        # Behandle sessions: Liste von SessionData-Objekten oder Dictionaries
        sessions_list: List[Dict[str, Any]] = []
        for session in self.sessions:
            if isinstance(session, dict):
                sessions_list.append(session)
            else:
                sessions_list.append(session.to_dict())
        
        return {
            "input": input_dict,
            "output": output_dict,
            "sessions": sessions_list,
            "session_count": self.session_count,
            "query": self.query,
            "context": self.context
        }


@dataclass(frozen=True)
class TrackResponse(BaseResponse):
    """
    API-Response für den TrackProzessor.
    
    Attributes:
        data: Track-spezifische Daten
    """
    data: TrackData
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        return base_dict 