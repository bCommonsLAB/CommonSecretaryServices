"""
@fileoverview Translation Models - Dataclasses for translation management

@description
Dataclass model for translation management. Manages translations of entities for directory
structure. This file defines dataclasses for managing translations of various entities
(tracks, sessions, etc.).

Main classes:
- Translation: Translation entry for an entity (slots=True)

Features:
- Serialization to dictionary (to_dict, asdict)
- Deserialization from dictionary (from_dict)
- Support for multiple languages per entity
- Timestamp tracking (created_at, updated_at)
- Entity type-based organization

@module core.models.translation

@exports
- Translation: Dataclass - Translation entry (slots=True)

@usedIn
- src.core.mongodb.translation_repository: Uses Translation for translation management
- Can be used for translation management

@dependencies
- Standard: dataclasses - Dataclass definitions
- Standard: datetime - Timestamps
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, Any
import datetime


@dataclass(frozen=False, slots=True)
class Translation:
    """
    Dataclass für Übersetzungseinträge.
    Speichert die Übersetzung eines einzelnen Textes in verschiedene Sprachen.
    """
    entity_type: str  # "track", "session", usw.
    entity_id: str    # Eindeutige ID oder Name des Originals
    original_text: str  # Originaltext
    original_language: str  # Sprachcode des Originals, z.B. "en"
    translations: Dict[str, str]  # Übersetzungen in verschiedene Sprachen: {"de": "übersetzter Text", ...}
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert das Objekt in ein Dictionary für MongoDB.
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Translation':
        """
        Erstellt ein Objekt aus einem Dictionary.
        """
        # Datum-Konvertierung, falls nötig
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.datetime.fromisoformat(data["updated_at"])
            
        return cls(**data) 