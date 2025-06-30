"""
Datenmodelle für den Session-Processor.
Verarbeitet und speichert Session-Informationen mit zugehörigen Medien.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime

from .base import (
    BaseResponse
)

@dataclass(frozen=True)
class SessionInput:
    """
    Eingabedaten für den Session-Processor.
    
    Pflichtfelder:
        event: Name der Veranstaltung (z.B. "FOSDEM 2025")
        session: Name der Session (z.B. "Welcome to FOSDEM 2025")
        url: URL zur Session-Seite
        filename: Zieldateiname für die Markdown-Datei
        track: Track/Kategorie der Session

    Optionale Felder:
        day: Veranstaltungstag (z.B. "2025-02-01")
        starttime: Startzeit der Session (z.B. "09:00")
        endtime: Endzeit der Session (z.B. "10:00")
        speakers: Liste der Vortragenden
        video_url: URL zum Video
        attachments_url: URL zu Anhängen
        source_language: Quellsprache (Standardmäßig Englisch)
        target_language: Zielsprache (Standardmäßig Deutsch)
        target: Zielgruppe der Session
        template: Name des Templates für die Markdown-Generierung (Standardmäßig "Session")
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
    source_language: str = "en"  # Standardmäßig Englisch
    target_language: str = "de"  # Standardmäßig Deutsch
    target: Optional[str] = None
    template: str = "Session"  # Standardmäßig "Session" Template

    def __post_init__(self) -> None:
        """Validiert die Eingabedaten."""
        # Validierung der Pflichtfelder
        if not self.event.strip():
            raise ValueError("Event-Name darf nicht leer sein")
        if not self.session.strip():
            raise ValueError("Session-Name darf nicht leer sein")
        if not self.url.strip():
            raise ValueError("Session-URL darf nicht leer sein")
        if not self.filename.strip():
            raise ValueError("Dateiname darf nicht leer sein")
        if not self.track.strip():
            raise ValueError("Track darf nicht leer sein")

        # Validierung der optionalen Felder nur wenn sie gesetzt sind
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
            "attachments_url": self.attachments_url,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "target": self.target,
            "template": self.template
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionInput':
        """Erstellt eine SessionInput-Instanz aus einem Dictionary."""
        return cls(
            event=data.get("event", ""),
            session=data.get("session", ""),
            url=data.get("url", ""),
            filename=data.get("filename", ""),
            track=data.get("track", ""),
            day=data.get("day"),
            starttime=data.get("starttime"),
            endtime=data.get("endtime"),
            speakers=data.get("speakers", []),
            video_url=data.get("video_url"),
            attachments_url=data.get("attachments_url"),
            source_language=data.get("source_language", "en"),
            target_language=data.get("target_language", "de"),
            target=data.get("target"),
            template=data.get("template", "Session")
        )

@dataclass(frozen=True)
class SessionOutput:
    """
    Ausgabedaten des Session-Processors.
    
    Attributes:
        target_dir: Zielverzeichnis für die generierten Dateien
        markdown_file: Pfad zur generierten Markdown-Datei
        markdown_content: Der generierte Markdown-Inhalt
        video_file: Optional, Pfad zur heruntergeladenen Videodatei
        attachments: Liste der heruntergeladenen Anhänge
        metadata: Zusätzliche Metadaten zur Session
        archive_data: Optional, Base64-kodiertes ZIP-Archiv mit Markdown und Bildern
        archive_filename: Optional, Dateiname für das ZIP-Archiv
    """
    web_text: str
    video_transcript: str
    input_data: SessionInput
    target_dir: str
    markdown_file: str
    markdown_content: str
    video_file: Optional[str] = None
    attachments_url: Optional[str] = None
    attachments: List[str] = field(default_factory=list)
    page_texts: List[str] = field(default_factory=list)
    structured_data: Dict[str, Any] = field(default_factory=dict)
    archive_data: Optional[str] = None
    archive_filename: Optional[str] = None
    asset_dir: Optional[str] = None  # Verzeichnis mit den Asset-Dateien

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Ausgabedaten in ein Dictionary."""
        return {
            "web_text": self.web_text,
            "video_transcript": self.video_transcript,
            "input_data": self.input_data.to_dict(),
            "target_dir": self.target_dir,
            "markdown_file": self.markdown_file,
            "markdown_content": self.markdown_content,
            "video_file": self.video_file,
            "attachments_url": self.attachments_url,
            "attachments": self.attachments,
            "page_texts": self.page_texts,
            "structured_data": self.structured_data,
            "archive_data": self.archive_data,
            "archive_filename": self.archive_filename,
            "asset_dir": self.asset_dir
        }

@dataclass(frozen=True)
class SessionData:
    """
    Container für Ein- und Ausgabedaten des Session-Processors.
    
    Attributes:
        input: Eingabedaten
        output: Ausgabedaten
    """
    input: SessionInput
    output: SessionOutput

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Session-Daten in ein Dictionary."""
        return {
            "input": self.input.to_dict(),
            "output": self.output.to_dict()
        }

