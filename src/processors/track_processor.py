"""
Track-Prozessor für die Verarbeitung von Event-Tracks.
"""
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict, cast, TypeVar
import traceback
from contextlib import nullcontext
import time

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.core.models.base import ErrorInfo, ProcessInfo, RequestInfo
from src.core.models.track import TrackInput, TrackOutput, TrackData, TrackResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.session import SessionData, SessionInput, SessionOutput
from src.core.models.enums import ProcessingStatus
from src.core.resource_tracking import ResourceCalculator
from src.utils.processor_cache import ProcessorCache
from src.utils.performance_tracker import get_performance_tracker
from .transformer_processor import TransformerProcessor
from .cacheable_processor import CacheableProcessor

# Typ-Variablen für Dictionary-Zugriffe
T = TypeVar('T')

def safe_get(d: Dict[str, Any], key: str, default: T) -> T:
    """Sicherer Dictionary-Zugriff mit Typ-Konvertierung."""
    value = d.get(key, default)
    return cast(T, value)

# Konstanten für ProcessorType
PROCESSOR_TYPE_TRACK = "track"

# Typ-Definitionen für Dictionary-Zugriffe
class SessionInputDict(TypedDict, total=False):
    event: str
    session: str
    url: str
    filename: str
    track: str
    day: Optional[str]
    starttime: Optional[str]
    endtime: Optional[str]
    speakers: List[str]
    video_url: Optional[str]
    attachments_url: Optional[str]
    source_language: str
    target_language: str
    target: Optional[str]
    template: str

class SessionOutputDict(TypedDict, total=False):
    target_dir: str
    web_text: str
    video_transcript: str
    attachments_text: str
    markdown_file: str
    markdown_content: str
    video_file: Optional[str]
    attachments_url: Optional[str]
    attachments: List[str]
    structured_data: Dict[str, Any]

class SessionDict(TypedDict, total=False):
    input: SessionInputDict
    output: SessionOutputDict

