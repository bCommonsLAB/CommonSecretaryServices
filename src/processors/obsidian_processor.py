"""
Obsidian Export Prozessor

Dieses Modul stellt Funktionalität bereit, um Event-Daten in ein optimiertes Format
für Obsidian zu exportieren. Es nutzt die MongoDB für Struktur- und Metadaten-Informationen
und unterstützt verschiedene Export-Modi und Sprachkonfigurationen.
"""
import os
import shutil
import hashlib
import logging
import re
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Set, Literal

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from src.core.models import (
    ObsidianExportConfig,
    EventInfo,
    TrackInfo,
    SessionInfo,
    ExportMapping,
    ExportProgress,
    ObsidianExportResponse,
    ErrorInfo,
    ProcessInfo,
)
from src.core.config import Config
from src.core.resource_tracking import ResourceCalculator
from src.utils.processor_cache import ProcessorCache, CacheableResult
from .cacheable_processor import CacheableProcessor

logger = logging.getLogger(__name__)


class ObsidianProcessingResult(CacheableResult):
    """
    Ergebnisstruktur für die Obsidian-Verarbeitung.
    Wird für Caching verwendet.
    """
    
    def __init__(
        self,
        source_dir: str,
        target_dir: str,
        event_name: str,
        languages: List[str],
        export_mode: str,
        progress: ExportProgress,
        mappings: List[ExportMapping],
        event_info: Optional[EventInfo] = None,
        process_id: Optional[str] = None,
        status: Literal["success", "error"] = "success"
    ):
        """Initialisiert das ObsidianProcessingResult"""
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.event_name = event_name
        self.languages = languages
        self.export_mode = export_mode
        self.progress = progress
        self.mappings = mappings
        self.event_info = event_info
        self.process_id = process_id
        self.status = status
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "source_dir": self.source_dir,
            "target_dir": self.target_dir,
            "event_name": self.event_name,
            "languages": self.languages,
            "export_mode": self.export_mode,
            "progress": self.progress.to_dict(),
            "mappings": [m.to_dict() for m in self.mappings],
            "event_info": self.event_info.to_dict() if self.event_info else None,
            "process_id": self.process_id,
            "status": self.status
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ObsidianProcessingResult':
        """Erstellt ein ObsidianProcessingResult aus einem Dictionary."""
        # Extrahiere Basisdaten mit Standardwerten für den Fall, dass etwas fehlt
        source_dir = str(data.get("source_dir", ""))
        target_dir = str(data.get("target_dir", ""))
        event_name = str(data.get("event_name", ""))
        languages = list(data.get("languages", []))
        export_mode = str(data.get("export_mode", "copy"))
        
        # Progress-Daten extrahieren
        progress_data = data.get("progress", {})
        progress = ExportProgress()
        
        # Setze Fortschrittsattribute
        if isinstance(progress_data, dict):
            progress.id = str(progress_data.get("id", ""))
            progress.status = str(progress_data.get("status", ""))
            progress.progress_percentage = float(progress_data.get("progress_percentage", 0.0))
            progress.processed_files = int(progress_data.get("processed_files", 0))
            progress.total_files = int(progress_data.get("total_files", 0))
            progress.error = str(progress_data.get("error", "")) if progress_data.get("error") else None
            progress.duration_seconds = float(progress_data.get("duration_seconds", 0.0))
            
            # Zeitstempel verarbeiten
            start_time_str = progress_data.get("start_time")
            if start_time_str:
                try:
                    progress.start_time = datetime.fromisoformat(str(start_time_str))
                except ValueError:
                    progress.start_time = None
            
            end_time_str = progress_data.get("end_time")
            if end_time_str:
                try:
                    progress.end_time = datetime.fromisoformat(str(end_time_str))
                except ValueError:
                    progress.end_time = None
        
        # Mapping-Daten extrahieren
        mappings_data = data.get("mappings", [])
        mappings: List[ExportMapping] = []
        
        for mapping_dict in mappings_data:
            if isinstance(mapping_dict, dict):
                mapping = ExportMapping(
                    source_path=str(mapping_dict.get("source_path", "")),
                    target_path=str(mapping_dict.get("target_path", "")),
                    type=str(mapping_dict.get("type", "")),
                    language=str(mapping_dict.get("language", "")) if mapping_dict.get("language") else None,
                    session_id=str(mapping_dict.get("session_id", "")) if mapping_dict.get("session_id") else None,
                    track_id=str(mapping_dict.get("track_id", "")) if mapping_dict.get("track_id") else None,
                    event_id=str(mapping_dict.get("event_id", "")) if mapping_dict.get("event_id") else None
                )
                mappings.append(mapping)
        
        # EventInfo rekonstruieren, wenn vorhanden
        event_info = None
        event_info_dict = data.get("event_info")
        if event_info_dict and isinstance(event_info_dict, dict):
            # Implementierung einer vereinfachten EventInfo-Rekonstruktion
            # (detaillierte Implementierung würde hier folgen)
            event_info = EventInfo(
                id=str(event_info_dict.get("id", "")),
                name=str(event_info_dict.get("name", "")),
                path=str(event_info_dict.get("path", "")),
                tracks=[],  # Vereinfacht
                summary_files={}  # Vereinfacht
            )
        
        process_id = str(data.get("process_id", "")) if data.get("process_id") else None
        
        status = str(data.get("status", "success"))
        
        return cls(
            source_dir=source_dir,
            target_dir=target_dir,
            event_name=event_name,
            languages=languages,
            export_mode=export_mode,
            progress=progress,
            mappings=mappings,
            event_info=event_info,
            process_id=process_id,
            status=status
        )


