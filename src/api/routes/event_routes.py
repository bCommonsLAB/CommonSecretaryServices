"""
API-Routen für den Event-Prozessor.
"""
# type: ignore

import traceback
from typing import Dict, Any, Union, cast
import uuid

# Typ-Ignorierung für Flask-RESTx
from flask import request
from flask_restx import Namespace, Resource, fields, Model, OrderedModel  # type: ignore[import]

from src.core.exceptions import ProcessingError, ValidationError
from src.core.models.event import EventResponse
from src.core.resource_tracking import ResourceCalculator
from src.processors.event_processor import EventProcessor
from src.utils.logger import get_logger
from src.utils.logger import ProcessingLogger

# Logger erstellen
logger: ProcessingLogger = get_logger(processor_name="event_api", process_id="event_api")

# Resource Calculator initialisieren
resource_calculator = ResourceCalculator()

# Namespace erstellen
event_ns = Namespace('events', description='Endpunkte zur Verarbeitung von Events')

# API-Modelle definieren
event_request_model: Model = cast(Model, event_ns.model('EventRequest', {  # type: ignore
    'event_name': fields.String(required=True, description='Name des Events'),
    'template': fields.String(required=False, default='event-eco-social-summary', description='Name des Templates für die Zusammenfassung'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache für die Zusammenfassung'),
    'useCache': fields.Boolean(required=False, default=False, description='Ob der Cache verwendet werden soll')
}))

# Response-Modelle definieren
request_info_model: Model = cast(Model, event_ns.model('RequestInfo', {  # type: ignore
    'processor': fields.String(description='Name des Prozessors'),
    'timestamp': fields.String(description='Zeitstempel der Anfrage'),
    'parameters': fields.Raw(description='Anfrageparameter')
}))

process_info_model: Model = cast(Model, event_ns.model('ProcessInfo', {  # type: ignore
    'id': fields.String(description='Eindeutige Prozess-ID'),
    'main_processor': fields.String(description='Hauptprozessor'),
    'sub_processors': fields.List(fields.String, description='Unterprozessoren'),
    'started': fields.String(description='Startzeitpunkt'),
    'completed': fields.String(description='Endzeitpunkt'),
    'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
    'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
}))

error_info_model: Model = cast(Model, event_ns.model('ErrorInfo', {  # type: ignore
    'code': fields.String(description='Fehlercode'),
    'message': fields.String(description='Fehlermeldung'),
    'details': fields.Raw(description='Detaillierte Fehlerinformationen')
}))

event_input_model: Model = cast(Model, event_ns.model('EventInput', {  # type: ignore
    'event_name': fields.String(description='Name des Events'),
    'template': fields.String(description='Name des Templates für die Zusammenfassung'),
    'target_language': fields.String(description='Zielsprache für die Zusammenfassung')
}))

event_output_model: Model = cast(Model, event_ns.model('EventOutput', {  # type: ignore
    'summary': fields.String(description='Generierte Zusammenfassung'),
    'metadata': fields.Raw(description='Metadaten zur Zusammenfassung'),
    'structured_data': fields.Raw(description='Strukturierte Daten aus der Zusammenfassung')
}))

track_data_model: Model = cast(Model, event_ns.model('TrackData', {  # type: ignore
    'input': fields.Raw(description='Track-Eingabedaten'),
    'output': fields.Raw(description='Track-Ausgabedaten'),
    'sessions': fields.List(fields.Raw(), description='Sessiondaten'),
    'session_count': fields.Integer(description='Anzahl der Sessions'),
    'query': fields.String(description='Abfrage'),
    'context': fields.Raw(description='Kontext')
}))

event_data_model: Model = cast(Model, event_ns.model('EventData', {  # type: ignore
    'input': fields.Nested(event_input_model),
    'output': fields.Nested(event_output_model),
    'tracks': fields.List(fields.Nested(track_data_model)),
    'track_count': fields.Integer(description='Anzahl der Tracks'),
    'query': fields.String(description='Der an das LLM gesendete Text'),
    'context': fields.Raw(description='Der an das LLM gesendete Kontext')
}))

event_response_model: Model = cast(Model, event_ns.model('EventResponse', {  # type: ignore
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(request_info_model),
    'process': fields.Nested(process_info_model),
    'data': fields.Nested(event_data_model),
    'error': fields.Nested(error_info_model)
}))


@event_ns.route('/<string:event_name>/summary')  # type: ignore
class EventSummaryEndpoint(Resource):
    """Endpoint für die Erstellung von Event-Zusammenfassungen."""
    
    @event_ns.doc(  # type: ignore
        description='Erstellt eine Zusammenfassung für ein Event.',
        params={
            'event_name': 'Name des Events',
            'template': 'Name des Templates für die Zusammenfassung',
            'target_language': 'Zielsprache für die Zusammenfassung',
            'useCache': 'Ob der Cache verwendet werden soll (default: false)'
        }
    )
    @event_ns.response(200, 'Erfolg', event_response_model)  # type: ignore
    @event_ns.response(400, 'Fehler bei der Verarbeitung', event_response_model)  # type: ignore
    def post(self, event_name: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Erstellt eine Zusammenfassung für ein Event.
        
        Args:
            event_name: Name des Events
            
        Returns:
            Union[Dict[str, Any], tuple[Dict[str, Any], int]]: Die Zusammenfassung des Events oder eine Fehlermeldung
        """
        try:
            # Request-Daten parsen - versuche zuerst JSON, dann Query-Parameter
            data: Dict[str, Any] = {}
            try:
                json_data = request.get_json(silent=True)
                if json_data:
                    data = json_data
            except Exception:
                pass  # Ignoriere Fehler beim JSON-Parsing
            
            # Parameter extrahieren - zuerst aus JSON, dann aus Query-Parametern
            template_default = 'Event_eco_social'
            template: str = str(data.get('template', request.args.get('template', template_default)))
            
            target_lang_default = 'de'
            target_language: str = str(data.get('target_language', request.args.get('target_language', target_lang_default)))
            
            # useCache-Parameter extrahieren (Standard: False)
            use_cache_str: Any = data.get('useCache', request.args.get('useCache', 'false'))
            # Konvertiere String zu Boolean
            use_cache: bool = use_cache_str.lower() == 'true' if isinstance(use_cache_str, str) else bool(use_cache_str)
            
            # Process-ID generieren für Tracking
            process_id = str(uuid.uuid4())
            
            # Prozessor initialisieren
            processor = EventProcessor(
                resource_calculator=resource_calculator,
                process_id=process_id
            )
            
            # Event-Zusammenfassung erstellen (asynchron)
            import asyncio
            try:
                # Versuche, den bestehenden Event-Loop zu verwenden
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Wenn der Loop bereits läuft, erstelle einen neuen
                    event_response = asyncio.run(processor.create_event_summary(
                        event_name=event_name,
                        template=template,
                        target_language=target_language,
                        use_cache=use_cache
                    ))
                else:
                    # Verwende den bestehenden Loop
                    event_response = loop.run_until_complete(processor.create_event_summary(
                        event_name=event_name,
                        template=template,
                        target_language=target_language,
                        use_cache=use_cache
                    ))
            except RuntimeError:
                # Fallback, wenn kein Event-Loop verfügbar ist
                event_response: EventResponse = asyncio.run(processor.create_event_summary(
                    event_name=event_name,
                    template=template,
                    target_language=target_language,
                    use_cache=use_cache
                ))
            
            # Response in Dictionary umwandeln
            return event_response.to_dict()
            
        except (ValidationError, ProcessingError) as e:
            # Bei bekannten Fehlern 400 zurückgeben
            logger.warning(f"Fehler bei der Event-Verarbeitung: {e}")
            
            return {
                'status': 'error',
                'error': {
                    'code': e.__class__.__name__,
                    'message': str(e),
                    'details': {}
                }
            }, 400
            
        except Exception as e:
            # Bei unbekannten Fehlern 500 zurückgeben
            logger.error(
                'Unerwarteter Fehler bei der Event-Verarbeitung',
                error=e,
                traceback=traceback.format_exc()
            )
            
            return {
                'status': 'error',
                'error': {
                    'code': 'InternalServerError',
                    'message': f'Unerwarteter Fehler bei der Verarbeitung: {str(e)}',
                    'details': {}
                }
            }, 500 