"""
Story-Modell-Definitionen
-------------------------
Dieses Modul enthält die Datenmodelle für die Story-Verarbeitung.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, TypeVar, cast
from datetime import datetime


# Hilfsfunktionen für Serialisierung und Deserialisierung
def _serialize_datetime(dt: datetime) -> str:
    """Serialisiert ein datetime-Objekt zu einem ISO 8601-String."""
    return dt.isoformat()

def _deserialize_datetime(dt_str: str) -> datetime:
    """Deserialisiert einen ISO 8601-String zu einem datetime-Objekt."""
    return datetime.fromisoformat(dt_str)


@dataclass(frozen=True)
class StoryProcessorInput:
    """
    Eingabedaten für den StoryProcessor.
    
    Attributes:
        topic_id: ID des Themas, für das die Story erstellt werden soll
        event: Event, zu dem das Thema gehört
        target_group: Zielgruppe, für die die Story erstellt werden soll
        languages: Liste der Sprachen, in denen die Story erstellt werden soll
        detail_level: Detailgrad der Story (1-5, wobei 5 die detaillierteste ist)
        session_ids: Optionale Liste von Session-IDs, die für die Story verwendet werden sollen
        data_topic_text: Optionaler Text für die Filterung nach data.topic
        use_cache: Ob der Cache verwendet werden soll (Standard: false)
    """
    topic_id: str
    event: str
    target_group: str
    languages: List[str]
    detail_level: int = 3
    session_ids: Optional[List[str]] = None
    data_topic_text: Optional[str] = None
    use_cache: bool = False
    
    def __post_init__(self) -> None:
        """
        Validiert die Eingabedaten nach der Initialisierung.
        
        Raises:
            ValueError: Wenn die Eingabedaten ungültig sind
        """
        if self.detail_level < 1 or self.detail_level > 5:
            raise ValueError("detail_level muss zwischen 1 und 5 liegen")
        
        if not self.languages:
            raise ValueError("Mindestens eine Sprache muss angegeben werden")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Instanz in ein Dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryProcessorInput':
        """
        Erstellt eine Instanz aus einem Dictionary.
        
        Args:
            data: Das Quelldictionary
            
        Returns:
            Eine neue StoryProcessorInput-Instanz
        """
        return cls(
            topic_id=data.get("topic_id", ""),
            event=data.get("event", ""),
            target_group=data.get("target_group", ""),
            languages=data.get("languages", []),
            detail_level=data.get("detail_level", 3),
            session_ids=data.get("session_ids"),
            data_topic_text=data.get("data_topic_text"),
            use_cache=data.get("use_cache", True)
        )


@dataclass(frozen=True)
class StoryProcessorOutput:
    """
    Ausgabedaten des StoryProcessors.
    
    Attributes:
        topic_id: ID des Themas, für das die Story erstellt wurde
        event: Event, zu dem das Thema gehört
        target_group: Zielgruppe, für die die Story erstellt wurde
        markdown_files: Dictionary mit Pfaden zu Markdown-Dateien, nach Sprache geordnet
        markdown_contents: Dictionary mit Markdown-Inhalten, nach Sprache geordnet
        session_count: Anzahl der Sessions, die für die Story verwendet wurden
        metadata: Zusätzliche Metadaten zur Story
    """
    topic_id: str
    event: str
    target_group: str
    markdown_files: Dict[str, str]
    markdown_contents: Dict[str, str]
    session_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Instanz in ein Dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryProcessorOutput':
        """
        Erstellt eine Instanz aus einem Dictionary.
        
        Args:
            data: Das Quelldictionary
            
        Returns:
            Eine neue StoryProcessorOutput-Instanz
        """
        return cls(
            topic_id=data.get("topic_id", ""),
            event=data.get("event", ""),
            target_group=data.get("target_group", ""),
            markdown_files=data.get("markdown_files", {}),
            markdown_contents=data.get("markdown_contents", {}),
            session_count=data.get("session_count", 0),
            metadata=data.get("metadata", {})
        )


@dataclass(frozen=True)
class StoryProcessingResult:
    """
    Ergebnis der Story-Verarbeitung, das im Cache gespeichert wird.
    
    Attributes:
        topic_id: ID des Themas, für das die Story erstellt wurde
        event: Event, zu dem das Thema gehört
        target_group: Zielgruppe, für die die Story erstellt wurde
        session_ids: Liste der Session-IDs, die für die Story verwendet wurden
        markdown_files: Dictionary mit Pfaden zu Markdown-Dateien, nach Sprache geordnet
        markdown_contents: Dictionary mit Markdown-Inhalten, nach Sprache geordnet
        metadata: Zusätzliche Metadaten zur Story
        process_id: ID des Verarbeitungsprozesses
        input_data: Die Eingabedaten, die zur Erstellung der Story verwendet wurden
        created_at: Zeitpunkt der Erstellung
    """
    topic_id: str
    event: str
    target_group: str
    session_ids: List[Any]
    markdown_files: Dict[str, str]
    markdown_contents: Dict[str, str]
    metadata: Dict[str, Any]
    process_id: Optional[str] = None
    input_data: Optional[StoryProcessorInput] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def status(self) -> str:
        """Status des Ergebnisses: 'success' oder 'error'."""
        return "success" if self.markdown_contents else "error"
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Instanz in ein Dictionary."""
        result = asdict(self)
        # Datetime-Objekt serialisieren
        result["created_at"] = _serialize_datetime(self.created_at)
        # Input-Daten serialisieren, falls vorhanden
        if self.input_data:
            result["input_data"] = self.input_data.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryProcessingResult':
        """
        Erstellt eine Instanz aus einem Dictionary.
        
        Args:
            data: Das Quelldictionary
            
        Returns:
            Eine neue StoryProcessingResult-Instanz
        """
        # Datetime-String deserialisieren
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = _deserialize_datetime(created_at)
        else:
            created_at = datetime.now()
        
        # Input-Daten deserialisieren, falls vorhanden
        input_data_raw = data.get("input_data")
        input_data: Optional[StoryProcessorInput] = None
        if isinstance(input_data_raw, dict):
            input_data = StoryProcessorInput.from_dict(cast(Dict[str, Any], input_data_raw))
        
        return cls(
            topic_id=data.get("topic_id", ""),
            event=data.get("event", ""),
            target_group=data.get("target_group", ""),
            session_ids=data.get("session_ids", []),
            markdown_files=data.get("markdown_files", {}),
            markdown_contents=data.get("markdown_contents", {}),
            metadata=data.get("metadata", {}),
            process_id=data.get("process_id"),
            input_data=input_data,
            created_at=created_at
        )