class ObsidianProcessor(CacheableProcessor[ObsidianProcessingResult]):
    """
    Prozessor für den Export von Event-Daten nach Obsidian.
    
    Diese Klasse nutzt MongoDB-Daten für die Struktur- und Metadaten-Informationen
    und exportiert die Daten in ein für Obsidian optimiertes Format.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "obsidian_cache"
    
    def __init__(self, 
                 resource_calculator: ResourceCalculator, 
                 config: Optional[ObsidianExportConfig] = None, 
                 process_id: Optional[str] = None, 
                 parent_process_info: Optional[ProcessInfo] = None) -> None:
        """
        Initialisiert den ObsidianProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            config: Optional, Konfiguration für den Export
            process_id: Optional, die Process-ID vom API-Layer
            parent_process_info: Optional, ProcessInfo vom übergeordneten Prozessor
        """
        # Basis-Klassen-Initialisierung
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        try:
            # Konfiguration
            self.config = config
            self.progress = ExportProgress()
            self.event_info: Optional[EventInfo] = None
            self.mappings: List[ExportMapping] = []
            
            # MongoDB-Verbindung initialisieren
            self._init_mongodb()
            
            # Cache initialisieren
            self.cache = ProcessorCache[ObsidianProcessingResult](str(self.cache_collection_name))
            
            # Basis-Verzeichnis für Sessions
            app_config = Config()
            self.base_dir = Path(app_config.get('sessions', {}).get('base_dir', './sessions'))
            self.base_dir.mkdir(parents=True, exist_ok=True)
            
            self.logger.info("Obsidian Processor initialisiert")
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Initialisierung des Obsidian Processors: {str(e)}")
            raise
    
    def _init_mongodb(self) -> None:
        """
        Initialisiert die MongoDB-Verbindung.
        """
        # MongoDB-Konfiguration laden
        app_config = Config()
        mongodb_config = app_config.get('mongodb', {})
        
        # MongoDB-Verbindung herstellen
        mongo_uri = mongodb_config.get('uri', 'mongodb://localhost:27017')
        db_name = mongodb_config.get('database', 'common-secretary-service')
        
        # Eindeutige Namen für MongoDB-Instanzen verwenden, um Konflikte zu vermeiden
        self._mongo_client: MongoClient[Dict[str, Any]] = MongoClient(mongo_uri)
        self._mongo_db: Database[Dict[str, Any]] = self._mongo_client[db_name]
        self._event_jobs: Collection[Dict[str, Any]] = self._mongo_db.event_jobs
        
        self.logger.debug("MongoDB-Verbindung initialisiert",
                        uri=mongo_uri,
                        database=db_name,
                        collection=self._event_jobs.name)
    
    @property
    def session_jobs(self) -> Collection[Dict[str, Any]]:
        """MongoDB Collection für Session Jobs (alias für event_jobs)."""
        return self._event_jobs
    
    @property
    def event_jobs(self) -> Collection[Dict[str, Any]]:
        """MongoDB Collection für Event Jobs."""
        return self._event_jobs
    
    def _generate_cache_key(
        self,
        event_name: str,
        export_mode: str,
        languages: List[str]
    ) -> str:
        """
        Generiert einen Cache-Schlüssel für den Export.
        
        Args:
            event_name: Name des Events
            export_mode: Exportmodus (copy, regenerate, hybrid)
            languages: Liste der zu exportierenden Sprachen
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        base_key = ProcessorCache.generate_simple_key(event_name)
        param_str = f"{export_mode}_{'-'.join(sorted(languages))}"
        return hashlib.sha256(f"{base_key}_{param_str}".encode()).hexdigest()
    
    def _check_cache(
        self,
        cache_key: str
    ) -> Optional[Tuple[ObsidianProcessingResult, Dict[str, Any]]]:
        """
        Prüft, ob ein Cache-Eintrag für den Export existiert.
        
        Args:
            cache_key: Der Cache-Schlüssel
            
        Returns:
            Optional[Tuple[ObsidianProcessingResult, Dict[str, Any]]]: 
                Das geladene Ergebnis und Metadaten oder None
        """
        # Prüfe Cache
        return self.cache.load_cache_with_key(
            cache_key=cache_key,
            result_class=ObsidianProcessingResult
        )
    
    def _save_to_cache(
        self,
        cache_key: str,
        result: ObsidianProcessingResult
    ) -> None:
        """
        Speichert ein Exportergebnis im Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            result: Das zu speichernde Ergebnis
        """
        try:
            # Verwende die save_to_cache-Methode der Basisklasse CacheableProcessor
            self.save_to_cache(cache_key=cache_key, result=result)
            
            # Erfolgreichen Cache-Speichervorgang protokollieren
            self.logger.info("Obsidian-Exportergebnis im Cache gespeichert", 
                           cache_key=cache_key,
                           event_name=result.event_name)
                           
        except Exception as e:
            # Fehler beim Cache-Speichervorgang protokollieren, aber Hauptprozess nicht unterbrechen
            self.logger.error(f"Fehler beim Speichern des Ergebnisses im Cache: {str(e)}",
                            error=e,
                            traceback=traceback.format_exc())
            # Wir werfen die Exception nicht weiter, damit der Hauptprozess weiterläuft,
            # auch wenn der Cache-Speichervorgang fehlschlägt
            
    def serialize_for_cache(self, result: ObsidianProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das ObsidianProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das ObsidianProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "processed_at": datetime.now().isoformat(),
            "event_name": result.event_name,
            "export_mode": result.export_mode,
            "languages": result.languages,
            "file_count": result.progress.total_files if result.progress else 0,
            "status": result.status,
            "processed_files": result.progress.processed_files if result.progress else 0,
            "duration_seconds": result.progress.duration_seconds if result.progress else 0
        }
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> ObsidianProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein ObsidianProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            ObsidianProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        return ObsidianProcessingResult.from_dict(result_data)
    
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die Obsidian-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Indizes für häufige Suchfelder
            index_fields = [
                ("event_name", 1),
                ("export_mode", 1),
                ("status", 1),
                ("processed_at", 1),
                ("languages", 1)
            ]
            
            # Indizes erstellen, wenn sie noch nicht existieren
            for field, direction in index_fields:
                index_name = f"{field}_{direction}"
                if index_name not in index_info:
                    collection.create_index([(field, direction)])
                    self.logger.debug(f"{field}-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")
            # Fehler nicht weiterwerfen, da die Indizes nicht kritisch sind
    
    async def _load_event_structure_from_db(self, event_name: str) -> EventInfo:
        """
        Lädt die Event-Struktur aus der MongoDB.
        
        Args:
            event_name: Name des Events
            
        Returns:
            EventInfo: Die Event-Struktur
        """
        # Finde alle Sessions für das Event
        self.logger.info(f"Lade Sessions für Event: {event_name}")
        sessions = list(self.session_jobs.find(
            {"parameters.event": event_name, "status": "completed"}
        ).sort("completed_at", -1))
        
        if not sessions:
            raise ValueError(f"Keine Sessions für Event '{event_name}' gefunden")
        
        self.logger.info(f"Gefunden: {len(sessions)} Sessions für Event '{event_name}'")
        
        # Event-Struktur erstellen
        event_info = EventInfo(
            id=event_name.lower().replace(" ", "-"),
            name=event_name,
            path=str(self.base_dir / event_name),  # Basisverzeichnis
            tracks=[],
            summary_files={}
        )
        
        # Tracks identifizieren (eindeutige Track-Namen)
        track_names: Set[str] = set()
        for doc in sessions:
            track_name = doc.get("parameters", {}).get("track", "")
            if track_name:
                track_names.add(track_name)
        
        # Track-Strukturen erstellen
        for track_name in track_names:
            track_sessions = [s for s in sessions if s.get("parameters", {}).get("track") == track_name]
            
            # Track-Info erstellen
            track_info = await self._create_track_info_from_db(track_name, track_sessions)
            event_info.tracks.append(track_info)
        
        return event_info
    
    async def _create_track_info_from_db(self, track_name: str, track_sessions: List[Dict[str, Any]]) -> TrackInfo:
        """
        Erstellt TrackInfo aus Datenbank-Dokumenten.
        
        Args:
            track_name: Name des Tracks
            track_sessions: Liste der Session-Dokumente für diesen Track
            
        Returns:
            TrackInfo: Die Track-Informationen
        """
        # Track-Pfad ermitteln
        track_id = track_name.lower().replace(" ", "-")
        event_name = track_sessions[0].get("parameters", {}).get("event", "Unknown") if track_sessions else "Unknown"
        track_path = str(self.base_dir / event_name / track_name)
        
        # Track-Info erstellen
        track_info = TrackInfo(
            id=track_id,
            name=track_name,
            path=track_path,
            sessions=[],
            summary_files={}
        )
        
        # Track-Summary-Dateien finden
        track_dir = Path(track_path)
        if track_dir.exists():
            summary_files = list(track_dir.glob("*-summary*.md"))
            for summary_file in summary_files:
                # Sprache aus Dateiname extrahieren oder Standardsprache verwenden
                lang_match = re.search(r"_([a-z]{2})\.md$", summary_file.name)
                lang = lang_match.group(1) if lang_match else "en"
                
                track_info.summary_files[lang] = str(summary_file)
        
        # Sessions verarbeiten
        for session_doc in track_sessions:
            # Session-Info erstellen
            session_info = await self._create_session_info_from_db(session_doc)
            
            # Nur Sessions mit Markdown-Dateien hinzufügen
            if session_info.languages:
                track_info.sessions.append(session_info)
        
        return track_info
    
    async def _create_session_info_from_db(self, session_doc: Dict[str, Any]) -> SessionInfo:
        """
        Erstellt SessionInfo aus einem Datenbank-Dokument.
        
        Args:
            session_doc: Das Session-Dokument aus der Datenbank
            
        Returns:
            SessionInfo: Die Session-Informationen
        """
        # Parameter und Ergebnisse extrahieren
        parameters = session_doc.get("parameters", {})
        results = session_doc.get("results", {})
        
        # Session-Pfad und Name
        session_name = parameters.get("session", "")
        track_name = parameters.get("track", "")
        event_name = parameters.get("event", "")
        
        # Wenn keine Pfade in den Ergebnissen gefunden werden, verwende Standardpfade
        session_path = results.get("target_dir", "")
        if not session_path:
            session_path = str(self.base_dir / event_name / track_name / session_name)
        
        # Session-ID
        session_id = session_name.lower().replace(" ", "-")
        
        # Session-Info erstellen
        session_info = SessionInfo(
            id=session_id,
            name=session_name,
            track=track_name,
            path=session_path,
            languages=[],
            markdown_files={},
            assets=[],
            modified_dates={}
        )
        
        # Markdown-Dateien aus den Ergebnissen extrahieren
        markdown_file = results.get("markdown_file", "")
        if markdown_file:
            # Pfad zum Markdown-File
            md_path = Path(markdown_file)
            
            # Sprache aus Dateiname extrahieren
            lang_match = re.search(r"_([a-z]{2})\.md$", md_path.name)
            if lang_match:
                lang = lang_match.group(1)
                session_info.languages.append(lang)
                session_info.markdown_files[lang] = markdown_file
                
                # Änderungsdatum speichern
                if md_path.exists():
                    mod_time = datetime.fromtimestamp(os.path.getmtime(md_path))
                    session_info.modified_dates[markdown_file] = mod_time
        
        # Asset-Dateien finden
        assets_path = Path(session_path) / "assets"
        if assets_path.exists() and assets_path.is_dir():
            for asset_file in assets_path.iterdir():
                if asset_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".pdf"]:
                    session_info.assets.append(str(asset_file))
        
        return session_info
    
    async def _execute_copy_mode(self) -> None:
        """
        Führt den Export im Copy-Modus durch.
        Dies verwendet die vorhandene MongoDB-Struktur und kopiert die Dateien in die Zielstruktur.
        """
        # 1. Erstelle Mappings
        await self._create_mappings()
        
        # 2. Führe Export durch
        await self._perform_export()
    
    async def _execute_regenerate_mode(self) -> None:
        """
        Führt den Export im Regenerate-Modus durch.
        Dies liest Daten aus der Datenbank und erzeugt eine neue Struktur.
        """
        # Diese Implementierung würde die Datenbank verwenden
        # Wird in einer späteren Version implementiert
        raise NotImplementedError("Regenerate-Modus ist noch nicht implementiert")
    
    async def _execute_hybrid_mode(self) -> None:
        """
        Führt den Export im Hybrid-Modus durch.
        Dies kombiniert die beiden anderen Modi.
        """
        # Diese Implementierung würde beide Ansätze kombinieren
        # Wird in einer späteren Version implementiert
        raise NotImplementedError("Hybrid-Modus ist noch nicht implementiert")
    
    async def _create_mappings(self) -> None:
        """
        Erstellt Mappings zwischen Quell- und Zieldateien.
        Verwendet die aus der Datenbank geladene Struktur.
        """
        if not self.event_info or not self.config:
            raise ValueError("Event-Info oder Konfiguration wurde nicht initialisiert")
        
        target_base = Path(self.config.target_dir) / self.event_info.name
        
        # Erstelle Asset-Verzeichnis
        assets_base = target_base / "assets"
        
        # Erstelle Mappings für jede Sprache
        for lang in self.config.languages:
            lang_dir = target_base / lang
            
            # Erstelle Track-Mappings
            for track in self.event_info.tracks:
                track_dir = lang_dir / f"{track.id}_{lang}"
                
                # Track-Summary
                if lang in track.summary_files:
                    source_path = track.summary_files[lang]
                    target_path = str(track_dir / f"{track.id}_summary_{lang}.md")
                    
                    self.mappings.append(ExportMapping(
                        source_path=source_path,
                        target_path=target_path,
                        type="track",
                        language=lang,
                        track_id=track.id,
                        event_id=self.event_info.id
                    ))
                
                # Session-Dateien
                for session in track.sessions:
                    if lang in session.markdown_files:
                        source_path = session.markdown_files[lang]
                        target_path = str(track_dir / f"{session.id}_{lang}.md")
                        
                        self.mappings.append(ExportMapping(
                            source_path=source_path,
                            target_path=target_path,
                            type="session",
                            language=lang,
                            session_id=session.id,
                            track_id=track.id,
                            event_id=self.event_info.id
                        ))
            
            # Asset-Mappings (nur einmal, nicht pro Sprache)
            if self.config.include_assets:
                for track in self.event_info.tracks:
                    for session in track.sessions:
                        session_assets_dir = assets_base / f"{session.id}_en"
                        
                        for asset_path in session.assets:
                            asset_file = Path(asset_path)
                            target_path = str(session_assets_dir / asset_file.name)
                            
                            # Prüfe, ob bereits ein Mapping für dieses Asset existiert
                            if not any(m.source_path == asset_path for m in self.mappings):
                                self.mappings.append(ExportMapping(
                                    source_path=asset_path,
                                    target_path=target_path,
                                    type="asset",
                                    session_id=session.id,
                                    track_id=track.id,
                                    event_id=self.event_info.id
                                ))
        
        # Zähle Gesamtanzahl der Dateien für den Fortschritt
        self.progress.total_files = len(self.mappings)
        self.logger.info(f"{len(self.mappings)} Mappings erstellt")
    
    async def _perform_export(self) -> None:
        """
        Führt den Export basierend auf den erstellten Mappings durch.
        """
        # Erstelle Zielverzeichnisse
        await self._create_target_directories()
        
        # Kopiere und verarbeite Dateien
        for idx, mapping in enumerate(self.mappings):
            try:
                source_path = Path(mapping.source_path)
                target_path = Path(mapping.target_path)
                
                # Prüfe ob Quelldatei existiert
                if not source_path.exists():
                    self.logger.warning(f"Quelldatei existiert nicht: {source_path}")
                    continue
                
                # Erstelle Zielverzeichnis, falls nicht vorhanden
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                if mapping.type == "asset":
                    # Assets einfach kopieren
                    shutil.copy2(source_path, target_path)
                else:
                    # Markdown-Dateien verarbeiten und Pfade anpassen
                    await self._process_markdown_file(mapping)
                
                self.progress.processed_files += 1
                self.progress.progress_percentage = (self.progress.processed_files / self.progress.total_files) * 100
                
                if idx % 10 == 0 or idx == len(self.mappings) - 1:
                    self.logger.info(f"Export-Fortschritt: {self.progress.progress_percentage:.1f}% ({self.progress.processed_files}/{self.progress.total_files})")
            
            except Exception as e:
                self.logger.error(f"Fehler beim Exportieren von {mapping.source_path}: {str(e)}")
                continue
    
    async def _create_target_directories(self) -> None:
        """
        Erstellt die Zielverzeichnisstruktur.
        """
        if not self.event_info or not self.config:
            raise ValueError("Event-Info oder Konfiguration wurde nicht initialisiert")
        
        target_base = Path(self.config.target_dir) / self.event_info.name
        
        # Erstelle Basis-Verzeichnis
        target_base.mkdir(parents=True, exist_ok=True)
        
        # Erstelle Asset-Verzeichnis
        assets_dir = target_base / "assets"
        assets_dir.mkdir(exist_ok=True)
        
        # Erstelle Verzeichnisse für jede Sprache
        for lang in self.config.languages:
            lang_dir = target_base / lang
            lang_dir.mkdir(exist_ok=True)
            
            # Erstelle Track-Verzeichnisse
            for track in self.event_info.tracks:
                track_dir = lang_dir / f"{track.id}_{lang}"
                track_dir.mkdir(exist_ok=True)
                
                # Erstelle Session-Asset-Verzeichnisse
                if self.config.include_assets:
                    for session in track.sessions:
                        session_assets_dir = assets_dir / f"{session.id}_en"
                        session_assets_dir.mkdir(exist_ok=True)
    
    async def _process_markdown_file(self, mapping: ExportMapping) -> None:
        """
        Verarbeitet eine Markdown-Datei und passt Pfade an.
        
        Args:
            mapping: Das ExportMapping mit Quell- und Zielpfad
        """
        source_path = Path(mapping.source_path)
        target_path = Path(mapping.target_path)
        
        # Lese Quell-Markdown
        with open(source_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Passt Bildpfade an (von [assets/preview_001.jpg] zu [../../assets/sessionname_en/preview_001.jpg])
        if mapping.session_id and mapping.type == "session":
            # Relativer Pfad vom Track-Verzeichnis zum Asset-Verzeichnis
            relative_path = f"../../assets/{mapping.session_id}_en"
            
            # Ersetze Bildpfade
            content = re.sub(
                r'!\[\[assets/([^\]]+)\]\]',
                f'![[{relative_path}/\\1]]',
                content
            )
        
        # Schreibe bearbeitete Datei
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        self.logger.debug(f"Markdown-Datei verarbeitet: {target_path}")
    
    async def export(
        self,
        config: Optional[ObsidianExportConfig] = None,
        use_cache: bool = True
    ) -> ObsidianExportResponse:
        """
        Führt den Export gemäß der Konfiguration durch.
        
        Args:
            config: Optionale Konfiguration (überschreibt die Konfiguration aus dem Constructor)
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            ObsidianExportResponse: Das Ergebnis des Exports
        """
        start_time = datetime.now()
        
        # Konfiguration sicherstellen
        if config:
            self.config = config
        
        if not self.config:
            return self.create_response(
                processor_name="obsidian",
                result=None,
                request_info={},
                response_class=ObsidianExportResponse,
                error=ErrorInfo(
                    code="CONFIG_ERROR",
                    message="Keine Konfiguration vorhanden"
                )
            )
        
        try:
            # Cache-Key generieren
            cache_key = self._generate_cache_key(
                event_name=self.config.event_name,
                export_mode=self.config.export_mode,
                languages=self.config.languages
            )
            
            # Cache prüfen
            if use_cache:
                cache_result = self._check_cache(cache_key)
                if cache_result:
                    result, _ = cache_result
                    self.logger.info("Obsidian-Export aus Cache geladen", 
                                   cache_key=cache_key)
                    
                    return self.create_response(
                        processor_name="obsidian",
                        result=result.progress,
                        request_info=self.config.to_dict(),
                        response_class=ObsidianExportResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )
            
            # Export durchführen
            self.progress = ExportProgress()
            self.progress.start_time = datetime.now()
            self.progress.status = "running"
            
            # Event-Struktur aus der Datenbank laden
            self.event_info = await self._load_event_structure_from_db(self.config.event_name)
            
            # Je nach Export-Modus ausführen
            if self.config.export_mode == "copy":
                await self._execute_copy_mode()
            elif self.config.export_mode == "regenerate":
                await self._execute_regenerate_mode()
            elif self.config.export_mode == "hybrid":
                await self._execute_hybrid_mode()
            else:
                raise ValueError(f"Ungültiger Export-Modus: {self.config.export_mode}")
            
            self.progress.status = "completed"
            self.progress.end_time = datetime.now()
            
            if self.progress.start_time and self.progress.end_time:
                delta = self.progress.end_time - self.progress.start_time
                self.progress.duration_seconds = delta.total_seconds()
            
            # Ergebnis im Cache speichern
            result = ObsidianProcessingResult(
                source_dir=self.config.source_dir,
                target_dir=self.config.target_dir,
                event_name=self.config.event_name,
                languages=self.config.languages,
                export_mode=self.config.export_mode,
                progress=self.progress,
                mappings=self.mappings,
                event_info=self.event_info,
                process_id=self.process_id,
                status="success"
            )
            
            self._save_to_cache(cache_key, result)
            
            self.logger.info(f"Obsidian-Export abgeschlossen: {self.progress.processed_files} Dateien in {self.progress.duration_seconds:.2f} Sekunden")
            
            # Response erstellen
            return self.create_response(
                processor_name="obsidian",
                result=self.progress,
                request_info=self.config.to_dict(),
                response_class=ObsidianExportResponse,
                from_cache=False,
                cache_key=cache_key
            )
            
        except Exception as e:
            self.progress.status = "failed"
            self.progress.error = str(e)
            self.progress.end_time = datetime.now()
            
            if self.progress.start_time and self.progress.end_time:
                delta = self.progress.end_time - self.progress.start_time
                self.progress.duration_seconds = delta.total_seconds()
            
            self.logger.error(f"Fehler beim Obsidian-Export: {str(e)}", 
                           traceback=traceback.format_exc())
            
            return self.create_response(
                processor_name="obsidian",
                result=self.progress,
                request_info=self.config.to_dict() if self.config else {},
                response_class=ObsidianExportResponse,
                error=ErrorInfo(
                    code=type(e).__name__,
                    message=str(e),
                    details={
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc()
                    }
                )
            )


# Für Abwärtskompatibilität mit vorhandenem Code
class ObsidianExporter(ObsidianProcessor):
    """Legacy-Klasse für Abwärtskompatibilität"""
    pass 