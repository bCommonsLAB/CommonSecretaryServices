"""
Event-Prozessor für die Verarbeitung von Events.
"""
from datetime import datetime, UTC
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypeVar, cast
import traceback
from contextlib import nullcontext
import time

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from core.models.transformer import TransformerData
from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.core.models.base import ErrorInfo, ProcessInfo, RequestInfo
from src.core.models.event import EventInput, EventOutput, EventData, EventResponse
from src.core.models.track import TrackData, TrackInput, TrackOutput
from src.core.models.transformer import TransformerResponse
from src.core.models.enums import ProcessingStatus
from src.core.resource_tracking import ResourceCalculator
from src.utils.processor_cache import ProcessorCache
from src.utils.performance_tracker import get_performance_tracker
from .transformer_processor import TransformerProcessor
from .cacheable_processor import CacheableProcessor
from .track_processor import TrackProcessor, safe_get

# Typ-Variablen für Dictionary-Zugriffe
T = TypeVar('T')

# Konstanten für ProcessorType
PROCESSOR_TYPE_EVENT = "event"

class EventProcessingResult:
    """
    Ergebnisstruktur für die Event-Verarbeitung.
    Wird für Caching verwendet.
    """
    
    def __init__(
        self,
        event_name: str,
        template: str,
        target_language: str,
        summary: str,
        metadata: Dict[str, Any],
        structured_data: Dict[str, Any],
        tracks: List[TrackData],
        process_id: Optional[str] = None
    ):
        self.event_name = event_name
        self.template = template
        self.target_language = target_language
        self.summary = summary
        self.metadata = metadata
        self.structured_data = structured_data
        self.tracks = tracks
        self.process_id = process_id
        
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.summary else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "event_name": self.event_name,
            "template": self.template,
            "target_language": self.target_language,
            "summary": self.summary,
            "metadata": self.metadata,
            "structured_data": self.structured_data,
            "tracks": [t.to_dict() for t in self.tracks],
            "process_id": self.process_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EventProcessingResult':
        """Erstellt ein EventProcessingResult aus einem Dictionary."""
        tracks_data: List[Dict[str, Any]] = safe_get(data, "tracks", cast(List[Dict[str, Any]], []))
        tracks: List[TrackData] = []
        
        for track_dict in tracks_data:
            try:
                # Erstelle TrackData aus Dictionary
                input_dict = track_dict.get("input", {})
                output_dict = track_dict.get("output", {})
                
                # Erstelle TrackInput und TrackOutput objekte
                try:
                    track_input = TrackInput(
                        track_name=str(input_dict.get("track_name", "")),
                        template=str(input_dict.get("template", "")),
                        target_language=str(input_dict.get("target_language", ""))
                    )
                except Exception as e:
                    # Falls Fehler, behalte das Dictionary
                    track_input = input_dict
                
                try:
                    track_output = TrackOutput(
                        summary=str(output_dict.get("summary", "")),
                        metadata=output_dict.get("metadata", {}),
                        structured_data=output_dict.get("structured_data", {})
                    )
                except Exception as e:
                    # Falls Fehler, behalte das Dictionary
                    track_output = output_dict
                
                # Erstelle TrackData mit korrekten Objekten
                track_data = TrackData(
                    input=track_input,
                    output=track_output,
                    sessions=track_dict.get("sessions", []),
                    session_count=track_dict.get("session_count", 0),
                    query=track_dict.get("query", ""),
                    context=track_dict.get("context", {})
                )
                tracks.append(track_data)
            except Exception as e:
                # Fehler bei der Deserialisierung eines Tracks überspringen und protokollieren
                print(f"Fehler beim Deserialisieren eines Tracks: {str(e)}")
                continue
        
        # Verwende sichere Cast-Operationen für Dictionaries
        metadata_dict: Dict[str, Any] = dict(safe_get(data, "metadata", cast(Dict[str, Any], {})))
        structured_data_dict: Dict[str, Any] = dict(safe_get(data, "structured_data", cast(Dict[str, Any], {})))
        
        return cls(
            event_name=str(safe_get(data, "event_name", "")),
            template=str(safe_get(data, "template", "")),
            target_language=str(safe_get(data, "target_language", "")),
            summary=str(safe_get(data, "summary", "")),
            metadata=metadata_dict,
            structured_data=structured_data_dict,
            tracks=tracks,
            process_id=str(safe_get(data, "process_id", "")) if safe_get(data, "process_id", None) else None
        )
    
    def to_event_data(self) -> EventData:
        """
        Konvertiert das Ergebnis in ein EventData-Objekt.
        
        Returns:
            EventData: Das EventData-Objekt für die Response
        """
        # Event-Input erstellen
        event_input = EventInput(
            event_name=self.event_name,
            template=self.template,
            target_language=self.target_language
        )
        
        # Event-Output erstellen
        event_output = EventOutput(
            summary=self.summary,
            metadata=self.metadata,
            structured_data=self.structured_data
        )
        
        # Event-Data erstellen
        event_data = EventData(
            input=event_input,
            output=event_output,
            tracks=self.tracks,
            track_count=len(self.tracks),
            query="",  # Wird nicht im Cache gespeichert
            context={}  # Wird nicht im Cache gespeichert
        )
        
        return event_data
    
    def to_event_response(self) -> EventResponse:
        """
        Konvertiert das Ergebnis in eine EventResponse.
        
        Returns:
            EventResponse: Die generierte Response
        """
        # Event-Data erstellen
        event_data = self.to_event_data()
        
        # Request-Info erstellen
        request = RequestInfo(
            processor=PROCESSOR_TYPE_EVENT,
            timestamp=datetime.now().isoformat(),
            parameters={
                "event_name": self.event_name,
                "template": self.template,
                "target_language": self.target_language
            }
        )
        
        # Process-Info erstellen
        process = ProcessInfo(
            id=self.process_id or "",
            main_processor=PROCESSOR_TYPE_EVENT,
            started=datetime.now().isoformat(),
            sub_processors=[],
            completed=None,
            duration=None
        )
        
        # Response erstellen
        response = EventResponse(
            request=request,
            process=process,
            status=ProcessingStatus.SUCCESS,
            error=None,
            data=event_data
        )
        
        return response

