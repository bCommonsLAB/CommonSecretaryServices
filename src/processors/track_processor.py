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
from src.core.models.event import EventData, EventInput, EventOutput
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
            
            # Events
            events_list: List[EventData] = []
            for event_dict in data_dict.get('events', []):
                event_input_dict = event_dict.get('input', {})
                event_input = EventInput(
                    event=event_input_dict.get('event', ''),
                    session=event_input_dict.get('session', ''),
                    url=event_input_dict.get('url', ''),
                    filename=event_input_dict.get('filename', ''),
                    track=event_input_dict.get('track', ''),
                    day=event_input_dict.get('day'),
                    starttime=event_input_dict.get('starttime'),
                    endtime=event_input_dict.get('endtime'),
                    speakers=event_input_dict.get('speakers', []),
                    video_url=event_input_dict.get('video_url'),
                    attachments_url=event_input_dict.get('attachments_url'),
                    source_language=event_input_dict.get('source_language', 'en'),
                    target_language=event_input_dict.get('target_language', 'de')
                )
                
                event_output_dict = event_dict.get('output', {})
                event_output = EventOutput(
                    web_text=event_output_dict.get('web_text', ''),
                    video_transcript=event_output_dict.get('video_transcript', ''),
                    context=event_output_dict.get('context', {}),
                    markdown_file=event_output_dict.get('markdown_file', ''),
                    markdown_content=event_output_dict.get('markdown_content', ''),
                    video_file=event_output_dict.get('video_file'),
                    attachments_url=event_output_dict.get('attachments_url'),
                    attachments=event_output_dict.get('attachments', []),
                    metadata=event_output_dict.get('metadata', {})
                )
                
                events_list.append(EventData(input=event_input, output=event_output))
            
            track_data = TrackData(
                input=track_input,
                output=track_output,
                events=events_list,
                event_count=len(events_list),
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
    Erstellt eine Zusammenfassung für einen Track basierend auf den zugehörigen Events.
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
            
            # Basis-Verzeichnis für Events
            app_config = Config()
            self.base_dir = Path(app_config.get('events', {}).get('base_dir', './events'))
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
        self.event_jobs: Collection[Dict[str, Any]] = self.db.event_jobs
        
        self.logger.debug("MongoDB-Verbindung initialisiert",
                        uri=mongo_uri,
                        database=db_name)
    
    async def get_track_events(self, track_name: str) -> List[EventData]:
        """
        Holt alle Events eines Tracks aus der Datenbank.
        
        Args:
            track_name: Name des Tracks
            
        Returns:
            List[EventData]: Liste aller Event-Daten für den Track
        """
        self.logger.info(f"Hole Events für Track: {track_name}")
        
        # Events aus der Datenbank holen
        # Sortiere nach completed_at absteigend (neueste zuerst)
        event_docs = list(self.event_jobs.find(
            {"parameters.track": track_name, "status": "completed"}
        ).sort("completed_at", -1))
        
        if not event_docs:
            self.logger.warning(f"Keine Events für Track '{track_name}' gefunden")
            return []
        
        # Event-Dokumente in EventData-Objekte umwandeln
        events: List[EventData] = []
        processed_job_names: set[str] = set()  # Set zum Speichern bereits verarbeiteter job_names
        
        for doc in event_docs:
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
                
                # EventInput-Objekt erstellen
                event_input = EventInput(
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
                
                # EventOutput-Objekt erstellen
                event_output = EventOutput(
                    web_text=results.get('web_text', ''),
                    video_transcript=results.get('video_transcript', ''),
                    context=results.get('context', {}),
                    markdown_file=results.get('markdown_file', ''),
                    markdown_content=results.get('markdown_content', ''),
                    video_file=results.get('video_file'),
                    attachments_url=results.get('attachments_url'),
                    attachments=results.get('assets', []),
                    metadata=results.get('metadata', {})
                )
                
                # EventData aus EventInput und EventOutput erstellen
                event = EventData(
                    input=event_input,
                    output=event_output
                )
                events.append(event)
            except Exception as e:
                self.logger.error(f"Fehler beim Konvertieren eines Event-Dokuments: {str(e)}")
                continue
        
        self.logger.info(f"{len(events)} Events für Track '{track_name}' gefunden")
        return events
    
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
            
            # Events holen
            events: List[EventData] = await self.get_track_events(track_name)
            
            if not events:
                raise ValidationError(f"Keine Events für Track '{track_name}' gefunden")
            
            # Event-Name aus dem ersten Event extrahieren
            event_name = events[0].input.event if events else "Unknown Event"
            
            # Markdown-Inhalte der Events zusammenführen
            all_markdown = self._merge_event_markdowns(events)
            
            # Kontext aus allen Events erstellen
            context = self._create_context_from_events(events)
            
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
                "events_count": len(events),
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
            
            # Optimierte Events-Liste erstellen (ohne große Textinhalte)
            optimized_events = self._create_optimized_events(events)
            
            track_data = TrackData(
                input=track_input,
                output=track_output,
                events=optimized_events,
                event_count=len(events),
                query=all_markdown,
                context=context
            )
            
            # Response erstellen
            response: TrackResponse = ResponseFactory.create_response(
                processor_name="track",
                result=track_data,
                request_info=request_info,
                response_class=TrackResponse,
                llm_info=llm_info
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
                error=error_info
            )
    
    def _merge_event_markdowns(self, events: List[EventData]) -> str:
        """
        Führt die Markdown-Inhalte aller Events zu einem einzigen Markdown-String zusammen.
        
        Args:
            events (List[EventData]): Liste der Event-Daten
            
        Returns:
            str: Zusammengeführter Markdown-Inhalt
        """
        merged_content: List[str] = []
        
        for i, event in enumerate(events):
            try:
                # Markdown-Inhalt aus dem Event extrahieren
                event_markdown = event.output.markdown_content or ""
                
                # Transkription entfernen (nur die Variante "\n## Transkription\n")
                transkription_header = "\n## Transkription\n"
                original_length = len(event_markdown)
                
                if transkription_header in event_markdown:
                    parts = event_markdown.split(transkription_header)
                    # Nur den Teil vor der Transkription behalten
                    event_markdown = parts[0].strip()
                    self.logger.debug(f"Transkription aus Event '{event.input.session}' entfernt. Größenreduktion: {original_length - len(event_markdown)} Zeichen")
                
                # Zum zusammengeführten Inhalt hinzufügen (nur den Markdown-Inhalt)
                # Füge Trenner hinzu, außer beim letzten Event
                if i < len(events) - 1:
                    merged_content.append(event_markdown + "\n\n\n---\n\n\n")
                else:
                    merged_content.append(event_markdown)
                
            except Exception as e:
                self.logger.warning(f"Fehler beim Extrahieren von Markdown aus Event: {str(e)}")
                continue
        
        return "\n".join(merged_content)
    
    def _create_context_from_events(self, events: List[EventData]) -> Dict[str, Any]:
        """
        Erstellt einen Kontext aus den Event-Daten für die Template-Verarbeitung.
        
        Args:
            events (List[EventData]): Liste der Event-Daten
            
        Returns:
            Dict[str, Any]: Kontext für die Template-Verarbeitung
        """
        context: Dict[str, Any] = {
            "events": []
        }
        
        for event in events:
            event_context: Dict[str, Any] = {
                "title": event.input.session,
                "filename": event.input.filename,
                "obsidian_link": f"[{event.input.session}]({event.input.filename})",
                "track": event.input.track,
                "url": event.input.url,
                "date": event.input.day or "",
                "speakers": event.input.speakers or []
            }
            
            # Metadaten hinzufügen, falls vorhanden
            if event.output.metadata:
                event_context.update(event.output.metadata)
            
            context["events"].append(event_context)
        
        # Allgemeine Track-Informationen
        if events:
            context["track_name"] = events[0].input.track
            context["event_name"] = events[0].input.event
        
        return context
    
    def _create_optimized_events(self, events: List[EventData]) -> List[EventData]:
        """
        Erstellt eine optimierte Liste von Events, die weniger Speicherplatz benötigt.
        Entfernt große Textinhalte wie Transkripte und Web-Text.
        
        Args:
            events: Liste der vollständigen Event-Daten
            
        Returns:
            List[EventData]: Liste der optimierten Event-Daten
        """
        optimized_events: List[EventData] = []
        
        for event in events:
            # Input-Daten beibehalten
            event_input = event.input
            
            # Output-Daten optimieren
            # Erstelle ein neues EventOutput-Objekt mit reduzierten Daten
            optimized_output = EventOutput(
                # Behalte nur die wichtigsten Metadaten
                web_text="",  # Entferne den Web-Text
                video_transcript="",  # Entferne das Transkript
                context=self._optimize_context(event.output.context),  # Optimiere den Kontext
                markdown_file=event.output.markdown_file,
                markdown_content="",  # Entferne den Markdown-Inhalt
                video_file=event.output.video_file,
                attachments_url=event.output.attachments_url,
                attachments=event.output.attachments,
                metadata=event.output.metadata
            )
            
            # Erstelle ein neues EventData-Objekt mit den optimierten Daten
            optimized_event = EventData(
                input=event_input,
                output=optimized_output
            )
            
            optimized_events.append(optimized_event)
        
        return optimized_events
    
    def _optimize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Optimiert den Kontext eines Events, indem große Textinhalte entfernt werden.
        
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