@dataclass(frozen=True)
class StoryData:
    """
    Kombinierte Ein- und Ausgabedaten für die Story-Verarbeitung.
    
    Attributes:
        input: Die Eingabedaten für die Story-Verarbeitung
        output: Die Ausgabedaten der Story-Verarbeitung
    """
    input: StoryProcessorInput
    output: StoryProcessorOutput
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Instanz in ein Dictionary."""
        return {
            "input": self.input.to_dict(),
            "output": self.output.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryData':
        """
        Erstellt eine Instanz aus einem Dictionary.
        
        Args:
            data: Das Quelldictionary
            
        Returns:
            Eine neue StoryData-Instanz
        """
        input_data = data.get("input", {})
        output_data = data.get("output", {})
        
        return cls(
            input=StoryProcessorInput.from_dict(cast(Dict[str, Any], input_data)),
            output=StoryProcessorOutput.from_dict(cast(Dict[str, Any], output_data))
        )


# Typ für die API-Response mit dem generischen Datentyp T
T = TypeVar('T')

@dataclass(frozen=True)
class StoryResponse:
    """
    API-Response für die Story-Verarbeitung.
    
    Attributes:
        status: Status der Verarbeitung ('success' oder 'error')
        request: Informationen zur Anfrage
        process: Informationen zum Verarbeitungsprozess
        data: Die Verarbeitungsdaten bei erfolgreicher Verarbeitung
        error: Fehlerinformationen bei fehlgeschlagener Verarbeitung
    """
    status: str
    request: Dict[str, Any]
    process: Dict[str, Any]
    data: Optional[StoryData] = None
    error: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Instanz in ein Dictionary."""
        result = {
            "status": self.status,
            "request": self.request,
            "process": self.process
        }
        
        if self.data:
            result["data"] = self.data.to_dict()
        
        if self.error:
            result["error"] = self.error
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryResponse':
        """
        Erstellt eine Instanz aus einem Dictionary.
        
        Args:
            data: Das Quelldictionary
            
        Returns:
            Eine neue StoryResponse-Instanz
        """
        story_data_raw = data.get("data")
        story_data: Optional[StoryData] = None
        if isinstance(story_data_raw, dict):
            story_data = StoryData.from_dict(cast(Dict[str, Any], story_data_raw))
        
        return cls(
            status=data.get("status", ""),
            request=data.get("request", {}),
            process=data.get("process", {}),
            data=story_data,
            error=data.get("error")
        )


