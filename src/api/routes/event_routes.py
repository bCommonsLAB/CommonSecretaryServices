"""
Event-Prozessor API-Routen.
Enthält alle Endpoints zur Verarbeitung von Event-Informationen und zugehörigen Medien.
"""
from flask import request
from flask_restx import Model, Namespace, OrderedModel, Resource, fields  # type: ignore
from typing import Dict, Any, Union, Optional, TypeVar, cast, List
import traceback
import asyncio
import uuid

from src.processors.event_processor import EventProcessor
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker, PerformanceTracker

from src.core.models.event import EventResponse
from src.core.models.notion import NotionResponse
from utils.logger import ProcessingLogger

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="event-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
event_ns = Namespace('event', description='Event-Verarbeitungs-Operationen')  # type: ignore

# Typ-Alias für die model-Methode
ModelType = TypeVar('ModelType', bound=Union[Model, OrderedModel])

# Definiere Modelle für die API-Dokumentation
# Input-Modelle
event_input = cast(ModelType, event_ns.model('EventInput', {  # type: ignore
    'event': fields.String(required=True, description='Name der Veranstaltung'),
    'session': fields.String(required=True, description='Name der Session'),
    'url': fields.String(required=True, description='URL zur Event-Seite'),
    'filename': fields.String(required=True, description='Zieldateiname für die Markdown-Datei'),
    'track': fields.String(required=True, description='Track/Kategorie der Session'),
    'day': fields.String(required=False, description='Veranstaltungstag im Format YYYY-MM-DD'),
    'starttime': fields.String(required=False, description='Startzeit im Format HH:MM'),
    'endtime': fields.String(required=False, description='Endzeit im Format HH:MM'),
    'speakers': fields.List(fields.String, required=False, description='Liste der Vortragenden'),
    'video_url': fields.String(required=False, description='URL zum Video'),
    'attachments_url': fields.String(required=False, description='URL zu Anhängen'),
    'source_language': fields.String(required=False, default='en', description='Quellsprache'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache')
}))

# Error-Modell
error_model = cast(ModelType, event_ns.model('Error', {  # type: ignore
    'error': fields.String(description='Fehlermeldung')
}))

# Response-Modelle
event_response_model = cast(ModelType, event_ns.model('EventResponse', {  # type: ignore
    'status': fields.String(required=True, description='Status der Anfrage'),
    'request': fields.Raw(required=True, description='Anfrageinformationen'),
    'process': fields.Raw(required=True, description='Prozessinformationen'),
    'data': fields.Raw(required=False, description='Ergebnisdaten'),
    'error': fields.Raw(required=False, description='Fehlerinformationen')
}))

notion_request_model = cast(ModelType, event_ns.model('NotionRequest', {  # type: ignore
    'blocks': fields.List(fields.Raw(description='Notion Block Struktur'))
}))

# Verwende type: ignore für die verschachtelten Modelle
notion_response_model = cast(ModelType, event_ns.model('NotionResponse', {  # type: ignore
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(cast(ModelType, event_ns.model('NotionRequestInfo', {  # type: ignore
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    }))),
    'process': fields.Nested(cast(ModelType, event_ns.model('NotionProcessInfo', {  # type: ignore
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    }))),
    'data': fields.Nested(cast(ModelType, event_ns.model('NotionData', {  # type: ignore
        'input': fields.List(fields.Raw(description='Notion Blocks')),
        'output': fields.Nested(cast(ModelType, event_ns.model('Newsfeed', {  # type: ignore
            'id': fields.String(description='Eindeutige Newsfeed-ID (parent_id des ersten Blocks)'),
            'title_DE': fields.String(description='Deutscher Titel'),
            'intro_DE': fields.String(description='Deutsche Einleitung'),
            'title_IT': fields.String(description='Italienischer Titel'),
            'intro_IT': fields.String(description='Italienische Einleitung'),
            'image': fields.String(description='Bild-URL'),
            'content_DE': fields.String(description='Deutscher Inhalt'),
            'content_IT': fields.String(description='Italienischer Inhalt')
        })))
    }))),
    'error': fields.Nested(cast(ModelType, event_ns.model('NotionError', {  # type: ignore
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    })))
}))

# Helper-Funktion zum Abrufen des Event-Processors
def get_event_processor(process_id: Optional[str] = None) -> EventProcessor:
    """Get or create event processor instance with process ID"""
    return EventProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

# Helper-Funktion für die Fehlerbehandlung
def handle_processing_error(error: Exception) -> tuple[Dict[str, Any], int]:
    """Standardisierte Fehlerbehandlung für Verarbeitungsfehler"""
    if isinstance(error, ProcessingError):
        return {
            'status': 'error',
            'error': {
                'code': 'PROCESSING_ERROR',
                'message': str(error),
                'details': getattr(error, 'details', {})
            }
        }, 400
    else:
        logger.error("Verarbeitungsfehler",
                    error=error,
                    error_type=type(error).__name__,
                    stack_trace=traceback.format_exc())
        return {
            'status': 'error',
            'error': {
                'code': type(error).__name__,
                'message': str(error),
                'details': {
                    'error_type': type(error).__name__,
                    'traceback': traceback.format_exc()
                }
            }
        }, 400

# Endpunkte für Event-Verarbeitung

# 1. Reguläre Event-Verarbeitung
@event_ns.route('/process')  # type: ignore
class EventProcessEndpoint(Resource):
    @event_ns.expect(event_input)  # type: ignore
    @event_ns.doc(description='Verarbeitet ein Event mit allen zugehörigen Medien')  # type: ignore
    @event_ns.response(200, 'Erfolg', event_response_model)  # type: ignore
    @event_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet ein Event mit allen zugehörigen Medien"""
        process_id = str(uuid.uuid4())
        tracker: Optional[PerformanceTracker] = get_performance_tracker() or get_performance_tracker(process_id)
        event_processor: EventProcessor = get_event_processor(process_id)
        
        # Setze Performance-Tracker-Informationen
        if tracker:
            tracker.set_processor_name("event")
        
        try:
            data = request.get_json()
            if not data:
                raise ProcessingError("Keine Daten erhalten")
                
            # Extrahiere Parameter
            event = data.get('event')
            session = data.get('session')
            url = data.get('url')
            filename = data.get('filename')
            track = data.get('track')
            day = data.get('day')
            starttime = data.get('starttime')
            endtime = data.get('endtime')
            speakers = data.get('speakers', [])
            video_url = data.get('video_url')
            attachments_url = data.get('attachments_url')
            source_language = data.get('source_language', 'en')
            target_language = data.get('target_language', 'de')
            
            # Validiere Pflichtfelder
            if not all([event, session, url, filename, track]):
                raise ProcessingError("Pflichtfelder fehlen: event, session, url, filename, track")
            
            # Verarbeite das Event
            result: EventResponse = asyncio.run(event_processor.process_event(
                event=event,
                session=session,
                url=url,
                filename=filename,
                track=track,
                day=day,
                starttime=starttime,
                endtime=endtime,
                speakers=speakers,
                video_url=video_url,
                attachments_url=attachments_url,
                source_language=source_language,
                target_language=target_language
            ))
            
            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker and hasattr(tracker, 'eval_result'):
                tracker.eval_result(result)
            
            return result.to_dict()
            
        except ValueError as ve:
            logger.error("Validierungsfehler",
                        error=ve,
                        error_type="ValidationError",
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': 'ValidationError',
                    'message': str(ve),
                    'details': {}
                }
            }, 400
        except Exception as e:
            logger.error("Event-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {
                        'error_type': type(e).__name__,
                        'traceback': traceback.format_exc()
                    }
                }
            }, 500
        finally:
            if event_processor and event_processor.logger:
                event_processor.logger.info("Event-Verarbeitung beendet")

# Batch-Events können jetzt über die neue Job-Verwaltung verarbeitet werden
# Der Endpunkt /process-batch wurde entfernt, da redundant mit der neuen Batch-Verarbeitung
# Der Endpunkt /process-batch-async wurde entfernt, da redundant mit der neuen asynchronen Batch-Verarbeitung

# 2. Asynchrone Event-Verarbeitung
@event_ns.route('/process-async')  # type: ignore
class AsyncEventProcessEndpoint(Resource):
    @event_ns.doc(description='Verarbeitet ein Event asynchron und sendet einen Webhook-Callback nach Abschluss')  # type: ignore
    @event_ns.response(200, 'Erfolg', event_response_model)  # type: ignore
    @event_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet ein Event asynchron und sendet einen Webhook-Callback nach Abschluss"""
        # Hier wird die bestehende Implementierung hinzugefügt
        # Platzhalter für die zukünftige Implementierung
        return {
            "status": "success",
            "message": "Async-Event-API-Struktur vorbereitet, Implementierung steht noch aus"
        }

# Der Endpunkt /process-batch-async wurde entfernt, da redundant mit der neuen asynchronen Batch-Verarbeitung
# Der Endpunkt /scrape wurde entfernt, da nicht aktiv genutzt und redundant mit /process

# 3. Notion-Block-Verarbeitung
@event_ns.route('/notion')  # type: ignore
class NotionEndpoint(Resource):
    @event_ns.expect(notion_request_model)  # type: ignore
    @event_ns.doc(description='Verarbeitet Notion Blocks und erstellt einen mehrsprachigen Newsfeed-Eintrag')  # type: ignore
    @event_ns.response(200, 'Erfolg', notion_response_model)  # type: ignore
    @event_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet Notion Blocks und erstellt einen mehrsprachigen Newsfeed-Eintrag"""
        
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            try:
                # Parse Request
                data = request.get_json()
                if not data or 'blocks' not in data:
                    return {'error': 'Keine Blocks gefunden'}, 400
                
                blocks_raw = data['blocks']
                if not isinstance(blocks_raw, list):
                    return {'error': 'Blocks müssen als Liste übergeben werden'}, 400
                
                # Cast blocks_raw zu korrekt typisierter Liste von Dicts
                blocks: List[Dict[str, Any]] = blocks_raw
                
                # Verarbeite Blocks
                processor: EventProcessor = get_event_processor()
                result: NotionResponse = await processor.process_notion_blocks(blocks)
                
                return result.to_dict()
                
            except Exception as e:
                return handle_processing_error(e)
        
        return asyncio.run(process_request())

# Neue MongoDB-basierte Endpoints werden in einer separaten Datei implementiert:
# - src/api/routes/event_job_routes.py für Event-Jobs
# - src/api/routes/batch_routes.py für Batch-Operationen 