class EventProcessor(CacheableProcessor[EventProcessingResult]):
    """
    Prozessor für die Verarbeitung von Events.
    Erstellt eine Zusammenfassung für ein Event basierend auf den zugehörigen Tracks.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "event_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None) -> None:
        """
        Initialisiert den EventProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Optional, die Process-ID vom API-Layer
            parent_process_info: Optional, ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        try:
            # Konfiguration laden
            event_config: Dict[str, Any] = self.load_processor_config('event')
            
            # Initialisiere MongoDB-Verbindung
            self._init_mongodb(event_config)
            
            # Initialisiere Sub-Prozessoren
            self.transformer_processor = TransformerProcessor(
                resource_calculator, 
                process_id,
                parent_process_info=self.process_info
            )
            
            self.track_processor = TrackProcessor(
                resource_calculator,
                process_id,
                parent_process_info=self.process_info
            )
            
            # Basis-Verzeichnis für Events
            app_config = Config()
            
            self.base_dir = Path(app_config.get('events', {}).get('base_dir', './sessions'))
            self.base_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialisiere Cache
            self.cache = ProcessorCache[EventProcessingResult](str(self.cache_collection_name))
            
            self.logger.info("Event Processor initialisiert")
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Initialisierung des Event Processors: {str(e)}")
            raise
    
    def _init_mongodb(self, config: Dict[str, Any]) -> None:
        """
        Initialisiert die MongoDB-Verbindung.
        
        Args:
            config: Konfiguration für den Event-Prozessor
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
        self._track_cache: Collection[Dict[str, Any]] = self._mongo_db.track_cache  # Collection für Track-Cache
        
        self.logger.debug("MongoDB-Verbindung initialisiert",
                        uri=mongo_uri,
                        database=db_name,
                        collection=self._track_cache.name) # Zeige den tatsächlichen Collection-Namen
    
    @property
    def client(self) -> MongoClient[Dict[str, Any]]:
        """MongoDB Client Property."""
        return self._mongo_client

    @property
    def db(self) -> Database[Dict[str, Any]]:
        """MongoDB Database Property."""
        return self._mongo_db

    @property
    def track_cache(self) -> Collection[Dict[str, Any]]:
        """MongoDB Collection für Track Cache."""
        return self._track_cache
    
    async def get_tracks(self, event_name: str, target_language: str) -> List[TrackData]:
        """
        Holt alle Tracks eines Events aus der Datenbank.
        
        Args:
            event_name: Name des Events
            
        Returns:
            List[TrackData]: Liste aller Track-Daten für das Event
        """
        self.logger.info(f"Hole Tracks für Event: {event_name}")
        
        # Tracks aus der Datenbank holen (track_cache Collection)
        # Sortiere nach processed_at absteigend (neueste zuerst)
        track_docs = list(self.track_cache.find(
            {"data.result.metadata.event": event_name, "data.result.target_language": target_language, "status": "success"}
        ).sort("processed_at", -1))
        
        if not track_docs:
            self.logger.warning(f"Keine Tracks für Event '{event_name}' gefunden")
            return []
        
        self.logger.info(f"Gefunden: {len(track_docs)} Tracks für Event '{event_name}'")
        
        # Track-Dokumente in TrackData-Objekte umwandeln
        tracks: List[TrackData] = []
        processed_track_names: set[str] = set()  # Set zum Speichern bereits verarbeiteter Track-Namen
        
        for doc in track_docs:
            # _id entfernen (nicht serialisierbar)
            if '_id' in doc:
                del doc['_id']
            
            try:
                # Prüfe, ob result unter data.result vorhanden ist
                if 'data' not in doc or 'result' not in doc.get('data', {}):
                    self.logger.warning(f"Track {doc.get('track_name')} hat keine Ergebnisse")
                    continue
                
                # Ergebnisse extrahieren
                result = doc.get('data', {}).get('result', {})
                
                # Extrahiere Track-Namen für Duplikaterkennung
                track_name = result.get('track_name')
                if not track_name:
                    self.logger.warning(f"Track hat keinen Namen")
                    continue
                
                # Überspringe Duplikate (gleicher Track-Name)
                if track_name in processed_track_names:
                    self.logger.debug(f"Überspringe doppelten Track-Namen: {track_name}")
                    continue
                
                # Füge Track-Namen zum Set der verarbeiteten Track-Namen hinzu
                processed_track_names.add(track_name)
                
                # Extrahiere Input-Daten
                input_dict = result.get('input', {})
                
                # Erstelle TrackInput-Objekt
                try:
                    track_input = TrackInput(
                        track_name=str(input_dict.get("track_name", "")),
                        template=str(input_dict.get("template", "")),
                        target_language=str(input_dict.get("target_language", "de"))
                    )
                except Exception as e:
                    self.logger.warning(f"Fehler beim Erstellen des TrackInput-Objekts: {str(e)}")
                    track_input = input_dict  # Fallback auf Dictionary
                
                # Extrahiere Output-Daten
                output_dict = result.get('output', {})
                
                # Erstelle TrackOutput-Objekt
                try:
                    track_output = TrackOutput(
                        summary=str(output_dict.get("summary", "")),
                        metadata=output_dict.get("metadata", {}),
                        structured_data=output_dict.get("structured_data", {})
                    )
                except Exception as e:
                    self.logger.warning(f"Fehler beim Erstellen des TrackOutput-Objekts: {str(e)}")
                    track_output = output_dict  # Fallback auf Dictionary
                
                # Extrahiere Sessions (vereinfacht, da wir sie nicht direkt verwenden)
                sessions = result.get('sessions', [])
                
                # Erstelle TrackData-Objekt
                # Verwende Any-Cast, um Typprüfung zu umgehen, falls wir Fallback-Dictionaries verwenden
                track_data = TrackData(
                    input=cast(TrackInput, track_input),
                    output=cast(TrackOutput, track_output),
                    sessions=sessions,
                    session_count=len(sessions),
                    query="",  # Wir behalten dieses leere Feld bei
                    context={}  # Wir behalten dieses leere Feld bei
                )
                
                tracks.append(track_data)
            except Exception as e:
                self.logger.error(f"Fehler beim Konvertieren eines Track-Dokuments: {str(e)}")
                continue
        
        self.logger.info(f"{len(tracks)} Tracks für Event '{event_name}' gefunden")
        return tracks
    
    
    async def _save_event_summary(self, event_name: str, summary: str, target_language: str) -> str:
        """
        Speichert die Event-Zusammenfassung in einer Markdown-Datei.
        Der Dateiname beginnt mit einem Unterstrich, damit er im Verzeichnis an erster Stelle angezeigt wird.
        
        Args:
            event_name: Name des Events (z.B. "FOSDEM 2025")
            summary: Die generierte Zusammenfassung
            target_language: Zielsprache (default: "de")
            source_language: Quellsprache (default: "de")
            
        Returns:
            str: Pfad zur gespeicherten Datei
        """
         # Sanitize translated names for directory creation
        sanitized_event = self._sanitize_filename(event_name)
        
        # Erstelle den Verzeichnispfad
        base_path: Path = self.base_dir / sanitized_event / target_language 
        
        # Stelle sicher, dass das Verzeichnis existiert
        base_path.mkdir(parents=True, exist_ok=True)


        file_path: Path = base_path / (event_name + ".md")

        # Zusammenfassung in die Datei schreiben
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        self.logger.info(f"Event-Zusammenfassung gespeichert: {file_path}")
        return str(file_path)
    
    def _generate_cache_key(
        self,
        event_name: str,
        template: str,
        target_language: str
    ) -> str:
        """
        Generiert einen eindeutigen Cache-Schlüssel für die Event-Verarbeitung.
        
        Args:
            event_name: Name des Events
            template: Name des Templates
            target_language: Zielsprache
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Key aus Event-Name
        base_key = ProcessorCache.generate_simple_key(event_name)
        
        # Parameter in Hash einbeziehen
        param_str = f"{template}_{target_language}"
        return hashlib.sha256(f"{base_key}_{param_str}".encode()).hexdigest()
    
    def _check_cache(
        self,
        cache_key: str
    ) -> Optional[Tuple[EventProcessingResult, Dict[str, Any]]]:
        """
        Prüft, ob ein Cache-Eintrag für die Event-Verarbeitung existiert.
        
        Args:
            cache_key: Der Cache-Schlüssel
            
        Returns:
            Optional[Tuple[EventProcessingResult, Dict[str, Any]]]: 
                Das geladene Ergebnis und Metadaten oder None
        """
        # Verwende die get_from_cache-Methode der CacheableProcessor-Basisklasse
        cache_hit, result = self.get_from_cache(cache_key)
        
        if cache_hit and result:
            self.logger.info("Cache-Hit für Event-Verarbeitung", 
                           cache_key=cache_key)
            # Erstelle leere Metadaten, da diese in der MongoDB-Version nicht
            # als separates Dictionary zurückgegeben werden
            metadata = {
                'event_name': result.event_name,
                'template': result.template,
                'target_language': result.target_language,
                'process_id': result.process_id
            }
            return result, metadata
            
        return None
    
    def _save_to_cache(
        self,
        cache_key: str,
        result: EventProcessingResult
    ) -> None:
        """
        Speichert ein Verarbeitungsergebnis im Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            result: Das zu speichernde Ergebnis
        """
        try:
            # Verwende die save_to_cache-Methode der CacheableProcessor-Basisklasse
            self.save_to_cache(cache_key=cache_key, result=result)
            
            self.logger.info("Event-Verarbeitungsergebnis im Cache gespeichert", 
                          cache_key=cache_key)
        except Exception as e:
            # Fehler beim Cache-Speichervorgang protokollieren, aber Hauptprozess nicht unterbrechen
            self.logger.error(f"Fehler beim Speichern des Ergebnisses im Cache: {str(e)}",
                            error=e,
                            traceback=traceback.format_exc())
    
    def _merge_track_markdowns(self, tracks: List[TrackData]) -> str:
        """
        Führt die Markdown-Inhalte aller Tracks zu einem einzigen Markdown-String zusammen.
        
        Args:
            tracks (List[TrackData]): Liste der Track-Daten
            
        Returns:
            str: Zusammengeführter Markdown-Inhalt
        """
        merged_content: List[str] = []
        
        for i, track in enumerate(tracks):
            try:
                # Markdown-Inhalt aus dem Track extrahieren mit robuster Typprüfung
                track_summary: str = ""
                
                if isinstance(track.output, dict):
                    # Wenn output ein Dictionary ist
                    track_dict: Dict[str, Any] = cast(Dict[str, Any], track.output)
                    track_summary = str(track_dict.get("summary", ""))
                elif hasattr(track.output, "summary"):
                    # Wenn output ein TrackOutput-Objekt ist
                    track_summary = str(track.output.summary)
                else:
                    # Fallback, sollte nie auftreten
                    self.logger.warning(f"Unbekannter Output-Typ für Track {i}")
                    track_summary = ""
                
                # Zum zusammengeführten Inhalt hinzufügen
                # Füge Trenner hinzu, außer beim letzten Track
                if i < len(tracks) - 1:
                    merged_content.append(track_summary + "\n\n\n---\n\n\n")
                else:
                    merged_content.append(track_summary)
                
            except Exception as e:
                self.logger.warning(f"Fehler beim Extrahieren von Markdown aus Track: {str(e)}")
                continue
        
        return "\n".join(merged_content)
    
    async def _create_context_from_tracks(self, tracks: List[TrackData], target_language: str = "de") -> Dict[str, Any]:
        """
        Erstellt einen Kontext aus den Track-Daten für die Template-Verarbeitung.
        
        Args:
            tracks (List[TrackData]): Liste der Track-Daten
            target_language: Zielsprache (default: "de")
            
        Returns:
            Dict[str, Any]: Kontext für die Template-Verarbeitung
        """
        context: Dict[str, Any] = {
            "tracks": []
        }
        
        for track in tracks:
            try:
                # Track-Daten extrahieren mit robuster Typprüfung
                track_name: str = ""
                track_summary: str = ""
                track_metadata: Dict[str, Any] = {}
                track_structured_data: Dict[str, Any] = {}
                
                # Name extrahieren
                if isinstance(track.input, dict):
                    input_dict: Dict[str, Any] = cast(Dict[str, Any], track.input)
                    track_name = str(input_dict.get("track_name", ""))
                elif hasattr(track.input, "track_name"):
                    track_name = str(track.input.track_name)
                
                # Output-Daten extrahieren
                if isinstance(track.output, dict):
                    output_dict: Dict[str, Any] = cast(Dict[str, Any], track.output)
                    track_summary = str(output_dict.get("summary", ""))
                    track_metadata = output_dict.get("metadata", {})
                    track_structured_data = output_dict.get("structured_data", {})
                elif hasattr(track.output, "summary") and hasattr(track.output, "metadata") and hasattr(track.output, "structured_data"):
                    track_summary = str(track.output.summary)
                    track_metadata = track.output.metadata
                    track_structured_data = track.output.structured_data
                
                # Stelle sicher, dass die Metadata ein Dict ist
                if not isinstance(track_metadata, dict):
                    track_metadata = {}
                if not isinstance(track_structured_data, dict):
                    track_structured_data = {}
                
                metadata_dict: Dict[str, Any] = track_metadata 
                structured_dict: Dict[str, Any] = track_structured_data
                
                # Pfad-Informationen extrahieren
                track_dir = str(metadata_dict.get("track_dir", ""))
                track_dir = track_dir.replace("\\", "/")
                summary_file = str(metadata_dict.get("summary_file", ""))

                obsidian_link = f"{track_dir}/{summary_file}"
                track_title = summary_file.replace("_", "")
                track_title = track_title.replace(".md", "")
                
                obsidian_link = obsidian_link.replace(" ", "%20")
                
                # Track-Kontext erstellen mit Standardwerten
                track_context: Dict[str, Any] = {
                    "name": track_name,
                    "summary": track_summary,
                    "topic": str(structured_dict.get("topic", "")),
                    "tags": str(structured_dict.get("tags", "")),
                    "general_summary": str(structured_dict.get("general_summary", "")),
                    "eco_social_relevance": str(structured_dict.get("eco_social_relevance", "")),
                    "eco_social_applications": str(structured_dict.get("eco_social_applications", "")),
                    "challenges": str(structured_dict.get("challenges", "")),
                    "session_count": int(metadata_dict.get("sessions_count", 0)),
                    "sessions": str(structured_dict.get("event_list", "")),
                    "obsidian_link": obsidian_link,
                    "track_title": track_title
                }
                
                context["tracks"].append(track_context)
                
            except Exception as e:
                self.logger.warning(f"Fehler beim Erstellen des Track-Kontexts: {str(e)}")
                continue
        
        # Allgemeine Event-Informationen
        context["event_name"] = ""
        context["track_count"] = len(tracks)
        
        return context
    
    async def create_event_summary(
        self,
        event_name: str,
        template: str = "event-eco-social-summary",
        target_language: str = "de",
        use_cache: bool = True
    ) -> EventResponse:
        """
        Erstellt eine Zusammenfassung für ein Event.
        
        Args:
            event_name: Name des Events
            template: Name des Templates für die Zusammenfassung
            target_language: Zielsprache für die Zusammenfassung
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            EventResponse: Die Zusammenfassung des Events
        """
        # Performance Tracking initialisieren
        tracker = get_performance_tracker()
        start_time = time.time()
        
        try:
            with tracker.measure_operation('create_event_summary', 'event') if tracker else nullcontext():
                self.logger.info("Starte Event-Zusammenfassung", 
                               event_name=event_name,
                               template=template,
                               target_language=target_language)
                
                # Eingabedaten validieren
                event_name = self.validate_text(event_name, "event_name")
                target_language = self.validate_language_code(target_language, "target_language")
                template = self.validate_text(template, "template") + "_" + target_language
                
                # Cache-Key generieren
                cache_key = self._generate_cache_key(
                    event_name=event_name,
                    template=template,
                    target_language=target_language
                )
                
                # Cache prüfen, wenn aktiviert
                if use_cache:
                    cache_result = self._check_cache(cache_key)
                    if cache_result:
                        result, _ = cache_result
                        self.logger.info("Event-Zusammenfassung aus Cache geladen", 
                                       event_name=event_name,
                                       cache_key=cache_key,
                                       processing_time=time.time() - start_time)
                        
                        # Standardisierte Response-Erstellung aus dem Cache-Ergebnis
                        return self.create_response(
                            processor_name=PROCESSOR_TYPE_EVENT,
                            result=result.to_event_data(),
                            request_info={
                                "event_name": event_name,
                                "template": template,
                                "target_language": target_language
                            },
                            response_class=EventResponse,
                            from_cache=True,
                            cache_key=cache_key
                        )
                
                # Request-Info erstellen
                request_info = {
                    "event_name": event_name,
                    "template": template,
                    "target_language": target_language
                }
                
                # Tracks holen
                with tracker.measure_operation('get_tracks', 'event') if tracker else nullcontext():
                    tracks: List[TrackData] = await self.get_tracks(event_name, target_language)
                
                if not tracks:
                    raise ProcessingError(f"Keine Tracks für Event '{event_name}' gefunden")
                
                # Markdown-Inhalte der Tracks zusammenführen
                with tracker.measure_operation('merge_track_markdowns', 'event') if tracker else nullcontext():
                    all_markdown = self._merge_track_markdowns(tracks)
                
                # Kontext aus allen Tracks erstellen
                with tracker.measure_operation('create_context_from_tracks', 'event') if tracker else nullcontext():
                    context = await self._create_context_from_tracks(tracks, target_language)
                
                # Template-Transformation durchführen
                with tracker.measure_operation('transform_template', 'event') if tracker else nullcontext():
                    transform_result: TransformerResponse = self.transformer_processor.transformByTemplate(
                        text=all_markdown,
                        source_language=target_language,  # Wir nehmen an, dass die Markdown-Dateien bereits in Zielsprache sind
                        target_language=target_language,
                        template=template,
                        context=context,
                        use_cache=use_cache
                    )
                
                # Prüfen, ob ein Fehler zurückgegeben wurde
                if transform_result.error:
                    self.logger.error(f"Fehler bei der Template-Transformation: {transform_result.error.message}")
                    
                    # Fehler-Informationen übernehmen
                    error_info = ErrorInfo(
                        code=transform_result.error.code,
                        message=f"Template-Transformationsfehler: {transform_result.error.message}",
                        details={
                            **transform_result.error.details,
                            "event_name": event_name,
                            "template": template
                        }
                    )
                    
                    # Fehler-Response zurückgeben
                    return self.create_response(
                        processor_name=PROCESSOR_TYPE_EVENT,
                        result=None,
                        request_info={
                            "event_name": event_name,
                            "template": template,
                            "target_language": target_language
                        },
                        response_class=EventResponse,
                        from_cache=False,
                        cache_key="",
                        error=error_info
                    )
                
                # Ausgabedaten erstellen
                summary: str = ""
                structured_data: Dict[str, Any] = {}
                
                # Sicher auf die Transformer-Ergebnisse zugreifen
                if transform_result.data:
                    data: TransformerData = transform_result.data
                    summary = data.text
                    if data.structured_data:
                        structured_data = data.structured_data  
                
                # Zusammenfassung in Datei speichern
                with tracker.measure_operation('save_summary', 'event') if tracker else nullcontext():
                    summary_file_path = await self._save_event_summary(
                        event_name=event_name,
                        summary=summary,
                        target_language=target_language,
                    )
                
                # Metadaten erstellen
                metadata = {
                    "event": event_name,
                    "tracks_count": len(tracks),
                    "generated_at": datetime.now().isoformat(),
                    "template": template,
                    "language": target_language,
                    "summary_file": summary_file_path
                }
                
                # EventData erstellen
                event_input = EventInput(
                    event_name=event_name,
                    template=template,
                    target_language=target_language
                )
                
                event_output = EventOutput(
                    summary=summary,
                    metadata=metadata,
                    structured_data=structured_data
                )
                
                event_data = EventData(
                    input=event_input,
                    output=event_output,
                    tracks=tracks,
                    track_count=len(tracks),
                    query=all_markdown,
                    context=context
                )
                
                # Response erstellen
                response: EventResponse = self.create_response(
                    processor_name=PROCESSOR_TYPE_EVENT,
                    result=event_data,
                    request_info=request_info,
                    response_class=EventResponse,
                    from_cache=False,
                    cache_key=cache_key
                )
                
                # Im Cache speichern
                self._save_to_cache(
                    cache_key=cache_key,
                    result=EventProcessingResult(
                        event_name=event_name,
                        template=template,
                        target_language=target_language,
                        summary=summary,
                        metadata=metadata,
                        structured_data=dict(structured_data) if structured_data else {},
                        tracks=tracks,
                        process_id=self.process_id
                    )
                )
                
                processing_time = time.time() - start_time
                self.logger.info("Event-Zusammenfassung erstellt",
                               event_name=event_name,
                               processing_time=processing_time,
                               tracks_count=len(tracks))
                
                return response
                
        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                    "event_name": event_name
                }
            )
            
            self.logger.error("Fehler bei der Event-Verarbeitung",
                            error=e,
                            event_name=event_name,
                            traceback=traceback.format_exc())
            
            return self.create_response(
                processor_name=PROCESSOR_TYPE_EVENT,
                result=None,
                request_info={
                    "event_name": event_name,
                    "template": template,
                    "target_language": target_language
                },
                response_class=EventResponse,
                error=error_info,
                from_cache=False,
                cache_key=""
            ) 

    def serialize_for_cache(self, result: EventProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das EventProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das EventProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "processed_at": datetime.now(UTC).isoformat(),
            "event_name": result.event_name,
            "template": result.template,
            "target_language": result.target_language,
            "tracks_count": len(result.tracks),
            "metadata": {
                "event": result.metadata.get("event", ""),
                "generated_at": result.metadata.get("generated_at", ""),
                "summary_file": result.metadata.get("summary_file", "")
            },
            "structured_data": {
                "topic": result.structured_data.get("topic", ""),
                "relevance": result.structured_data.get("relevance", ""),
                "keywords": result.structured_data.get("keywords", [])
            }
        }
        return cache_data
        
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> EventProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein EventProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            EventProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        return EventProcessingResult.from_dict(result_data) 