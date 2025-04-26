"""
Event-Datenmodelle für die Verarbeitung von Events.
"""
from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel
from .base import BaseResponse
from .track import TrackData


class EventInput(BaseModel):
    """
    Eingabedaten für die Event-Verarbeitung.
    """
    event_name: str
    template: str
    target_language: str


class EventOutput(BaseModel):
    """
    Ausgabedaten für die Event-Verarbeitung.
    """
    summary: str
    metadata: Dict[str, Any]
    structured_data: Dict[str, Any]


class EventData(BaseModel):
    """
    Daten für ein Event.
    """
    input: EventInput
    output: EventOutput
    tracks: List[TrackData]
    track_count: int
    query: str = ""
    context: Dict[str, Any] = {}

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
    data: Optional[EventData] = None


class EventInputDict(TypedDict, total=False):
    """
    Dictionary-Repräsentation der Event-Eingabedaten.
    """
    event_name: str
    template: str
    target_language: str


class EventOutputDict(TypedDict, total=False):
    """
    Dictionary-Repräsentation der Event-Ausgabedaten.
    """
    summary: str
    metadata: Dict[str, Any]
    structured_data: Dict[str, Any] 