# Typ-Definitionen für die MongoDB-Dokumente
# Diese Klassen dienen nur zur Dokumentation und werden nicht instanziiert
class TopicModel:
    """
    Modell für ein Thema in der Datenbank.
    
    Dies ist eine strukturelle Beschreibung eines Themas, wie es in der 
    MongoDB-Datenbank gespeichert wird. Die tatsächlichen Dokumente werden
    als Dictionary-Instanzen gehandhabt.
    
    Attributes:
        topic_id: Eindeutige ID des Themas
        display_name: Anzeigename des Themas in verschiedenen Sprachen
        description: Beschreibung des Themas in verschiedenen Sprachen
        keywords: Liste von Schlüsselwörtern für das Thema
        primary_target_group: Primäre Zielgruppe für das Thema
        relevance_threshold: Schwellenwert für die Relevanz von Sessions
        status: Status des Themas ('active' oder 'inactive')
        template: Name des zu verwendenden Templates
        event: Event, zu dem das Thema gehört
        created_at: Zeitpunkt der Erstellung
        updated_at: Zeitpunkt der letzten Aktualisierung
    """
    topic_id: str
    display_name: Dict[str, str]  # z.B. {"de": "Nachhaltigkeit", "en": "Sustainability"}
    description: Dict[str, str]
    keywords: List[str]
    primary_target_group: str
    relevance_threshold: float
    status: str
    template: str
    event: str
    created_at: datetime
    updated_at: datetime


class TargetGroupModel:
    """
    Modell für eine Zielgruppe in der Datenbank.
    
    Dies ist eine strukturelle Beschreibung einer Zielgruppe, wie sie in der 
    MongoDB-Datenbank gespeichert wird. Die tatsächlichen Dokumente werden
    als Dictionary-Instanzen gehandhabt.
    
    Attributes:
        target_id: Eindeutige ID der Zielgruppe
        display_name: Anzeigename der Zielgruppe in verschiedenen Sprachen
        description: Beschreibung der Zielgruppe in verschiedenen Sprachen
        status: Status der Zielgruppe ('active' oder 'inactive')
        created_at: Zeitpunkt der Erstellung
        updated_at: Zeitpunkt der letzten Aktualisierung
    """
    target_id: str
    display_name: Dict[str, str]
    description: Dict[str, str]
    status: str
    created_at: datetime
    updated_at: datetime

# Typ-Aliase für TopicDict und TargetGroupDict
TopicDict = Dict[str, Any]
TargetGroupDict = Dict[str, Any]
SessionDict = Dict[str, Any] 