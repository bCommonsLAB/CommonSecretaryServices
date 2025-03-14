"""
Session-Prozessor API-Routen.
Enthält alle Endpoints zur Verarbeitung von Session-Informationen und zugehörigen Medien.
"""
from flask import request
from flask_restx import Model, Namespace, OrderedModel, Resource, fields  # type: ignore
from typing import Dict, Any, Union, Optional, TypeVar, cast
import traceback
import asyncio
import uuid

from src.processors.session_processor import SessionProcessor
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker, PerformanceTracker

from src.core.models.session import SessionResponse
from utils.logger import ProcessingLogger

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="session-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
session_ns = Namespace(
    name='session',
    description='Session-Verarbeitungs-Operationen',
)

# Typ-Alias für die model-Methode
ModelType = TypeVar('ModelType', bound=Union[Model, OrderedModel])

# Definiere Modelle für die API-Dokumentation
# Input-Modelle
session_input = cast(ModelType, session_ns.model('SessionInput', {  # type: ignore
    'event': fields.String(required=True, description='Name der Veranstaltung'),
    'session': fields.String(required=True, description='Name der Session'),
    'url': fields.String(required=True, description='URL zur Session-Seite'),
    'filename': fields.String(required=True, description='Zieldateiname für die Markdown-Datei'),
    'track': fields.String(required=True, description='Track/Kategorie der Session'),
    'day': fields.String(required=False, description='Veranstaltungstag im Format YYYY-MM-DD'),
    'starttime': fields.String(required=False, description='Startzeit im Format HH:MM'),
    'endtime': fields.String(required=False, description='Endzeit im Format HH:MM'),
    'speakers': fields.List(fields.String, required=False, description='Liste der Vortragenden'),
    'video_url': fields.String(required=False, description='URL zum Video'),
    'attachments_url': fields.String(required=False, description='URL zu Anhängen'),
    'source_language': fields.String(required=False, default='en', description='Quellsprache'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache'),
    'template': fields.String(required=False, default='Session', description='Name des Templates für die Markdown-Generierung')
}))

# Error-Modell
error_model = cast(ModelType, session_ns.model('Error', {  # type: ignore
    'error': fields.String(description='Fehlermeldung')
}))

# Response-Modelle
session_response_model = cast(ModelType, session_ns.model('SessionResponse', {  # type: ignore
    'status': fields.String(required=True, description='Status der Anfrage'),
    'request': fields.Raw(required=True, description='Anfrageinformationen'),
    'process': fields.Raw(required=True, description='Prozessinformationen'),
    'data': fields.Raw(required=False, description='Ergebnisdaten'),
    'error': fields.Raw(required=False, description='Fehlerinformationen')
}))

# Helper-Funktion zum Abrufen des Session-Processors
def get_session_processor(process_id: Optional[str] = None) -> SessionProcessor:
    """Gibt einen Session-Processor mit dem angegebenen Process-ID zurück oder erstellt einen neuen."""
    return SessionProcessor(resource_calculator, process_id)

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

# Endpunkte für Session-Verarbeitung

# 1. Reguläre Session-Verarbeitung
@session_ns.route('/process')  # type: ignore
class SessionProcessEndpoint(Resource):
    @session_ns.expect(session_input)  # type: ignore
    @session_ns.doc(description='Verarbeitet eine Session mit allen zugehörigen Medien')  # type: ignore
    @session_ns.response(200, 'Erfolg', session_response_model)  # type: ignore
    @session_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine Session mit allen zugehörigen Medien"""
        process_id = str(uuid.uuid4())
        tracker: Optional[PerformanceTracker] = get_performance_tracker() or get_performance_tracker(process_id)
        session_processor: SessionProcessor = get_session_processor(process_id)
        
        # Setze Performance-Tracker-Informationen
        if tracker:
            tracker.set_processor_name("session")
        
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
            template = data.get('template', 'Session')
            use_cache = data.get('use_cache', True)
            
            # Validiere Pflichtfelder
            if not all([event, session, url, filename, track]):
                raise ProcessingError("Pflichtfelder fehlen: event, session, url, filename, track")
            
            # Verarbeite die Session
            result: SessionResponse = asyncio.run(session_processor.process_session(
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
                target_language=target_language,
                template=template,
                use_cache=use_cache
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
            logger.error("Session-Verarbeitungsfehler",
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
            if session_processor and session_processor.logger:
                session_processor.logger.info("Session-Verarbeitung beendet")

# Batch-Sessions können jetzt über die neue Job-Verwaltung verarbeitet werden
# Der Endpunkt /process-batch wurde entfernt, da redundant mit der neuen Batch-Verarbeitung
# Der Endpunkt /process-batch-async wurde entfernt, da redundant mit der neuen asynchronen Batch-Verarbeitung

# 2. Asynchrone Session-Verarbeitung
@session_ns.route('/process-async')  # type: ignore
class AsyncSessionProcessEndpoint(Resource):
    @session_ns.doc(description='Verarbeitet eine Session asynchron und sendet einen Webhook-Callback nach Abschluss')  # type: ignore
    @session_ns.response(200, 'Erfolg', session_response_model)  # type: ignore
    @session_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine Session asynchron und sendet einen Webhook-Callback nach Abschluss"""
        # Hier wird die bestehende Implementierung hinzugefügt
        # Platzhalter für die zukünftige Implementierung
        return {
            "status": "success",
            "message": "Async-Session-API-Struktur vorbereitet, Implementierung steht noch aus"
        }

# Neue MongoDB-basierte Endpoints werden in einer separaten Datei implementiert:
# - src/api/routes/session_job_routes.py für Session-Jobs
# - src/api/routes/batch_routes.py für Batch-Operationen 