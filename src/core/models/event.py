"""
Datenmodelle für den Event-Processor.
Verarbeitet und speichert Event-Informationen mit zugehörigen Medien.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base import (
    BaseResponse
)

@dataclass(frozen=True)
class EventInput:
    """
    Eingabedaten für den Event-Processor.
    
    Pflichtfelder:
        event: Name der Veranstaltung (z.B. "FOSDEM 2025")
        session: Name der Session (z.B. "Welcome to FOSDEM 2025")
        url: URL zur Event-Seite
        filename: Zieldateiname für die Markdown-Datei
        track: Track/Kategorie der Session

    Optionale Felder:
        day: Veranstaltungstag (z.B. "2025-02-01")
        starttime: Startzeit der Session (z.B. "09:00")
        endtime: Endzeit der Session (z.B. "10:00")
        speakers: Liste der Vortragenden
        video_url: URL zum Video
        attachments_url: URL zu Anhängen
    """
    # Pflichtfelder
    event: str
    session: str
    url: str
    filename: str
    track: str
    
    # Optionale Felder
    day: Optional[str] = None
    starttime: Optional[str] = None
    endtime: Optional[str] = None
    speakers: List[str] = field(default_factory=list)
    video_url: Optional[str] = None
    attachments_url: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Eingabedaten."""
        # Validierung der Pflichtfelder
        if not self.event.strip():
            raise ValueError("Event-Name darf nicht leer sein")
        if not self.session.strip():
            raise ValueError("Session-Name darf nicht leer sein")
        if not self.url.strip():
            raise ValueError("Event-URL darf nicht leer sein")
        if not self.filename.strip():
            raise ValueError("Dateiname darf nicht leer sein")
        if not self.track.strip():
            raise ValueError("Track darf nicht leer sein")

        # Validierung der optionalen Felder nur wenn sie gesetzt sind
        if self.day:
            try:
                datetime.strptime(self.day, "%Y-%m-%d")
            except ValueError:
                raise ValueError("Tag muss im Format YYYY-MM-DD sein")

        if self.starttime and self.endtime:
            for time_str in [self.starttime, self.endtime]:
                try:
                    datetime.strptime(time_str, "%H:%M")
                except ValueError:
                    raise ValueError("Zeit muss im Format HH:MM sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Eingabedaten in ein Dictionary."""
        return {
            "event": self.event,
            "session": self.session,
            "url": self.url,
            "filename": self.filename,
            "track": self.track,
            "day": self.day,
            "starttime": self.starttime,
            "endtime": self.endtime,
            "speakers": self.speakers,
            "video_url": self.video_url,
            "attachments_url": self.attachments_url
        }

@dataclass(frozen=True)
class EventOutput:
    """
    Ausgabedaten des Event-Processors.
    
    Attributes:
        markdown_file: Pfad zur generierten Markdown-Datei
        markdown_content: Der generierte Markdown-Inhalt
        video_file: Optional, Pfad zur heruntergeladenen Videodatei
        attachments: Liste der heruntergeladenen Anhänge
        metadata: Zusätzliche Metadaten zum Event
    """
    markdown_file: str
    markdown_content: str
    video_file: Optional[str] = None
    attachments: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Ausgabedaten in ein Dictionary."""
        return {
            "markdown_file": self.markdown_file,
            "markdown_content": self.markdown_content,
            "video_file": self.video_file,
            "attachments": self.attachments,
            "metadata": self.metadata
        }

@dataclass(frozen=True)
class EventData:
    """
    Container für Ein- und Ausgabedaten des Event-Processors.
    
    Attributes:
        input: Eingabedaten
        output: Ausgabedaten
    """
    input: EventInput
    output: EventOutput

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Event-Daten in ein Dictionary."""
        return {
            "input": self.input.to_dict(),
            "output": self.output.to_dict()
        }

@dataclass(frozen=True)
class EventResponse(BaseResponse):
    """
    API-Response für den Event-Processor.
    
    Attributes:
        data: Event-spezifische Daten
    """
    data: EventData

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict["data"] = self.data.to_dict() if self.data else None
        return base_dict 