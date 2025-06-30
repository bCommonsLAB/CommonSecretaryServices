"""
Datenmodelle für Jobs und Batches.
Definiert die Struktur von Jobs und Batches in der MongoDB-Datenbank.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Literal
from datetime import datetime, UTC
import uuid
from enum import Enum


class JobStatus(str, Enum):
    """Status eines Jobs."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AccessVisibility(str, Enum):
    """Sichtbarkeit eines Objekts."""
    PRIVATE = "private"
    PUBLIC = "public"


@dataclass(frozen=True)
class AccessControl:
    """Zugriffssteuerung für ein Objekt."""
    visibility: AccessVisibility = AccessVisibility.PRIVATE
    read_access: List[str] = field(default_factory=list)
    write_access: List[str] = field(default_factory=list)
    admin_access: List[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Validiert die Zugriffssteuerung nach der Initialisierung."""
        # Konvertiere String-Wert zu AccessVisibility-Enum, falls nötig
        if type(self.visibility) is not AccessVisibility:
            object.__setattr__(self, "visibility", AccessVisibility(self.visibility))


@dataclass(frozen=True)
class LogEntry:
    """Ein Log-Eintrag für einen Job."""
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error", "critical"]
    message: str
    
    def __post_init__(self) -> None:
        """Validiert den Log-Eintrag nach der Initialisierung."""
        valid_levels = ("debug", "info", "warning", "error", "critical")
        if self.level not in valid_levels:
            raise ValueError(f"Level muss einer von {valid_levels} sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Log-Eintrag in ein Dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogEntry":
        """Erstellt einen Log-Eintrag aus einem Dictionary."""
        return cls(
            timestamp=data.get("timestamp", datetime.now(UTC)),
            level=data.get("level", "info"),
            message=data.get("message", "")
        )


@dataclass
class JobProgress:
    """Fortschrittsinformationen für einen Job."""
    step: str
    percent: int = 0
    message: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert den Fortschritt nach der Initialisierung."""
        if self.percent < 0 or self.percent > 100:
            raise ValueError("Prozent muss eine Ganzzahl zwischen 0 und 100 sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Fortschritt in ein Dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobProgress":
        """Erstellt einen Fortschritt aus einem Dictionary."""
        return cls(
            step=data.get("step", "unknown"),
            percent=data.get("percent", 0),
            message=data.get("message")
        )


@dataclass
class JobParameters:
    """Parameter für einen Job."""
    event: Optional[str] = None
    session: Optional[str] = None
    url: Optional[str] = None
    filename: Optional[str] = None
    track: Optional[str] = None
    day: Optional[str] = None
    starttime: Optional[str] = None
    endtime: Optional[str] = None
    speakers: List[str] = field(default_factory=list)
    video_url: Optional[str] = None
    attachments_url: Optional[str] = None
    source_language: str = "en"
    target_language: str = "de"
    use_cache: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Parameter in ein Dictionary."""
        # Alle Felder einschließen, auch mit None-Werten, damit sie in der UI angezeigt werden
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobParameters":
        """Erstellt Parameter aus einem Dictionary."""
        return cls(
            event=data.get("event"),
            session=data.get("session"),
            url=data.get("url"),
            filename=data.get("filename"),
            track=data.get("track"),
            day=data.get("day"),
            starttime=data.get("starttime"),
            endtime=data.get("endtime"),
            speakers=data.get("speakers", []),
            video_url=data.get("video_url"),
            attachments_url=data.get("attachments_url"),
            source_language=data.get("source_language", "en"),
            target_language=data.get("target_language", "de"),
            use_cache=data.get("use_cache", True)
        )


@dataclass
class JobResults:
    """Ergebnisse eines Jobs."""
    markdown_file: Optional[str] = None
    markdown_content: Optional[str] = None
    assets: List[str] = field(default_factory=list)
    web_text: Optional[str] = None
    video_transcript: Optional[str] = None
    attachments_text: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    attachments_url: Optional[str] = None
    # ZIP-Archiv Felder
    archive_data: Optional[str] = None  # Base64-kodiertes ZIP-Archiv
    archive_filename: Optional[str] = None  # Dateiname des ZIP-Archives
    # Zusätzliche Metadaten
    structured_data: Optional[Dict[str, Any]] = None
    target_dir: Optional[str] = None
    page_texts: List[str] = field(default_factory=list)
    asset_dir: Optional[str] = None  # Verzeichnis mit den Asset-Dateien
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Ergebnisse in ein Dictionary."""
        # Alle Felder einschließen, auch mit None-Werten und leeren Listen
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobResults":
        """Erstellt Ergebnisse aus einem Dictionary."""
        return cls(
            markdown_file=data.get("markdown_file"),
            markdown_content=data.get("markdown_content"),
            assets=data.get("assets", []),
            web_text=data.get("web_text"),
            video_transcript=data.get("video_transcript"),
            attachments_text=data.get("attachments_text"),
            context=data.get("context"),
            attachments_url=data.get("attachments_url"),
            archive_data=data.get("archive_data"),
            archive_filename=data.get("archive_filename"),
            structured_data=data.get("structured_data"),
            target_dir=data.get("target_dir"),
            page_texts=data.get("page_texts", []),
            asset_dir=data.get("asset_dir")
        )


@dataclass
class JobError:
    """Fehlerinformationen für einen Job."""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Fehler in ein Dictionary."""
        # Alle Felder einschließen, auch mit None-Werten
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobError":
        """Erstellt einen Fehler aus einem Dictionary."""
        return cls(
            code=data.get("code", "unknown_error"),
            message=data.get("message", "Ein unbekannter Fehler ist aufgetreten"),
            details=data.get("details")
        )


@dataclass
class Job:
    """Ein Job für die asynchrone Verarbeitung."""
    job_id: str = field(default_factory=lambda: f"job-{uuid.uuid4()}")
    job_type: str = ""
    job_name: Optional[str] = None  # Name des Jobs für die Anzeige
    status: JobStatus = JobStatus.PENDING
    parameters: JobParameters = field(default_factory=JobParameters)
    results: Optional[JobResults] = None
    error: Optional[JobError] = None
    progress: Optional[JobProgress] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None  # Timestamp für den Start der Verarbeitung
    user_id: Optional[str] = None
    access_control: AccessControl = field(default_factory=AccessControl)
    event_type: Optional[str] = None
    batch_id: Optional[str] = None
    log_entries: List[Dict[str, Any]] = field(default_factory=list)
    archived: bool = False
    
    def __post_init__(self) -> None:
        """Validiert den Job nach der Initialisierung."""
        # Konvertierung von String zu Enum, falls notwendig
        if type(self.status) is not JobStatus:
            self.status = JobStatus(self.status)
        
        # Zugriffssteuerung automatisch setzen, wenn Benutzer-ID vorhanden ist
        if self.user_id and not self.access_control.read_access:
            self.access_control = AccessControl(
                visibility=AccessVisibility.PRIVATE,
                read_access=[self.user_id],
                write_access=[self.user_id],
                admin_access=[self.user_id]
            )
        
        # Job-Name automatisch aus Parametern generieren, falls nicht angegeben
        if self.job_name is None:
            parts: List[str] = []
            if self.parameters.event:
                parts.append(self.parameters.event)
            if self.parameters.track:
                parts.append(self.parameters.track)
            if self.parameters.session:
                parts.append(self.parameters.session)
            
            if parts:
                self.job_name = " - ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Job in ein Dictionary für MongoDB."""
        job_dict: Dict[str, Any] = {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "parameters": self.parameters.to_dict(),
            "archived": self.archived
        }
        
        # Optionale Felder hinzufügen
        if self.job_name:
            job_dict["job_name"] = self.job_name
            
        if self.user_id:
            job_dict["user_id"] = self.user_id
        
        if self.access_control:
            access_dict = asdict(self.access_control)
            # Konvertiere Enum-Werte zu Strings
            access_dict["visibility"] = self.access_control.visibility.value
            job_dict["access_control"] = access_dict
        
        if self.processing_started_at:
            job_dict["processing_started_at"] = self.processing_started_at
        
        if self.completed_at:
            job_dict["completed_at"] = self.completed_at
        
        if self.progress:
            job_dict["progress"] = self.progress.to_dict()
        
        if self.log_entries:
            job_dict["log_entries"] = self.log_entries
        
        if self.results:
            job_dict["results"] = self.results.to_dict()
        
        if self.error:
            job_dict["error"] = self.error.to_dict()
        
        if self.batch_id:
            job_dict["batch_id"] = self.batch_id
        
        return job_dict
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Erstellt einen Job aus einem Dictionary aus MongoDB."""
        # Performance-Optimierung: Nur die minimal notwendigen Felder konvertieren
        # für die Anzeige in der Tabelle
        
        # Parameter konvertieren - nur wenn sie vorhanden sind und benötigt werden
        parameters = JobParameters() 
        if "parameters" in data:
            parameters = JobParameters.from_dict(data.get("parameters", {}))
        
        # Zeitstempel direkt übernehmen ohne zusätzliche Konvertierung
        created_at = data.get("created_at", datetime.now(UTC))
        updated_at = data.get("updated_at", datetime.now(UTC))
        processing_started_at = data.get("processing_started_at")
        completed_at = data.get("completed_at")
        
        # Minimale Felder für Fortschritt konvertieren (für Anzeige wichtig)
        progress = None
        if "progress" in data:
            progress_data = data["progress"]
            # Sichere Prüfung: progress_data kann None sein
            if progress_data is not None:
                # Schnellere direkte Erstellung ohne vollständige Validierung
                progress = JobProgress(
                    step=progress_data.get("step", "unknown"),
                    percent=progress_data.get("percent", 0),
                    message=progress_data.get("message")
                )
            else:
                # Fallback für None progress_data
                progress = JobProgress(
                    step="unknown",
                    percent=0,
                    message="Kein Fortschritt verfügbar"
                )
        
        # Nur Fehlermeldung extrahieren, wenn vorhanden
        error = None
        if "error" in data:
            error_data = data["error"]
            # Sichere Prüfung: error_data kann None sein
            if error_data is not None:
                error = JobError(
                    code=error_data.get("code", "unknown_error"),
                    message=error_data.get("message", "Ein unbekannter Fehler ist aufgetreten"),
                    details=error_data.get("details")
                )
            else:
                # Fallback für None error_data
                error = JobError(
                    code="unknown_error",
                    message="Fehlerdaten nicht verfügbar",
                    details=None
                )
        
        # Ergebnisse nur bei Bedarf konvertieren
        results = None
        if "results" in data:
            results = JobResults.from_dict(data["results"])
        
        # Zugriffssteuerung vereinfacht übernehmen
        access_control = AccessControl()
        
        # Minimale Log-Einträge übernehmen
        log_entries = data.get("log_entries", [])
        
        return cls(
            job_id=data.get("job_id", f"job-{uuid.uuid4()}"),
            status=JobStatus(data.get("status", "pending")),
            created_at=created_at,
            updated_at=updated_at,
            processing_started_at=processing_started_at,
            completed_at=completed_at,
            user_id=data.get("user_id"),
            access_control=access_control,
            parameters=parameters,
            progress=progress,
            log_entries=log_entries,
            results=results,
            error=error,
            batch_id=data.get("batch_id"),
            job_name=data.get("job_name"),
            archived=data.get("archived", False),
            job_type=data.get("job_type", "")
        )


@dataclass
class Batch:
    """Ein Batch von Jobs."""
    total_jobs: int
    batch_id: str = field(default_factory=lambda: f"batch-{uuid.uuid4()}")
    batch_name: Optional[str] = None
    status: JobStatus = JobStatus.PROCESSING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None
    user_id: Optional[str] = None
    access_control: AccessControl = field(default_factory=AccessControl)
    completed_jobs: int = 0
    failed_jobs: int = 0
    pending_jobs: int = 0     # Anzahl der Jobs im Status PENDING
    processing_jobs: int = 0  # Anzahl der Jobs im Status PROCESSING
    archived: bool = False
    isActive: bool = True
    
    def __post_init__(self) -> None:
        """Validiert den Batch nach der Initialisierung."""
        if type(self.status) is not JobStatus:
            self.status = JobStatus(self.status)
        
        if self.user_id and not self.access_control.read_access:
            self.access_control = AccessControl(
                visibility=AccessVisibility.PRIVATE,
                read_access=[self.user_id],
                write_access=[self.user_id],
                admin_access=[self.user_id]
            )
            
        # Batch-Name auf Batch-ID setzen, falls nicht vorhanden
        if self.batch_name is None:
            self.batch_name = self.batch_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Batch in ein Dictionary für MongoDB."""
        batch_dict = {
            "batch_id": self.batch_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_jobs": self.total_jobs,
            "completed_jobs": self.completed_jobs,
            "failed_jobs": self.failed_jobs,
            "pending_jobs": self.pending_jobs,
            "processing_jobs": self.processing_jobs,
            "archived": self.archived,
            "isActive": self.isActive
        }
        
        # Optionale Felder hinzufügen
        if self.batch_name:
            batch_dict["batch_name"] = self.batch_name
            
        if self.user_id:
            batch_dict["user_id"] = self.user_id
        
        if self.access_control:
            access_dict = asdict(self.access_control)
            # Konvertiere Enum-Werte zu Strings
            access_dict["visibility"] = self.access_control.visibility.value
            batch_dict["access_control"] = access_dict  # type: ignore
        
        if self.completed_at:
            batch_dict["completed_at"] = self.completed_at
        
        return batch_dict
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Batch":
        """Erstellt einen Batch aus einem Dictionary aus MongoDB."""
        # Stelle sicher, dass batch_id immer eine gültige String-UUID ist
        batch_id_value = data.get("batch_id")
        if batch_id_value is None:
            batch_id = f"batch-{uuid.uuid4()}"
        else:
            batch_id = str(batch_id_value)
        
        # Zugriffssteuerung konvertieren
        access_control_data = data.get("access_control", {})
        access_control = AccessControl(
            visibility=AccessVisibility(access_control_data.get("visibility", "private")),
            read_access=access_control_data.get("read_access", []),
            write_access=access_control_data.get("write_access", []),
            admin_access=access_control_data.get("admin_access", [])
        )
        
        # Hole batch_name oder setze auf None
        batch_name: Optional[str] = data.get("batch_name")
        
        return cls(
            batch_id=batch_id,
            batch_name=batch_name,
            status=JobStatus(data.get("status", "processing")),
            created_at=data.get("created_at", datetime.now(UTC)),
            updated_at=data.get("updated_at", datetime.now(UTC)),
            completed_at=data.get("completed_at"),
            user_id=data.get("user_id"),
            access_control=access_control,
            total_jobs=data.get("total_jobs", 0),
            completed_jobs=data.get("completed_jobs", 0),
            failed_jobs=data.get("failed_jobs", 0),
            pending_jobs=data.get("pending_jobs", 0),
            processing_jobs=data.get("processing_jobs", 0),
            archived=data.get("archived", False),
            isActive=data.get("isActive", True)
        ) 