@dataclass(frozen=True)
class SessionResponse(BaseResponse):
    """
    API-Response für den Session-Processor.
    
    Attributes:
        data: Session-spezifische Daten
    """
    data: SessionData

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict["data"] = self.data.to_dict() if self.data else None
        return base_dict

@dataclass(frozen=True)
class BatchSessionInput:
    """
    Eingabedaten für die Batch-Verarbeitung von Sessions.
    
    Attributes:
        sessions: Liste von Session-Eingabedaten
    """
    sessions: List[Dict[str, Any]]

    def __post_init__(self) -> None:
        """Validiert die Batch-Eingabedaten."""
        if not self.sessions:
            raise ValueError("Sessions list must not be empty")

@dataclass(frozen=True)
class BatchSessionOutput:
    """
    Ausgabedaten der Batch-Session-Verarbeitung.
    
    Attributes:
        results: Liste der Session-Verarbeitungsergebnisse
        summary: Zusammenfassung der Verarbeitung
    """
    results: List[SessionOutput]
    summary: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialisiert die Summary mit Basis-Statistiken."""
        # Aktualisiere die Summary
        object.__setattr__(self, 'summary', {
            **self.summary,
            'total_sessions': len(self.results),
            'processed_at': datetime.now().isoformat()
        })

@dataclass(frozen=True)
class BatchSessionData:
    """
    Container für Ein- und Ausgabedaten der Batch-Session-Verarbeitung.
    
    Attributes:
        input: Batch-Eingabedaten
        output: Batch-Ausgabedaten
    """
    input: BatchSessionInput
    output: BatchSessionOutput

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Batch-Daten in ein Dictionary."""
        return {
            "input": {"sessions": self.input.sessions},
            "output": {
                "results": [result.to_dict() for result in self.output.results],
                "summary": self.output.summary
            }
        }

@dataclass(frozen=True)
class BatchSessionResponse(BaseResponse):
    """
    API-Response für die Batch-Session-Verarbeitung.
    
    Attributes:
        data: Batch-Session-spezifische Daten
    """
    data: Optional[BatchSessionData] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict["data"] = self.data.to_dict() if self.data else None
        return base_dict

@dataclass(frozen=True)
class WebhookConfig:
    """
    Konfiguration für Webhook-Callbacks nach der Session-Verarbeitung.
    
    Attributes:
        url: Die URL, an die der Webhook-Callback gesendet wird
        headers: Optionale HTTP-Header für den Webhook-Request
        include_markdown: Ob der Markdown-Inhalt im Callback enthalten sein soll
        include_metadata: Ob die Metadaten im Callback enthalten sein soll
        session_id: Eine eindeutige ID für die Session (wird vom Aufrufer bereitgestellt)
    """
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    include_markdown: bool = True
    include_metadata: bool = True
    session_id: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert die Webhook-Konfiguration."""
        if not self.url.strip():
            raise ValueError("Webhook URL darf nicht leer sein")
        
        # Stelle sicher, dass die URL mit http oder https beginnt
        if not (self.url.startswith("http://") or self.url.startswith("https://")):
            raise ValueError("Webhook URL muss mit http:// oder https:// beginnen")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Webhook-Konfiguration in ein Dictionary."""
        return {
            "url": self.url,
            "headers": self.headers,
            "include_markdown": self.include_markdown,
            "include_metadata": self.include_metadata,
            "session_id": self.session_id
        }

@dataclass(frozen=True)
class AsyncSessionInput(SessionInput):
    """
    Erweiterte Eingabedaten für die asynchrone Session-Verarbeitung.
    
    Attributes:
        webhook: Konfiguration für den Webhook-Callback nach der Verarbeitung
        use_cache: Ob die Ergebnisse zwischengespeichert werden sollen
    """
    webhook: Optional[WebhookConfig] = None
    use_cache: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die asynchronen Eingabedaten in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict["webhook"] = self.webhook.to_dict() if self.webhook else None
        base_dict["use_cache"] = self.use_cache
        return base_dict

@dataclass(frozen=True)
class AsyncBatchSessionInput(BatchSessionInput):
    """
    Erweiterte Eingabedaten für die asynchrone Batch-Session-Verarbeitung.
    
    Attributes:
        webhook: Konfiguration für den Webhook-Callback nach der Verarbeitung
    """
    webhook: Optional[WebhookConfig] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die asynchronen Batch-Eingabedaten in ein Dictionary."""
        return {
            "sessions": self.sessions,
            "webhook": self.webhook.to_dict() if self.webhook else None
        } 