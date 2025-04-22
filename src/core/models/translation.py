"""
Dataclass-Modell für Übersetzungsverwaltung.
Verwaltet Übersetzungen von Entitäten für die Verzeichnisstruktur.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List, ClassVar
import uuid
import datetime
from enum import Enum


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