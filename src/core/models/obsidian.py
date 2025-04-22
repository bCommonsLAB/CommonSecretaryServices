from dataclasses import dataclass, field
from typing import List, Optional, Dict, Literal, Any
from datetime import datetime
import uuid

from src.core.models.base import BaseResponse

@dataclass(frozen=True)
class ObsidianExportConfig:
    """Konfiguration für den Obsidian-Export"""
    source_dir: str
    target_dir: str
    event_name: str
    languages: List[str] = field(default_factory=lambda: ["de", "en"])
    export_mode: Literal["copy", "regenerate", "hybrid"] = "copy"
    preserve_changes: bool = True
    force_overwrite: bool = False
    include_assets: bool = True
    file_extensions: List[str] = field(default_factory=lambda: [".md", ".jpg", ".jpeg", ".png", ".pdf"])


@dataclass
class SessionInfo:
    """Informationen zu einer Session"""
    id: str
    name: str
    track: str
    path: str
    languages: List[str] = field(default_factory=list)
    markdown_files: Dict[str, str] = field(default_factory=dict)  # Sprache -> Dateipfad
    assets: List[str] = field(default_factory=list)
    modified_dates: Dict[str, datetime] = field(default_factory=dict)  # Dateipfad -> letzte Änderung


@dataclass
class TrackInfo:
    """Informationen zu einem Track"""
    id: str
    name: str
    path: str
    summary_files: Dict[str, str] = field(default_factory=dict)  # Sprache -> Dateipfad
    sessions: List[SessionInfo] = field(default_factory=list)


@dataclass
class EventInfo:
    """Informationen zu einem Event"""
    id: str
    name: str
    path: str
    tracks: List[TrackInfo] = field(default_factory=list)
    summary_files: Dict[str, str] = field(default_factory=dict)  # Sprache -> Dateipfad


@dataclass
class ExportMapping:
    """Mapping zwischen Quell- und Zielstruktur"""
    source_path: str
    target_path: str
    type: Literal["session", "track", "event", "asset"]
    language: Optional[str] = None
    session_id: Optional[str] = None
    track_id: Optional[str] = None
    event_id: Optional[str] = None
    original_content: Optional[str] = None  # Für Diff-Funktionalität
    
    
@dataclass
class ExportProgress:
    """Fortschritt des Exports"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    total_files: int = 0
    processed_files: int = 0
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error: Optional[str] = None
    
    @property
    def progress_percentage(self) -> float:
        """Berechnet den Fortschritt in Prozent"""
        if self.total_files == 0:
            return 0.0
        return (self.processed_files / self.total_files) * 100
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Berechnet die Dauer in Sekunden"""
        if not self.start_time:
            return None
        
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()


@dataclass
class ObsidianExportRequest:
    """Request für den Obsidian-Export"""
    source_dir: str
    target_dir: str
    event_name: str
    languages: List[str] = field(default_factory=lambda: ["de", "en"])
    export_mode: Literal["copy", "regenerate", "hybrid"] = "copy"
    preserve_changes: bool = True
    force_overwrite: bool = False
    include_assets: bool = True
    
    def to_config(self) -> ObsidianExportConfig:
        """Konvertiert den Request in eine Konfiguration"""
        return ObsidianExportConfig(
            source_dir=self.source_dir,
            target_dir=self.target_dir,
            event_name=self.event_name,
            languages=self.languages,
            export_mode=self.export_mode,
            preserve_changes=self.preserve_changes,
            force_overwrite=self.force_overwrite,
            include_assets=self.include_assets
        )


@dataclass(frozen=True)
class ObsidianExportResponse(BaseResponse):
    """Response für den Obsidian-Export"""
    # Keine zusätzlichen Felder nötig, BaseResponse bietet alles Notwendige
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        return super().to_dict()

# ... existing code ... 