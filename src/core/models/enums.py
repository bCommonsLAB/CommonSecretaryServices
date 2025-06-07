"""
Enums und Type-Aliases für die Common Secretary Services.
"""
from enum import Enum
from typing import Literal

# Typ-Alias für ISO 639-1 Sprachcodes
LanguageCode = Literal[
    "en", "de", "fr", "es", "it", "ja", "zh", "ko", "ru", "pt",
    "tr", "pl", "ar", "nl", "hi", "sv", "id", "vi", "th", "he"
]

class EventFormat(str, Enum):
    """Format einer Veranstaltung."""
    ONLINE = "online"
    HYBRID = "hybrid"
    PHYSICAL = "physical"

class PublicationStatus(str, Enum):
    """Status einer Publikation."""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class ProcessorType(str, Enum):
    """Verfügbare Processor-Typen"""
    PDF = "pdf"
    VIDEO = "video"
    AUDIO = "audio"
    IMAGEOCR = "imageocr"
    METADATA = "metadata"
    TRANSFORMER = "transformer"
    EVENT = "event"
    SESSION = "session"
    YOUTUBE = "youtube"

class ProcessingStatus(str, Enum):
    """
    Status der Verarbeitung.
    """
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"
    PENDING = "pending"
    RUNNING = "running"
    CANCELLED = "cancelled"

class OutputFormat(str, Enum):
    """Verfügbare Ausgabeformate"""
    TEXT = "text"
    HTML = "html"
    MARKDOWN = "markdown"
    JSON = "json"
    XML = "xml" 
    FILENAME = "filename"
    