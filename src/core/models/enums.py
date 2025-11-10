"""
@fileoverview Enums and Type Aliases - Central enum definitions and type aliases

@description
Enums and type aliases for Common Secretary Services. This file defines all central
enum classes and type aliases used throughout the application.

Defined enums:
- ProcessorType: Available processor types (PDF, VIDEO, AUDIO, etc.)
- ProcessingStatus: Status of a processing (SUCCESS, ERROR, PENDING, etc.)
- OutputFormat: Available output formats (TEXT, HTML, MARKDOWN, JSON, etc.)
- EventFormat: Format of an event (ONLINE, HYBRID, PHYSICAL)
- PublicationStatus: Status of a publication (DRAFT, PUBLISHED, ARCHIVED)

Type aliases:
- LanguageCode: ISO 639-1 language codes as Literal type

@module core.models.enums

@exports
- ProcessorType: Enum - Processor types
- ProcessingStatus: Enum - Processing status
- OutputFormat: Enum - Output formats
- EventFormat: Enum - Event formats
- PublicationStatus: Enum - Publication status
- LanguageCode: TypeAlias - Language codes

@usedIn
- src.core.models.base: Uses ProcessingStatus
- src.processors.*: All processors use ProcessorType and ProcessingStatus
- src.api.routes.*: API routes use enums for validation
- All model definitions: Use enums for typing

@dependencies
- Standard: enum - Enum definitions
- Standard: typing - Literal type for LanguageCode
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
    