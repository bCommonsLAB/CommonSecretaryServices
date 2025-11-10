"""
@fileoverview Event Models - Pydantic models for event processing and track aggregation

@description
Event data models for event processing. This file defines Pydantic models for event
processing, including track aggregation and event summarization.

Main classes:
- EventInput: Input data for event processing (Pydantic BaseModel)
- EventOutput: Output data of event processing
- EventData: Container for input/output data with tracks
- EventResponse: API response for event processing
- EventInputDict/OutputDict/DataDict: TypedDict variants for dictionary access

Features:
- Pydantic-based validation
- Serialization to dictionary (to_dict, model_dump)
- Track aggregation (list of TrackData)
- Integration with BaseResponse for standardized API responses
- TypedDict variants for flexible dictionary access

@module core.models.event

@exports
- EventInput: Pydantic BaseModel - Event input data
- EventOutput: Pydantic BaseModel - Event output data
- EventData: Pydantic BaseModel - Event data container
- EventResponse: Pydantic BaseModel - API response for event processing
- EventInputDict/OutputDict/DataDict: TypedDict - Dictionary variants

@usedIn
- src.processors.event_processor: Uses all event models
- src.api.routes.event_routes: Uses EventResponse for API responses

@dependencies
- External: pydantic - Data validation and model definitions
- Internal: src.core.models.base - BaseResponse
- Internal: src.core.models.track - TrackData
"""
from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field
from .base import BaseResponse
from .track import TrackData


class EventInput(BaseModel):
    """
    Eingabedaten für die Event-Verarbeitung.
    """
    event_name: str = Field(..., description="Name des Events")
    template: str = Field(..., description="Template für die Verarbeitung")
    target_language: str = Field(..., description="Zielsprache für die Verarbeitung")


class EventOutput(BaseModel):
    """
    Ausgabedaten für die Event-Verarbeitung.
    """
    summary: str = Field(..., description="Zusammenfassung des Events als JSON-String")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadaten des Events")
    structured_data: Dict[str, Any] = Field(default_factory=dict, description="Strukturierte Daten des Events")
    results: List[Dict[str, Any]] = Field(default_factory=list, description="Liste der verarbeiteten Ergebnisse")


class EventData(BaseModel):
    """
    Daten für ein Event.
    """
    input: EventInput = Field(..., description="Eingabedaten des Events")
    output: EventOutput = Field(..., description="Ausgabedaten des Events")
    tracks: List[TrackData] = Field(default_factory=list, description="Liste der zugehörigen Tracks")
    track_count: int = Field(..., description="Anzahl der Tracks")
    query: str = Field(default="", description="Suchanfrage")
    context: Dict[str, Any] = Field(default_factory=dict, description="Kontextinformationen")

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert das Objekt in ein Dictionary für die JSON-Serialisierung.
        
        Returns:
            Dict[str, Any]: Dictionary-Repräsentation der EventData
        """
        tracks_data: List[Dict[str, Any]] = []
        for track in self.tracks:
            if isinstance(track, dict):
                tracks_data.append(track)  # Bereits ein Dictionary
            else:
                tracks_data.append(track.to_dict())  # TrackData Objekt

        return {
            "input": self.input.model_dump(),
            "output": self.output.model_dump(),
            "tracks": tracks_data,
            "track_count": self.track_count,
            "query": self.query,
            "context": self.context
        }


class EventResponse(BaseResponse):
    """
    Response für die Event-Verarbeitung.
    """
    data: Optional[EventData] = Field(None, description="Event-Daten")


class EventInputDict(TypedDict):
    """
    Dictionary-Repräsentation der Event-Eingabedaten.
    """
    event_name: str
    template: str
    target_language: str


class EventOutputDict(TypedDict):
    """
    Dictionary-Repräsentation der Event-Ausgabedaten.
    """
    summary: str
    metadata: Dict[str, Any]
    structured_data: Dict[str, Any]
    results: List[Dict[str, Any]] 