class TrackProcessingResult:
    """
    Ergebnisstruktur für die Track-Verarbeitung.
    Wird für Caching verwendet.
    """
    
    def __init__(
        self,
        track_name: str,
        template: str,
        target_language: str,
        summary: str,
        metadata: Dict[str, Any],
        structured_data: Dict[str, Any],
        sessions: List[SessionData],
        process_id: Optional[str] = None
    ):
        self.track_name = track_name
        self.template = template
        self.target_language = target_language
        self.summary = summary
        self.metadata = metadata
        self.structured_data = structured_data
        self.sessions = sessions
        self.process_id = process_id
        
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.summary else ProcessingStatus.ERROR
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "track_name": self.track_name,
            "template": self.template,
            "target_language": self.target_language,
            "summary": self.summary,
            "metadata": self.metadata,
            "structured_data": self.structured_data,
            "sessions": [s.to_dict() for s in self.sessions],
            "process_id": self.process_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TrackProcessingResult':
        """Erstellt ein TrackProcessingResult aus einem Dictionary."""
        sessions_data: List[Dict[str, Any]] = safe_get(data, "sessions", cast(List[Dict[str, Any]], []))
        sessions: List[SessionData] = []
        
        for session_dict in sessions_data:
            # Extrahiere und validiere Input-Daten
            input_data: Dict[str, Any] = safe_get(session_dict, "input", cast(Dict[str, Any], {}))
            session_input = SessionInput(
                event=str(safe_get(input_data, "event", "")),
                session=str(safe_get(input_data, "session", "")),
                url=str(safe_get(input_data, "url", "")),
                filename=str(safe_get(input_data, "filename", "")),
                track=str(safe_get(input_data, "track", "")),
                day=str(safe_get(input_data, "day", "")) if safe_get(input_data, "day", None) else None,
                starttime=str(safe_get(input_data, "starttime", "")) if safe_get(input_data, "starttime", None) else None,
                endtime=str(safe_get(input_data, "endtime", "")) if safe_get(input_data, "endtime", None) else None,
                speakers=list(safe_get(input_data, "speakers", [])),  # type: ignore
                video_url=str(safe_get(input_data, "video_url", "")) if safe_get(input_data, "video_url", None) else None,
                attachments_url=str(safe_get(input_data, "attachments_url", "")) if safe_get(input_data, "attachments_url", None) else None,
                source_language=str(safe_get(input_data, "source_language", "en")),
                target_language=str(safe_get(input_data, "target_language", "de")),
                target=str(safe_get(input_data, "target", "")) if safe_get(input_data, "target", None) else None,
                template=str(safe_get(input_data, "template", "Session"))
            )
            
            # Extrahiere und validiere Output-Daten
            output_data: SessionOutputDict = safe_get(session_dict, "output", cast(SessionOutputDict, {}))  # type: ignore
            session_output = SessionOutput(
                input_data=session_input,
                target_dir=str(safe_get(output_data, "target_dir", "")),  # type: ignore
                web_text=str(safe_get(output_data, "web_text", "")),  # type: ignore
                video_transcript=str(safe_get(output_data, "video_transcript", "")),  # type: ignore
                attachments_text=str(safe_get(output_data, "attachments_text", "")),  # type: ignore
                markdown_file=str(safe_get(output_data, "markdown_file", "")),  # type: ignore
                markdown_content=str(safe_get(output_data, "markdown_content", "")),  # type: ignore
                video_file=str(safe_get(output_data, "video_file", "")) if safe_get(output_data, "video_file", None) else None,  # type: ignore
                attachments_url=str(safe_get(output_data, "attachments_url", "")) if safe_get(output_data, "attachments_url", None) else None,  # type: ignore
                attachments=list(safe_get(output_data, "attachments", [])),  # type: ignore
                structured_data=dict(safe_get(output_data, "structured_data", {}))  # type: ignore
            )
            
            sessions.append(SessionData(input=session_input, output=session_output))
        
        return cls(
            track_name=str(safe_get(data, "track_name", "")),
            template=str(safe_get(data, "template", "")),
            target_language=str(safe_get(data, "target_language", "")),
            summary=str(safe_get(data, "summary", "")),
            metadata=dict(safe_get(data, "metadata", {})), # type: ignore
            structured_data=dict(safe_get(data, "structured_data", {})), # type: ignore
            sessions=sessions,
            process_id=str(safe_get(data, "process_id", "")) if safe_get(data, "process_id", None) else None
        )
    
    def to_track_response(self) -> TrackResponse:
        """
        Konvertiert das Ergebnis in eine TrackResponse.
        
        Returns:
            TrackResponse: Die generierte Response
        """
        # Track-Input erstellen
        track_input = TrackInput(
            track_name=self.track_name,
            template=self.template,
            target_language=self.target_language
        )
        
        # Track-Output erstellen
        track_output = TrackOutput(
            summary=self.summary,
            metadata=self.metadata,
            structured_data=self.structured_data
        )
        
        # Track-Data erstellen
        track_data = TrackData(
            input=track_input,
            output=track_output,
            sessions=self.sessions,
            session_count=len(self.sessions),
            query="",  # Wird nicht im Cache gespeichert
            context={}  # Wird nicht im Cache gespeichert
        )
        
        # Request-Info erstellen
        request = RequestInfo(
            processor=PROCESSOR_TYPE_TRACK,
            timestamp=datetime.now().isoformat(),
            parameters={
                "track_name": self.track_name,
                "template": self.template,
                "target_language": self.target_language
            }
        )
        
        # Process-Info erstellen
        process = ProcessInfo(
            id=self.process_id or "",
            main_processor=PROCESSOR_TYPE_TRACK,
            started=datetime.now().isoformat(),
            sub_processors=[],
            completed=None,
            duration=None
        )
        
        # Response erstellen
        response = TrackResponse(
            request=request,
            process=process,
            status=ProcessingStatus.SUCCESS,
            error=None,
            data=track_data
        )
        
        return response

