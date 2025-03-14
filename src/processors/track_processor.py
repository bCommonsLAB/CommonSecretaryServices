"""
Track-Prozessor für die Verarbeitung von Event-Tracks.
"""
from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

from src.core.config import Config
from src.core.exceptions import ValidationError
from src.core.models.base import ErrorInfo, ProcessInfo, RequestInfo
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.response_factory import ResponseFactory
from src.core.models.track import TrackInput, TrackOutput, TrackData, TrackResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.session import SessionData, SessionInput, SessionOutput
from src.core.resource_tracking import ResourceCalculator
from src.utils.processor_cache import ProcessorCache
from .base_processor import BaseProcessor
from .transformer_processor import TransformerProcessor

class CacheableTrackResponse(TrackResponse):
    """
    Eine cacheable Version der TrackResponse, die das CacheableResult-Protokoll implementiert.
    """
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheableTrackResponse':
        """
        Erstellt eine CacheableTrackResponse aus einem Dictionary.
        
        Args:
            data: Dictionary mit den Daten
            
        Returns:
            CacheableTrackResponse: Die erstellte Response
        """
        # Erstelle RequestInfo
        request_data = data.get('request', {})
        request = RequestInfo(
            processor=request_data.get('processor', ''),
            timestamp=request_data.get('timestamp', ''),
            parameters=request_data.get('parameters', {})
        )
        
        # Erstelle ProcessInfo
        process_data = data.get('process', {})
        process = ProcessInfo(
            id=process_data.get('id', ''),
            main_processor=process_data.get('main_processor', ''),
            started=process_data.get('started', ''),
            sub_processors=process_data.get('sub_processors', []),
            completed=process_data.get('completed'),
            duration=process_data.get('duration')
        )
        
        # LLM-Info hinzufügen, falls vorhanden
        llm_info_data = process_data.get('llm_info')
        if llm_info_data:
            # Erstelle LLM-Requests
            llm_requests: List[LLMRequest] = []
            if 'requests' in llm_info_data:
                for req_data in llm_info_data.get('requests', []):
                    llm_requests.append(LLMRequest(
                        model=req_data.get('model', ''),
                        purpose=req_data.get('purpose', ''),
                        tokens=req_data.get('tokens', 1),
                        duration=req_data.get('duration', 0)
                    ))
            
            # Erstelle LLM-Info mit Requests
            llm_info = LLMInfo(
                model=llm_info_data.get('model', ''),
                purpose=llm_info_data.get('purpose', ''),
                requests=llm_requests
            )
            process.llm_info = llm_info
        
        # Erstelle TrackData, falls vorhanden
        track_data = None
        if 'data' in data and data['data']:
            data_dict = data['data']
            
            # Input
            input_dict = data_dict.get('input', {})
            track_input = TrackInput(
                track_name=input_dict.get('track_name', ''),
                template=input_dict.get('template', ''),
                target_language=input_dict.get('target_language', '')
            )
            
            # Output
            output_dict = data_dict.get('output', {})
            track_output = TrackOutput(
                summary=output_dict.get('summary', ''),
                metadata=output_dict.get('metadata', {}),
                structured_data=output_dict.get('structured_data', {})
            )
            
            # Sessions (vorher Events)
            sessions_list: List[SessionData] = []
            for session_dict in data_dict.get('sessions', []):
                session_input_dict = session_dict.get('input', {})
                session_input = SessionInput(
                    event=session_input_dict.get('event', ''),
                    session=session_input_dict.get('session', ''),
                    url=session_input_dict.get('url', ''),
                    filename=session_input_dict.get('filename', ''),
                    track=session_input_dict.get('track', ''),
                    day=session_input_dict.get('day'),
                    starttime=session_input_dict.get('starttime'),
                    endtime=session_input_dict.get('endtime'),
                    speakers=session_input_dict.get('speakers', []),
                    video_url=session_input_dict.get('video_url'),
                    attachments_url=session_input_dict.get('attachments_url'),
                    source_language=session_input_dict.get('source_language', 'en'),
                    target_language=session_input_dict.get('target_language', 'de')
                )
                
                session_output_dict = session_dict.get('output', {})
                session_output = SessionOutput(
                    web_text=session_output_dict.get('web_text', ''),
                    video_transcript=session_output_dict.get('video_transcript', ''),
                    context=session_output_dict.get('context', {}),
                    markdown_file=session_output_dict.get('markdown_file', ''),
                    markdown_content=session_output_dict.get('markdown_content', ''),
                    video_file=session_output_dict.get('video_file'),
                    attachments_url=session_output_dict.get('attachments_url'),
                    attachments=session_output_dict.get('attachments', []),
                    attachments_text=session_output_dict.get('attachments_text', '')
                )
                
                sessions_list.append(SessionData(input=session_input, output=session_output))
            
            track_data = TrackData(
                input=track_input,
                output=track_output,
                sessions=sessions_list,
                session_count=len(sessions_list),
                query=data_dict.get('query', ''),
                context=data_dict.get('context', {})
            )
        
        # Erstelle Error, falls vorhanden
        error = None
        if 'error' in data and data['error']:
            error_dict = data['error']
            error = ErrorInfo(
                code=error_dict.get('code', ''),
                message=error_dict.get('message', ''),
                details=error_dict.get('details', {})
            )
        
        # Erstelle die Response
        response = cls.__new__(cls)
        object.__setattr__(response, 'request', request)
        object.__setattr__(response, 'process', process)
        object.__setattr__(response, 'status', data.get('status', 'success'))
        object.__setattr__(response, 'error', error)
        object.__setattr__(response, 'data', track_data)
        
        return response


