"""
Datenmodelle für die Notion-Integration.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from .base import BaseResponse

@dataclass(frozen=True)
class NotionBlock:
    """
    Repräsentiert einen einzelnen Notion Block.
    """
    root_id: str
    object: str
    id: str
    parent_id: str
    type: str
    has_children: bool
    archived: bool
    in_trash: bool
    content: Optional[str] = None
    image: Optional[Dict[str, Any]] = None
    caption: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiere die Block-Struktur nach der Initialisierung."""
        if not self.root_id:
            raise ValueError("root_id muss gesetzt sein")
        if not self.type:
            raise ValueError("Block-Typ darf nicht leer sein")
        if self.type not in ["paragraph", "image", "child_page"]:
            raise ValueError(f"Ungültiger Block-Typ: {self.type}")
            
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Block in ein Dictionary."""
        return {
            "root_id": self.root_id,
            "object": self.object,
            "id": self.id,
            "parent_id": self.parent_id,
            "type": self.type,
            "has_children": self.has_children,
            "archived": self.archived,
            "in_trash": self.in_trash,
            "content": self.content,
            "image": self.image,
            "caption": self.caption
        }

@dataclass(frozen=True)
class Newsfeed:
    """
    Repräsentiert einen mehrsprachigen Newsfeed-Eintrag (DE/IT).
    """
    id: str  # parent_id des ersten Blocks als eindeutige ID
    title_DE: str
    intro_DE: str
    title_IT: str
    intro_IT: str
    image: Optional[str]
    content_DE: str
    content_IT: str

    def __post_init__(self) -> None:
        """Validiere die Newsfeed-Struktur nach der Initialisierung."""
        if not self.id:
            raise ValueError("ID muss gesetzt sein")
        if not self.title_DE or not self.title_IT:
            raise ValueError("Titel muss in beiden Sprachen vorhanden sein")
        if not self.intro_DE or not self.intro_IT:
            raise ValueError("Intro muss in beiden Sprachen vorhanden sein")
        if not self.content_DE or not self.content_IT:
            raise ValueError("Content muss in beiden Sprachen vorhanden sein")
            
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Newsfeed in ein Dictionary."""
        return {
            "id": self.id,
            "title_DE": self.title_DE,
            "intro_DE": self.intro_DE,
            "title_IT": self.title_IT,
            "intro_IT": self.intro_IT,
            "image": self.image,
            "content_DE": self.content_DE,
            "content_IT": self.content_IT
        }

@dataclass(frozen=True)
class NotionData:
    """
    Enthält die Ein- und Ausgabedaten der Notion-Verarbeitung.
    """
    input: List[NotionBlock]
    output: Newsfeed
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die NotionData in ein Dictionary."""
        return {
            "input": [block.to_dict() for block in self.input],
            "output": self.output.to_dict()
        }

@dataclass(frozen=True)
class NotionResponse(BaseResponse):
    """
    Response-Struktur für den Notion-Endpoint.
    """
    data: Optional[NotionData] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        if self.data:
            base_dict["data"] = self.data.to_dict()
        return base_dict 