class TrackProcessor(CacheableProcessor[TrackProcessingResult]):
    """
    Prozessor für die Verarbeitung von Event-Tracks.
    Erstellt eine Zusammenfassung für einen Track basierend auf den zugehörigen Sessions.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "track_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den TrackProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Optional, die Process-ID vom API-Layer
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        try:
            # Konfiguration laden
            track_config: Dict[str, Any] = self.load_processor_config('track')
            
            # Initialisiere MongoDB-Verbindung
            self._init_mongodb(track_config)
            
            # Initialisiere Sub-Prozessoren
            self.transformer_processor = TransformerProcessor(
                resource_calculator, 
                process_id,
                parent_process_info=self.process_info
            )
            
            # Basis-Verzeichnis für Sessions (vorher Events)
            app_config = Config()
            self.base_dir = Path(app_config.get('sessions', {}).get('base_dir', './sessions'))
            self.base_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialisiere Cache
            self.cache = ProcessorCache[TrackProcessingResult](str(self.cache_collection_name))
            
            self.logger.info("Track Processor initialisiert")
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Initialisierung des Track Processors: {str(e)}")
            raise
    
    def _init_mongodb(self, config: Dict[str, Any]) -> None:
        """
        Initialisiert die MongoDB-Verbindung.
        
        Args:
            config: Konfiguration für den Track-Prozessor
        """
        # MongoDB-Konfiguration laden
        app_config = Config()
        mongodb_config = app_config.get('mongodb', {})
        
        # MongoDB-Verbindung herstellen
        mongo_uri = mongodb_config.get('uri', 'mongodb://localhost:27017')
        db_name = mongodb_config.get('database', 'common-secretary-service')
        
        self.client: MongoClient[Dict[str, Any]] = MongoClient(mongo_uri)
        self.db: Database[Dict[str, Any]] = self.client[db_name]
        self.session_jobs: Collection[Dict[str, Any]] = self.db.session_jobs
        
        self.logger.debug("MongoDB-Verbindung initialisiert",
                        uri=mongo_uri,
                        database=db_name)
    
    async def get_track_sessions(self, track_name: str) -> List[SessionData]:
        """
        Holt alle Sessions eines Tracks aus der Datenbank.
        
        Args:
            track_name: Name des Tracks
            
        Returns:
            List[SessionData]: Liste aller Session-Daten für den Track
        """
        self.logger.info(f"Hole Sessions für Track: {track_name}")
        
        # Sessions aus der Datenbank holen
        # Sortiere nach completed_at absteigend (neueste zuerst)
        session_docs = list(self.session_jobs.find(
            {"parameters.track": track_name, "status": "completed"}
        ).sort("completed_at", -1))
        
        if not session_docs:
            self.logger.warning(f"Keine Sessions für Track '{track_name}' gefunden")
            return []
        
        # Session-Dokumente in SessionData-Objekte umwandeln
        sessions: List[SessionData] = []
        processed_job_names: set[str] = set()  # Set zum Speichern bereits verarbeiteter job_names
        
        for doc in session_docs:
            # _id entfernen (nicht serialisierbar)
            if '_id' in doc:
                del doc['_id']
            
            try:
                # Prüfe, ob results vorhanden ist
                if 'results' not in doc or not doc['results']:
                    self.logger.warning(f"Job {doc.get('job_id')} hat keine Ergebnisse")
                    continue
                
                # Prüfe auf eindeutigen job_name
                job_name = doc.get('job_name')
                if not job_name:
                    self.logger.warning(f"Job {doc.get('job_id')} hat keinen job_name")
                    continue
                
                # Überspringe Duplikate (gleicher job_name)
                if job_name in processed_job_names:
                    self.logger.debug(f"Überspringe doppelten job_name: {job_name}")
                    continue
                
                # Füge job_name zum Set der verarbeiteten job_names hinzu
                processed_job_names.add(job_name)
                
                # Parameter und Ergebnisse extrahieren
                parameters = doc.get('parameters', {})
                results = doc.get('results', {})
                
                # SessionInput-Objekt erstellen
                session_input = SessionInput(
                    event=parameters.get('event', ''),
                    session=parameters.get('session', ''),
                    url=parameters.get('url', ''),
                    filename=parameters.get('filename', ''),
                    track=parameters.get('track', ''),
                    day=parameters.get('day'),
                    starttime=parameters.get('starttime'),
                    endtime=parameters.get('endtime'),
                    speakers=parameters.get('speakers', []),
                    video_url=parameters.get('video_url'),
                    attachments_url=parameters.get('attachments_url'),
                    source_language=parameters.get('source_language', 'en'),
                    target_language=parameters.get('target_language', 'de')
                )
                
                # SessionOutput-Objekt erstellen
                session_output = SessionOutput(
                    input_data=session_input,
                    target_dir=str(results.get('target_dir', '')),  # type: ignore
                    web_text=results.get('web_text', ''),
                    video_transcript=results.get('video_transcript', ''),
                    markdown_file=results.get('markdown_file', ''),
                    markdown_content=results.get('markdown_content', ''),
                    video_file=results.get('video_file'),
                    attachments_url=results.get('attachments_url'),
                    attachments=results.get('assets', [])
                )
                
                # SessionData aus SessionInput und SessionOutput erstellen
                session = SessionData(
                    input=session_input,
                    output=session_output
                )
                sessions.append(session)
            except Exception as e:
                self.logger.error(f"Fehler beim Konvertieren eines Session-Dokuments: {str(e)}")
                continue
        
        self.logger.info(f"{len(sessions)} Sessions für Track '{track_name}' gefunden")
        return sessions
    
    def _get_track_directory(self, event_name: str, track_name: str) -> Path:
        """
        Ermittelt das Verzeichnis für einen Track.
        
        Args:
            event_name: Name des Events (z.B. "FOSDEM 2025")
            track_name: Name des Tracks
            
        Returns:
            Path: Pfad zum Track-Verzeichnis
        """
        # Erstelle den Pfad zum Track-Verzeichnis
        track_dir = self.base_dir / event_name / track_name
        
        # Stelle sicher, dass das Verzeichnis existiert
        track_dir.mkdir(parents=True, exist_ok=True)
        
        return track_dir
    
    def _save_track_summary(self, event_name: str, track_name: str, summary: str) -> str:
        """
        Speichert die Track-Zusammenfassung in einer Markdown-Datei.
        
        Args:
            event_name: Name des Events (z.B. "FOSDEM 2025")
            track_name: Name des Tracks
            summary: Die generierte Zusammenfassung
            
        Returns:
            str: Pfad zur gespeicherten Datei
        """
        # Track-Verzeichnis ermitteln
        track_dir = self._get_track_directory(event_name, track_name)
        
        # Dateiname für die Zusammenfassung erstellen
        filename = f"{track_name}-summary.md"
        file_path = track_dir / filename
        
        # Zusammenfassung in die Datei schreiben
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        self.logger.info(f"Track-Zusammenfassung gespeichert: {file_path}")
        return str(file_path)
    
    def _generate_cache_key(
        self,
        track_name: str,
        template: str,
        target_language: str
    ) -> str:
        """
        Generiert einen eindeutigen Cache-Schlüssel für die Track-Verarbeitung.
        
        Args:
            track_name: Name des Tracks
            template: Name des Templates
            target_language: Zielsprache
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Key aus Track-Name
        base_key = ProcessorCache.generate_simple_key(track_name)
        
        # Parameter in Hash einbeziehen
        param_str = f"{template}_{target_language}"
        return hashlib.sha256(f"{base_key}_{param_str}".encode()).hexdigest()
    
    def _check_cache(
        self,
        cache_key: str
    ) -> Optional[Tuple[TrackProcessingResult, Dict[str, Any]]]:
        """
        Prüft, ob ein Cache-Eintrag für die Track-Verarbeitung existiert.
        
        Args:
            cache_key: Der Cache-Schlüssel
            
        Returns:
            Optional[Tuple[TrackProcessingResult, Dict[str, Any]]]: 
                Das geladene Ergebnis und Metadaten oder None
        """
        # Prüfe Cache
        cache_result = self.cache.load_cache_with_key(
            cache_key=cache_key,
            result_class=TrackProcessingResult
        )
        
        if cache_result:
            self.logger.info("Cache-Hit für Track-Verarbeitung", 
                           cache_key=cache_key)
            return cache_result
            
        return None
    
    def _save_to_cache(
        self,
        cache_key: str,
        result: TrackProcessingResult,
        track_name: str,
        template: str,
        target_language: str
    ) -> None:
        """
        Speichert ein Verarbeitungsergebnis im Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            result: Das zu speichernde Ergebnis
            track_name: Name des Tracks
            template: Name des Templates
            target_language: Zielsprache
        """
        # Erstelle Metadaten
        metadata = {
            'track_name': track_name,
            'template': template,
            'target_language': target_language,
            'process_id': self.process_id
        }
        
        # Speichere im Cache
        self.cache.save_cache_with_key(
            cache_key=cache_key,
            result=result,
            metadata=metadata
        )
        
        self.logger.info("Track-Verarbeitungsergebnis im Cache gespeichert", 
                       cache_key=cache_key)
    
    async def create_track_summary(
        self,
        track_name: str,
        template: str = "track-eco-social-summary",
        target_language: str = "de",
        use_cache: bool = True
    ) -> TrackResponse:
        """
        Erstellt eine Zusammenfassung für einen Track.
        
        Args:
            track_name: Name des Tracks
            template: Name des Templates für die Zusammenfassung
            target_language: Zielsprache für die Zusammenfassung
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            TrackResponse: Die Zusammenfassung des Tracks
        """
        # Performance Tracking initialisieren
        tracker = get_performance_tracker()
        start_time = time.time()
        
        try:
            with tracker.measure_operation('create_track_summary', 'track') if tracker else nullcontext():
                self.logger.info("Starte Track-Zusammenfassung", 
                               track_name=track_name,
                               template=template,
                               target_language=target_language)
                
                # Eingabedaten validieren
                track_name = self.validate_text(track_name, "track_name")
                template = self.validate_text(template, "template")
                target_language = self.validate_language_code(target_language, "target_language")
                
                # Cache-Key generieren
                cache_key = self._generate_cache_key(
                    track_name=track_name,
                    template=template,
                    target_language=target_language
                )
                
                # Cache prüfen, wenn aktiviert
                if use_cache:
                    cache_result = self._check_cache(cache_key)
                    if cache_result:
                        result, _ = cache_result
                        self.logger.info("Track-Zusammenfassung aus Cache geladen", 
                                       track_name=track_name,
                                       cache_key=cache_key,
                                       processing_time=time.time() - start_time)
                        return result.to_track_response()
                
                # Request-Info erstellen
                request_info = {
                    "track_name": track_name,
                    "template": template,
                    "target_language": target_language
                }
                
                # Sessions holen (vorher Events)
                with tracker.measure_operation('get_track_sessions', 'track') if tracker else nullcontext():
                    sessions: List[SessionData] = await self.get_track_sessions(track_name)
                
                if not sessions:
                    raise ProcessingError(f"Keine Sessions für Track '{track_name}' gefunden")
                
                # Event-Name aus der ersten Session extrahieren
                event_name = sessions[0].input.event if sessions else "Unknown Event"
                
                # Markdown-Inhalte der Sessions zusammenführen
                with tracker.measure_operation('merge_session_markdowns', 'track') if tracker else nullcontext():
                    all_markdown = self._merge_session_markdowns(sessions)
                
                # Kontext aus allen Sessions erstellen
                with tracker.measure_operation('create_context', 'track') if tracker else nullcontext():
                    context = self._create_context_from_sessions(sessions)
                
                # Template-Transformation durchführen
                with tracker.measure_operation('transform_template', 'track') if tracker else nullcontext():
                    transform_result: TransformerResponse = self.transformer_processor.transformByTemplate(
                        source_text=all_markdown,
                        source_language=target_language,  # Wir nehmen an, dass die Markdown-Dateien bereits in Zielsprache sind
                        target_language=target_language,
                        template=template,
                        context=context
                    )
                
                # Ausgabedaten erstellen
                summary = ""
                structured_data: Dict[str, Any] = {}
                
                if transform_result.data and transform_result.data.output:
                    summary = getattr(transform_result.data.output, 'text', "")
                    if hasattr(transform_result.data.output, 'structured_data'):
                        structured_data = transform_result.data.output.structured_data or {}
                
                # Stelle sicher, dass summary ein String ist
                if summary is None:
                    summary = ""
                
                # Zusammenfassung in Datei speichern
                with tracker.measure_operation('save_summary', 'track') if tracker else nullcontext():
                    summary_file_path = self._save_track_summary(event_name, track_name, summary)
                
                # Metadaten erstellen
                metadata = {
                    "track": track_name,
                    "event": event_name,
                    "sessions_count": len(sessions),
                    "generated_at": datetime.now().isoformat(),
                    "template": template,
                    "language": target_language,
                    "summary_file": summary_file_path
                }
                
                # Optimierte Sessions-Liste erstellen (ohne große Textinhalte)
                with tracker.measure_operation('optimize_sessions', 'track') if tracker else nullcontext():
                    optimized_sessions = self._create_optimized_sessions(sessions)
                
                # TrackData erstellen
                track_input = TrackInput(
                    track_name=track_name,
                    template=template,
                    target_language=target_language
                )
                
                track_output = TrackOutput(
                    summary=summary,
                    metadata=metadata,
                    structured_data=structured_data
                )
                
                track_data = TrackData(
                    input=track_input,
                    output=track_output,
                    sessions=optimized_sessions,
                    session_count=len(sessions),
                    query=all_markdown,
                    context=context
                )
                
                # Response erstellen
                response: TrackResponse = self.create_response(
                    processor_name=PROCESSOR_TYPE_TRACK,
                    result=track_data,
                    request_info=request_info,
                    response_class=TrackResponse,
                    from_cache=False,
                    cache_key=cache_key
                )
                
                # Im Cache speichern
                self._save_to_cache(
                    cache_key=cache_key,
                    result=TrackProcessingResult(
                        track_name=track_name,
                        template=template,
                        target_language=target_language,
                        summary=summary,
                        metadata=metadata,
                        structured_data=structured_data,
                        sessions=optimized_sessions,
                        process_id=self.process_id
                    ),
                    track_name=track_name,
                    template=template,
                    target_language=target_language
                )
                
                processing_time = time.time() - start_time
                self.logger.info("Track-Zusammenfassung erstellt",
                               track_name=track_name,
                               processing_time=processing_time,
                               sessions_count=len(sessions))
                
                return response
                
        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                    "track_name": track_name
                }
            )
            
            self.logger.error("Fehler bei der Track-Verarbeitung",
                            error=e,
                            track_name=track_name,
                            traceback=traceback.format_exc())
            
            return self.create_response(
                processor_name=PROCESSOR_TYPE_TRACK,
                result=None,
                request_info={
                    "track_name": track_name,
                    "template": template,
                    "target_language": target_language
                },
                response_class=TrackResponse,
                error=error_info,
                from_cache=False,
                cache_key=""
            )
    
    def _merge_session_markdowns(self, sessions: List[SessionData]) -> str:
        """
        Führt die Markdown-Inhalte aller Sessions zu einem einzigen Markdown-String zusammen.
        
        Args:
            sessions (List[SessionData]): Liste der Session-Daten
            
        Returns:
            str: Zusammengeführter Markdown-Inhalt
        """
        merged_content: List[str] = []
        
        for i, session in enumerate(sessions):
            try:
                # Markdown-Inhalt aus der Session extrahieren
                session_markdown = session.output.markdown_content or ""
                
                # Transkription entfernen (nur die Variante "\n## Transkription\n")
                transkription_header = "\n## Transkription\n"
                original_length = len(session_markdown)
                
                if transkription_header in session_markdown:
                    parts = session_markdown.split(transkription_header)
                    # Nur den Teil vor der Transkription behalten
                    session_markdown = parts[0].strip()
                    self.logger.debug(f"Transkription aus Session '{session.input.session}' entfernt. Größenreduktion: {original_length - len(session_markdown)} Zeichen")
                
                # Zum zusammengeführten Inhalt hinzufügen (nur den Markdown-Inhalt)
                # Füge Trenner hinzu, außer bei der letzten Session
                if i < len(sessions) - 1:
                    merged_content.append(session_markdown + "\n\n\n---\n\n\n")
                else:
                    merged_content.append(session_markdown)
                
            except Exception as e:
                self.logger.warning(f"Fehler beim Extrahieren von Markdown aus Session: {str(e)}")
                continue
        
        return "\n".join(merged_content)
    
    def _create_context_from_sessions(self, sessions: List[SessionData]) -> Dict[str, Any]:
        """
        Erstellt einen Kontext aus den Session-Daten für die Template-Verarbeitung.
        
        Args:
            sessions (List[SessionData]): Liste der Session-Daten
            
        Returns:
            Dict[str, Any]: Kontext für die Template-Verarbeitung
        """
        context: Dict[str, Any] = {
            "sessions": []
        }
        
        for session in sessions:
            session_context: Dict[str, Any] = {
                "title": session.input.session,
                "filename": session.input.filename,
                "obsidian_link": f"[{session.input.session}]({session.input.filename})",
                "track": session.input.track,
                "url": session.input.url,
                "date": session.input.day or "",
                "speakers": session.input.speakers or []
            }
            
            context["sessions"].append(session_context)
        
        # Allgemeine Track-Informationen
        if sessions:
            context["track_name"] = sessions[0].input.track
            context["event_name"] = sessions[0].input.event
        
        return context
    
    def _create_optimized_sessions(self, sessions: List[SessionData]) -> List[SessionData]:
        """
        Erstellt eine optimierte Version der Sessions-Liste.
        Entfernt große Textinhalte, behält aber Metadaten.
        
        Args:
            sessions: Die ursprüngliche Sessions-Liste
            
        Returns:
            List[SessionData]: Die optimierte Sessions-Liste
        """
        optimized_sessions: List[SessionData] = []
        
        for session in sessions:
            # Input-Daten bleiben unverändert
            session_input = session.input
            
            # Output-Daten optimieren
            # Erstelle ein neues SessionOutput-Objekt mit reduzierten Daten
            optimized_output = SessionOutput(
                input_data=session_input,
                target_dir=session.output.target_dir,
                web_text="",  # Entferne den Web-Text
                video_transcript="",  # Entferne das Transkript
                markdown_file=session.output.markdown_file,
                markdown_content="",  # Entferne den Markdown-Inhalt
                video_file=session.output.video_file,
                attachments_url=session.output.attachments_url,
                attachments=session.output.attachments,
                structured_data=session.output.structured_data
            )
            
            # Erstelle ein neues SessionData-Objekt mit den optimierten Daten
            optimized_sessions.append(SessionData(input=session_input, output=optimized_output))
        
        return optimized_sessions
    
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die Track-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Indizes für häufige Suchfelder
            index_fields = [
                ("track_name", 1),
                ("template", 1),
                ("target_language", 1),
                ("processed_at", 1),
                ("event", 1)
            ]
            
            # Indizes erstellen, wenn sie noch nicht existieren
            for field, direction in index_fields:
                index_name = f"{field}_{direction}"
                if index_name not in index_info:
                    collection.create_index([(field, direction)])
                    self.logger.debug(f"{field}-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")

    def serialize_for_cache(self, result: TrackProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das TrackProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das TrackProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "processed_at": datetime.now().isoformat(),
            "track_name": result.track_name,
            "template": result.template,
            "target_language": result.target_language,
            "sessions_count": len(result.sessions),
            "metadata": {
                "event": result.metadata.get("event", ""),
                "track": result.metadata.get("track", ""),
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

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> TrackProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein TrackProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            TrackProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        
        # Validiere und konvertiere die Daten
        track_name = str(safe_get(result_data, "track_name", ""))  # type: ignore
        template = str(safe_get(result_data, "template", ""))  # type: ignore
        target_language = str(safe_get(result_data, "target_language", ""))  # type: ignore
        summary = str(safe_get(result_data, "summary", ""))  # type: ignore
        
        # Explizite Typ-Definitionen für Dictionaries
        metadata_dict: Dict[str, Any] = safe_get(result_data, "metadata", {})  # type: ignore
        structured_data_dict: Dict[str, Any] = safe_get(result_data, "structured_data", {})  # type: ignore
        
        # Sessions rekonstruieren
        sessions: List[SessionData] = []
        for session_dict in result_data.get("sessions", []):  # type: ignore
            if isinstance(session_dict, dict):
                try:
                    # Input-Daten extrahieren und validieren
                    input_dict = session_dict.get("input", {})  # type: ignore
                    session_input = SessionInput(
                        event=str(input_dict.get("event", "")),  # type: ignore
                        session=str(input_dict.get("session", "")),  # type: ignore
                        url=str(input_dict.get("url", "")),  # type: ignore
                        filename=str(input_dict.get("filename", "")),  # type: ignore
                        track=str(input_dict.get("track", "")),  # type: ignore
                        day=str(input_dict.get("day", "")) if input_dict.get("day") else None,  # type: ignore
                        starttime=str(input_dict.get("starttime", "")) if input_dict.get("starttime") else None,  # type: ignore
                        endtime=str(input_dict.get("endtime", "")) if input_dict.get("endtime") else None,  # type: ignore
                        speakers=list(input_dict.get("speakers", [])),  # type: ignore
                        video_url=str(input_dict.get("video_url", "")) if input_dict.get("video_url") else None,  # type: ignore
                        attachments_url=str(input_dict.get("attachments_url", "")) if input_dict.get("attachments_url") else None,  # type: ignore
                        source_language=str(input_dict.get("source_language", "en")),  # type: ignore
                        target_language=str(input_dict.get("target_language", "de")),  # type: ignore
                        target=str(input_dict.get("target", "")) if input_dict.get("target") else None,  # type: ignore
                        template=str(input_dict.get("template", "Session"))  # type: ignore
                    )
                    
                    # Output-Daten extrahieren und validieren
                    output_dict = session_dict.get("output", {})  # type: ignore
                    session_output = SessionOutput(
                        input_data=session_input,
                        target_dir=str(output_dict.get("target_dir", "")),  # type: ignore
                        web_text=str(output_dict.get("web_text", "")),  # type: ignore
                        video_transcript=str(output_dict.get("video_transcript", "")),  # type: ignore
                        attachments_text=str(output_dict.get("attachments_text", "")),  # type: ignore
                        markdown_file=str(output_dict.get("markdown_file", "")),  # type: ignore
                        markdown_content=str(output_dict.get("markdown_content", "")),  # type: ignore
                        video_file=str(output_dict.get("video_file", "")) if output_dict.get("video_file") else None,  # type: ignore
                        attachments_url=str(output_dict.get("attachments_url", "")) if output_dict.get("attachments_url") else None,  # type: ignore
                        attachments=list(output_dict.get("attachments", [])),  # type: ignore
                        structured_data=dict(output_dict.get("structured_data", {}))  # type: ignore
                    )
                    
                    sessions.append(SessionData(input=session_input, output=session_output))
                    
                except Exception as e:
                    self.logger.warning(f"Fehler beim Deserialisieren einer Session: {str(e)}")
                    continue
        
        process_id = str(safe_get(result_data, "process_id", "")) if safe_get(result_data, "process_id", None) else None  # type: ignore
        
        return TrackProcessingResult(
            track_name=track_name,
            template=template,
            target_language=target_language,
            summary=summary,
            metadata=metadata_dict,
            structured_data=structured_data_dict,
            sessions=sessions,
            process_id=process_id
        )