import os
import json
from typing import Dict, List, Optional, Any, cast, TypeVar, Type
from pathlib import Path
from bson import ObjectId

from core.models.story import (
    StoryProcessorInput, StoryProcessorOutput, StoryData, 
    StoryResponse, StoryProcessingResult
)
from processors.cacheable_processor import CacheableProcessor
from processors.transformer_processor import TransformerProcessor, TransformerResponse
from core.resource_tracking import ResourceCalculator
from core.mongodb.connection import get_mongodb_database

from core.models.base import ProcessInfo, ErrorInfo, BaseResponse
from core.mongodb.story_repository import StoryRepository, TopicDict, TargetGroupDict, SessionDict

T = TypeVar('T')
R = TypeVar('R', bound=BaseResponse)

class StoryProcessor(CacheableProcessor[StoryProcessingResult]):  # type: ignore
    """
    StoryProcessor für die Erstellung thematischer Geschichten aus Sessions.
    
    Funktionalität:
    -------------
    - Abrufen von Session-Daten zum angegebenen Thema
    - Gruppierung und Analyse der Session-Inhalte
    - Generierung einer thematischen Zusammenfassung
    - Anwendung von Templates für verschiedene Zielgruppen
    - Erstellung einer mehrsprachigen Markdown-Ausgabe
    - Speicherung und Verwaltung der generierten Geschichten
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "story_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None) -> None:
        """
        Initialisiert den StoryProcessor.
        
        Args:
            resource_calculator: Berechnet die Ressourcennutzung während der Verarbeitung
            process_id: Optionale eindeutige ID für diesen Verarbeitungsprozess
            parent_process_info: Optionale Prozessinformationen des übergeordneten Prozessors
        """
        # Basis-Initialisierung mit dem CacheableProcessor
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Sicherstellen, dass die Verbindung existiert
        if not hasattr(self, 'connection'):
            self.connection = get_mongodb_database()
        
        # Repository für den Zugriff auf Themen, Zielgruppen und Sessions
        self.story_repository = StoryRepository(self.connection)
        
        # Konfiguration für den Force-Reprocess-Modus
        self.force_reprocess = False
        
        self.transformer_processor: TransformerProcessor = TransformerProcessor(
            resource_calculator=self.resource_calculator, 
            process_id=process_id,
            parent_process_info=self.process_info
        )

        # Verzeichnis für generierte Geschichten
        self.base_dir = Path("stories")
        if not self.base_dir.exists():
            self.base_dir.mkdir(parents=True)
            
        self.logger.debug("Story Processor initialisiert")
    
    async def process_story(self, input_data: StoryProcessorInput) -> StoryResponse:
        """
        Verarbeitet eine Story-Anfrage und generiert eine thematische Geschichte aus Sessions.
        
        Args:
            input_data: Die Eingabedaten für die Story-Verarbeitung
            
        Returns:
            Eine Story-Response mit der generierten Geschichte oder Fehlerinformationen
        """
        try:
            # Cache-Schlüssel generieren
            cache_key = self._generate_cache_key(input_data)
            
            # Prüfen, ob die Story bereits im Cache ist und Cache verwendet werden soll
            if not self.force_reprocess and input_data.use_cache:
                cache_hit, cached_result = self.get_from_cache(cache_key)
                
                if cache_hit and cached_result:
                    self.logger.info(f"Story aus Cache abgerufen: {cache_key}")
                    
                    # Cache-Ergebnis in StoryProcessingResult umwandeln
                    result = StoryProcessingResult.from_dict(cast(Dict[str, Any], cached_result))
                    
                    # Output-Daten aus dem Cache-Ergebnis erstellen
                    output = StoryProcessorOutput(
                        topic_id=result.topic_id,
                        event=result.event,
                        target_group=result.target_group,
                        markdown_files=result.markdown_files,
                        markdown_contents=result.markdown_contents,
                        session_count=len(result.session_ids),
                        metadata=result.metadata
                    )
                    
                    # Nutze die optimierte create_response-Methode der Basisklasse
                    return cast(StoryResponse, self.create_response(
                        processor_name="story",
                        result=StoryData(input=input_data, output=output),
                        request_info={
                            'topic_id': input_data.topic_id,
                            'event': input_data.event,
                            'target_group': input_data.target_group,
                            'languages': input_data.languages,
                            'detail_level': input_data.detail_level
                        },
                        response_class=cast(Type[R], StoryResponse),
                        from_cache=True,
                        cache_key=cache_key
                    ))
            
            # Bestimme, welche Methode zum Abrufen der Sessions verwendet werden soll
            # Wenn ein spezifisches data.topic angegeben ist, verwende die neue Methode
            
            session_ids = None
            topic_text: str = input_data.topic_id
            if input_data.session_ids and len(input_data.session_ids) > 0:
                # Wenn session_ids explizit angegeben sind, diese verwenden
                sessions = self.story_repository.get_sessions_by_session_ids(input_data.session_ids)
                session_ids = input_data.session_ids
            elif topic_text:
                # Wenn data.topic angegeben ist, die neue Methode verwenden
                self.logger.info(f"Verwende data.topic Filter: {topic_text}")
                sessions: List[Dict[str, Any]] = self.story_repository.get_sessions_by_data_topic(topic_text)
                session_ids = [s.get("session_id") for s in sessions if s.get("session_id")]
            else:
                # Andernfalls die ursprüngliche Methode verwenden
                self.logger.info(f"Verwende ursprünglichen Filter (topic_id, event, target_group)")
                sessions = self.story_repository.get_sessions_by_topic(
                    input_data.topic_id, 
                    input_data.event, 
                    input_data.target_group
                )
                session_ids = [s.get("_id") for s in sessions if s.get("_id")]
            
            if not session_ids:
                # Nutze die optimierte create_response-Methode mit Fehlerparameter
                error_message = 'Keine Sessions für das angegebene Thema und die Zielgruppe gefunden'
                if topic_text:
                    error_message = f'Keine Sessions für das angegebene data.topic "{topic_text}" gefunden'
                
                return cast(StoryResponse, self.create_response(
                    processor_name="story",
                    result=None,
                    request_info={
                        'topic_id': input_data.topic_id,
                        'event': input_data.event,
                        'target_group': input_data.target_group,
                        'languages': input_data.languages,
                        'detail_level': input_data.detail_level,
                        'data_topic_text': topic_text
                    },
                    response_class=cast(Type[R], StoryResponse),
                    from_cache=False,
                    cache_key="",
                    error=ErrorInfo(
                        code='NO_SESSIONS_FOUND',
                        message=error_message,
                        details={
                            'topic_id': input_data.topic_id,
                            'event': input_data.event,
                            'target_group': input_data.target_group,
                            'data_topic_text': topic_text
                        }
                    )
                ))
            
            # Thema und Zielgruppe abrufen
            topic = self.story_repository.get_topic_by_id(input_data.topic_id)
            if not topic:
                return cast(StoryResponse, self.create_response(
                    processor_name="story",
                    result=None,
                    request_info={
                        'topic_id': input_data.topic_id,
                        'event': input_data.event,
                        'target_group': input_data.target_group
                    },
                    response_class=cast(Type[R], StoryResponse),
                    from_cache=False,
                    cache_key="",
                    error=ErrorInfo(
                        code='TOPIC_NOT_FOUND',
                        message=f'Thema mit ID {input_data.topic_id} nicht gefunden',
                        details={
                            'topic_id': input_data.topic_id
                        }
                    )
                ))
            
            target_group = self.story_repository.get_target_group_by_id(input_data.target_group)
            if not target_group:
                return cast(StoryResponse, self.create_response(
                    processor_name="story",
                    result=None,
                    request_info={
                        'topic_id': input_data.topic_id,
                        'event': input_data.event,
                        'target_group': input_data.target_group
                    },
                    response_class=cast(Type[R], StoryResponse),
                    from_cache=False,
                    cache_key="",
                    error=ErrorInfo(
                        code='TARGET_GROUP_NOT_FOUND',
                        message=f'Zielgruppe mit ID {input_data.target_group} nicht gefunden',
                        details={
                            'target_group': input_data.target_group
                        }
                    )
                ))
            
            # Verzeichnisstruktur erstellen
            base_dir = f"stories/{input_data.event}_{input_data.target_group}/{input_data.topic_id}"
            os.makedirs(base_dir, exist_ok=True)
            
            # Story-Generierung für jede Sprache
            markdown_files: Dict[str, str] = {}
            markdown_contents: Dict[str, str] = {}

            for language in input_data.languages:
                
                target_dir: str = f"{input_data.event}_{input_data.target_group}/{input_data.topic_id}"

                # Story generieren
                story_content: str = await self._generate_story(
                    sessions=sessions,
                    topic=topic,
                    target_group=target_group,
                    target_dir=target_dir,
                    language=language,
                    detail_level=input_data.detail_level,
                    template=topic.get("template", "story") + "_" + language
                )
                
                # Datei speichern
                file_path = f"{base_dir}/{input_data.topic_id}_{language}.md"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(story_content)
                
                markdown_files[language] = file_path
                markdown_contents[language] = story_content
            
            # Symbolische Links zu den Sessions erstellen
            await self._create_session_links(session_ids, base_dir)
            
            # Output erstellen
            output = StoryProcessorOutput(
                topic_id=str(input_data.topic_id),
                event=str(input_data.event),
                target_group=str(input_data.target_group),
                markdown_files=markdown_files,
                markdown_contents=markdown_contents,
                session_count=len(session_ids),
                metadata={
                    "topic": {k: str(v) if isinstance(v, ObjectId) else v for k, v in topic.items()},
                    "target_group": {k: str(v) if isinstance(v, ObjectId) else v for k, v in target_group.items()},
                    "languages": input_data.languages,
                    "detail_level": input_data.detail_level
                }
            )
            
            # Ergebnis im Cache speichern
            result = StoryProcessingResult(
                topic_id=str(input_data.topic_id),
                event=str(input_data.event),
                target_group=str(input_data.target_group),
                session_ids=[str(sid) for sid in session_ids],
                markdown_files=markdown_files,
                markdown_contents=markdown_contents,
                metadata={
                    "topic": {k: str(v) if isinstance(v, ObjectId) else v for k, v in topic.items()},
                    "target_group": {k: str(v) if isinstance(v, ObjectId) else v for k, v in target_group.items()},
                    "languages": input_data.languages,
                    "detail_level": input_data.detail_level
                },
                process_id=self.process_id,
                input_data=input_data
            )
            
            # Cache speichern mit der Basis-Methode
            self.save_to_cache(cache_key, result)
            
            # Response erstellen mit der optimierten create_response-Methode
            return cast(StoryResponse, self.create_response(
                processor_name="story",
                result=StoryData(input=input_data, output=output),
                request_info={
                    'topic_id': input_data.topic_id,
                    'event': input_data.event,
                    'target_group': input_data.target_group,
                    'languages': input_data.languages,
                    'detail_level': input_data.detail_level
                },
                response_class=cast(Type[R], StoryResponse),
                from_cache=False,
                cache_key=cache_key
            ))
        except Exception as e:
            self.logger.error(f"Fehler bei der Story-Verarbeitung: {e}", exc_info=True)
            # Fehlerresponse erstellen
            return cast(StoryResponse, self.create_response(
                processor_name="story",
                result=None,
                request_info={
                    'topic_id': input_data.topic_id,
                    'event': input_data.event,
                    'target_group': input_data.target_group,
                    'languages': input_data.languages,
                    'detail_level': input_data.detail_level
                },
                response_class=cast(Type[R], StoryResponse),
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code='STORY_PROCESSING_ERROR',
                    message=str(e),
                    details={
                        'error_type': type(e).__name__
                    }
                )
            ))
    
    def _generate_cache_key(self, input_data: StoryProcessorInput) -> str:
        """
        Generiert einen Cache-Schlüssel für die Eingabedaten.
        
        Args:
            input_data: Die Eingabedaten für die Story-Verarbeitung
            
        Returns:
            Ein eindeutiger Cache-Schlüssel als String
        """
        key_parts: List[str] = [
            f"story_{input_data.event}",
            input_data.topic_id,
            input_data.target_group,
            "_".join(sorted(input_data.languages)),
            str(input_data.detail_level)
        ]
        
        if input_data.session_ids:
            key_parts.append("sessions_" + "_".join(sorted(input_data.session_ids)))
        
        if input_data.data_topic_text:
            key_parts.append(f"data_topic_{input_data.data_topic_text}")
        
        # JSON-String erstellen und generischen Cache-Key erzeugen
        key_string = json.dumps(key_parts, sort_keys=True)
        return self.generate_cache_key(key_string)
    
    async def _get_sessions(self, session_ids: List[str]) -> List[SessionDict]:
        """
        Lädt Session-Daten aus dem Cache oder der Datenbank.
        
        Args:
            session_ids: Liste von Session-IDs (können Strings oder andere Typen sein)
            
        Returns:
            Liste mit Session-Daten
        """
        sessions: List[SessionDict] = []
        
        for session_id in session_ids:
            try:
                # Sicherstellen, dass session_id ein String ist
                str_session_id = str(session_id)
                
                # Cache-Key für die Session
                session_key = f"session_{str_session_id}"
                
                # Versuch, die Session aus dem Cache zu laden
                cache_hit, session_data = self.get_from_cache(session_key)
                
                if cache_hit and session_data:
                    # Session aus dem Cache verwenden
                    sessions.append(cast(SessionDict, session_data))
                else:
                    # Versuche, die Session aus der Datenbank direkt zu laden
                    try:
                        db_session = self.story_repository.db.session_cache.find_one({"_id": str_session_id})
                        if db_session:
                            # Formatierte Session erstellen
                            title = db_session.get('data', {}).get('title', f'Session {str_session_id}')
                            content = db_session.get('data', {}).get('content', 'Keine Inhalte verfügbar')
                            topic = db_session.get('data', {}).get('topic', 'unknown')
                            
                            formatted_session: SessionDict = {
                                "session_id": str_session_id,
                                "title": title,
                                "content": {
                                    "de": content if isinstance(content, str) else str(content)
                                },
                                "metadata": {
                                    "topics": [topic],
                                    "relevance": {
                                        "general": 0.8  # Standard-Relevanz
                                    },
                                    "event": db_session.get('data', {}).get('event', 'unknown')
                                }
                            }
                            sessions.append(formatted_session)
                        else:
                            # Platzhalter erstellen, wenn Session nicht gefunden
                            sessions.append({
                                "session_id": str_session_id,
                                "title": f"Session {str_session_id}",
                                "content": {
                                    "de": "Keine Daten verfügbar"
                                },
                                "metadata": {
                                    "topics": [],
                                    "relevance": {},
                                    "event": "unknown"
                                }
                            })
                    except Exception as e:
                        self.logger.warning(f"Fehler beim Laden der Session {str_session_id} aus der Datenbank: {e}")
                        # Platzhalter erstellen, wenn ein Fehler auftritt
                        sessions.append({
                            "session_id": str_session_id,
                            "title": f"Session {str_session_id}",
                            "content": {
                                "de": "Fehler beim Laden der Daten"
                            },
                            "metadata": {
                                "topics": [],
                                "relevance": {},
                                "event": "unknown"
                            }
                        })
            except Exception as e:
                self.logger.error(f"Fehler bei der Verarbeitung von Session-ID: {session_id} - {e}")
                # Wenn session_id nicht verarbeitet werden kann, überspringen
                continue
        
        return sessions
    
    def _get_template_path(self, template_name: str, language: str) -> str:
        """
        Ermittelt den Pfad zum Template.
        
        Args:
            template_name: Name des Templates
            language: Sprachcode (z.B. 'de', 'en')
            
        Returns:
            Der Pfad zum Template
        """
        # Zuerst versuchen, ein sprachspezifisches Template zu finden
        template_path = f"templates/{template_name}_{language}.md"
        
        # Wenn nicht gefunden, Fallback auf Standardsprache (de)
        if not os.path.exists(template_path):
            template_path = f"templates/Story_{template_name}_de.md"
        
        # Wenn immer noch nicht gefunden, Fallback auf generisches Template
        if not os.path.exists(template_path):
            template_path = f"templates/{template_name}.md"
        
        return template_path
    
    async def _generate_story(
        self,
        sessions: List[SessionDict],
        topic: TopicDict,
        target_group: TargetGroupDict,
        target_dir: str,
        language: str,
        detail_level: int,
        template: str
    ) -> str:
        """
        Generiert die Story basierend auf den Session-Daten und dem Template.
        Diese Methode wird in Phase B vollständig implementiert.
        
        Args:
            session_data: Die Daten der ausgewählten Sessions
            topic: Das Thema, zu dem die Story generiert wird
            target_group: Die Zielgruppe, für die die Story generiert wird
            language: Der Sprachcode
            detail_level: Das Detaillevel der Story
            template_path: Der Pfad zum Template
            
        Returns:
            Der generierte Story-Text als Markdown
        """
        # Template-Kontext als flaches JSON-Objekt erstellen
        template_context: Dict[str, Any] = {
            # Topic-Informationen
            "topic_id": str(topic.get("topic_id", "")),
            "topic_display_name": str(topic.get("display_name", {}).get(language, topic.get("topic_id", ""))),
            "topic_description": str(topic.get("description", {}).get(language, "")),
            "topic_keywords": [str(k) for k in topic.get("keywords", [])],
            "topic_relevance": float(topic.get("relevance_threshold", 0.7)),
            "topic_template": str(topic.get("template", "default")),
            "topic_event": str(topic.get("event", "")),
            
            # Target-Group-Informationen
            "target_group_id": str(target_group.get("target_id", "")),
            "target_group_display_name": str(target_group.get("display_name", {}).get(language, target_group.get("target_id", ""))),
            "target_group_description": str(target_group.get("description", {}).get(language, "")),
            
            # Story-spezifische Informationen
            "language": language,
            "detail_level": detail_level,
        }

        session_list = "\n\n".join([
            f"## {s.get('title', 'Unbekannte Session')}\n\n{s.get('markdown_content', 'Kein Inhalt verfügbar')}"
            for s in sessions
        ])
        
        
        # Template-Transformation mit korrekten Parametern
        result: TransformerResponse = self.transformer_processor.transformByTemplate(
            text=session_list,
            template=template,
            source_language=language, 
            target_language=language,
            context=template_context,
            use_cache=False
        )
        
        if not result or not result.data:
            return "Fehler bei der Template-Transformation"
            
        content: str = result.data.text
        return content
    
    async def _create_session_links(self, session_ids: List[Any], base_dir: str) -> None:
        """
        Erstellt symbolische Links zu den Sessions im Story-Verzeichnis.
        
        Args:
            session_ids: Liste von Session-IDs (können Strings oder andere Typen sein)
            base_dir: Das Basis-Verzeichnis für die Links
        """
        # Implementieren Sie hier die Erstellung von Links zu den Sessions
        # Dies ist eine Platzhaltermethode für die Phase B
        pass
    
    def serialize_for_cache(self, result: StoryProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das Verarbeitungsergebnis für den Cache.
        
        Args:
            result: Das zu serialisierende Ergebnis
            
        Returns:
            Das serialisierte Ergebnis als Dictionary
        """
        return result.to_dict()
    
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> StoryProcessingResult:
        """
        Deserialisiert die gecachten Daten zu einem StoryProcessingResult.
        
        Args:
            cached_data: Die zu deserialisierenden Cache-Daten
            
        Returns:
            Das deserialisierte StoryProcessingResult
        """
        return StoryProcessingResult.from_dict(cached_data)
        
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezialisierte Indizes für die Story-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection, für die Indizes erstellt werden sollen
        """
        collection.create_index([("topic_id", 1), ("event", 1), ("target_group", 1)])
        collection.create_index([("event", 1)])
        collection.create_index([("topic_id", 1)]) 