class TrackProcessor(BaseProcessor):
    """
    Prozessor für die Verarbeitung von Event-Tracks.
    Erstellt eine Zusammenfassung für einen Track basierend auf den zugehörigen Sessions.
    """
    
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
            self.transformer_processor = TransformerProcessor(resource_calculator, process_id)
            
            # Basis-Verzeichnis für Sessions (vorher Events)
            app_config = Config()
            self.base_dir = Path(app_config.get('sessions', {}).get('base_dir', './sessions'))
            self.base_dir.mkdir(parents=True, exist_ok=True)
            
            # Initialisiere Cache
            self.cache = ProcessorCache[CacheableTrackResponse]("track")
            
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
                    web_text=results.get('web_text', ''),
                    video_transcript=results.get('video_transcript', ''),
                    context=results.get('context', {}),
                    markdown_file=results.get('markdown_file', ''),
                    markdown_content=results.get('markdown_content', ''),
                    video_file=results.get('video_file'),
                    attachments_url=results.get('attachments_url'),
                    attachments=results.get('assets', []),
                    attachments_text=results.get('attachments_text', '')
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
    ) -> Optional[Tuple[TrackResponse, Dict[str, Any]]]:
        """
        Prüft, ob ein Cache-Eintrag für die Track-Verarbeitung existiert.
        
        Args:
            cache_key: Der Cache-Schlüssel
            
        Returns:
            Optional[Tuple[TrackResponse, Dict[str, Any]]]: 
                Das geladene Ergebnis und Metadaten oder None
        """
        # Prüfe Cache
        cache_result = self.cache.load_cache_with_key(
            cache_key=cache_key,
            result_class=CacheableTrackResponse
        )
        
        if cache_result:
            self.logger.info("Cache-Hit für Track-Verarbeitung", 
                           cache_key=cache_key)
            return cache_result
            
        return None
    
    def _save_to_cache(
        self,
        cache_key: str,
        response: TrackResponse,
        track_name: str,
        template: str,
        target_language: str
    ) -> None:
        """
        Speichert ein Verarbeitungsergebnis im Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            response: Die zu speichernde Response
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
        
        # Konvertiere zu CacheableTrackResponse
        cacheable_response = cast(CacheableTrackResponse, response)
        
        # Speichere im Cache
        self.cache.save_cache_with_key(
            cache_key=cache_key,
            result=cacheable_response,
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
        try:
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
                    response, _ = cache_result
                    self.logger.info("Track-Zusammenfassung aus Cache geladen", 
                                   track_name=track_name)
                    return response
            
            # LLM-Tracking initialisieren
            llm_info = LLMInfo(model="gpt-4", purpose="track-summary")
            
            # Request-Info erstellen
            request_info = {
                "track_name": track_name,
                "template": template,
                "target_language": target_language
            }
            
            # Sessions holen (vorher Events)
            sessions: List[SessionData] = await self.get_track_sessions(track_name)
            
            if not sessions:
                raise ValidationError(f"Keine Sessions für Track '{track_name}' gefunden")
            
            # Event-Name aus der ersten Session extrahieren
            event_name = sessions[0].input.event if sessions else "Unknown Event"
            
            # Markdown-Inhalte der Sessions zusammenführen
            all_markdown = self._merge_session_markdowns(sessions)
            
            # Kontext aus allen Sessions erstellen
            context = self._create_context_from_sessions(sessions)
            
            # Template-Transformation durchführen
            transform_result: TransformerResponse = self.transformer_processor.transformByTemplate(
                source_text=all_markdown,
                source_language=target_language,  # Wir nehmen an, dass die Markdown-Dateien bereits in Zielsprache sind
                target_language=target_language,
                template=template,
                context=context
            )
            
            # LLM-Informationen hinzufügen
            if transform_result.process and transform_result.process.llm_info:
                llm_info.add_request(transform_result.process.llm_info.requests)
            
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
            
            # Optimierte Sessions-Liste erstellen (ohne große Textinhalte)
            optimized_sessions = self._create_optimized_sessions(sessions)
            
            track_data = TrackData(
                input=track_input,
                output=track_output,
                sessions=optimized_sessions,
                session_count=len(sessions),
                query=all_markdown,
                context=context
            )
            
            # Response erstellen
            response: TrackResponse = ResponseFactory.create_response(
                processor_name="track",
                result=track_data,
                request_info=request_info,
                response_class=TrackResponse,
                llm_info=llm_info,
                from_cache=False
            )
            
            # Im Cache immer speichern, unabhängig vom Parameter use_cache
            self._save_to_cache(
                cache_key=cache_key,
                response=response,
                track_name=track_name,
                template=template,
                target_language=target_language
            )
            
            return response
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Track-Verarbeitung: {str(e)}")
            
            # Fehler-Response erstellen
            error_info = ErrorInfo(
                code="track_processing_error",
                message=f"Fehler bei der Verarbeitung des Tracks: {str(e)}",
                details={"track_name": track_name}
            )
            
            return ResponseFactory.create_response(
                processor_name="track",
                result=None,
                request_info={
                    "track_name": track_name,
                    "template": template,
                    "target_language": target_language
                },
                response_class=TrackResponse,
                error=error_info,
                from_cache=False
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
        Erstellt eine optimierte Liste von Sessions, die weniger Speicherplatz benötigt.
        Entfernt große Textinhalte wie Transkripte und Web-Text.
        
        Args:
            sessions: Liste der vollständigen Session-Daten
            
        Returns:
            List[SessionData]: Liste der optimierten Session-Daten
        """
        optimized_sessions: List[SessionData] = []
        
        for session in sessions:
            # Input-Daten beibehalten
            session_input = session.input
            
            # Output-Daten optimieren
            # Erstelle ein neues SessionOutput-Objekt mit reduzierten Daten
            optimized_output = SessionOutput(
                # Behalte nur die wichtigsten Metadaten
                web_text="",  # Entferne den Web-Text
                video_transcript="",  # Entferne das Transkript
                attachments_text="",
                context=self._optimize_context(session.output.context),  # Optimiere den Kontext
                markdown_file=session.output.markdown_file,
                markdown_content="",  # Entferne den Markdown-Inhalt
                video_file=session.output.video_file,
                attachments_url=session.output.attachments_url,
                attachments=session.output.attachments
            )
            
            # Erstelle ein neues SessionData-Objekt mit den optimierten Daten
            optimized_session = SessionData(
                input=session_input,
                output=optimized_output
            )
            
            optimized_sessions.append(optimized_session)
        
        return optimized_sessions
    
    def _optimize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Optimiert den Kontext einer Session, indem große Textinhalte entfernt werden.
        
        Args:
            context: Der vollständige Kontext
            
        Returns:
            Dict[str, Any]: Der optimierte Kontext
        """
        if not context:
            return {}
        
        # Erstelle eine Kopie des Kontexts
        optimized_context = context.copy()
        
        # Entferne große Textinhalte
        if 'web_text' in optimized_context:
            optimized_context['web_text'] = ""
        
        if 'video_transcript' in optimized_context:
            optimized_context['video_transcript'] = ""
        
        if 'attachment_text' in optimized_context:
            optimized_context['attachment_text'] = ""
        
        return optimized_context 