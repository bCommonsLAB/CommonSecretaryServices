"""
API-Routen für den Track-Prozessor.
"""
# type: ignore
import logging
import traceback
from typing import Dict, Any, Union, List, Optional

# Typ-Ignorierung für Flask-RESTx
from flask import request
from flask_restx import Namespace, Resource, fields  # type: ignore[import]

from src.core.config import Config
from src.core.exceptions import ProcessingError, ValidationError
from src.core.models.track import TrackResponse
from src.core.resource_tracking import ResourceCalculator
from src.processors.track_processor import TrackProcessor
from src.utils.logger import get_logger

# Logger erstellen
logger = get_logger(processor_name="track_api", process_id="track_api")

# Resource Calculator initialisieren
resource_calculator = ResourceCalculator()

# Namespace erstellen
track_ns = Namespace('tracks', description='Endpunkte zur Verarbeitung von Event-Tracks')

# API-Modelle definieren
track_request_model = track_ns.model('TrackRequest', {
    'track_name': fields.String(required=True, description='Name des Tracks'),
    'template': fields.String(required=False, default='track-eco-social-summary', description='Name des Templates für die Zusammenfassung'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache für die Zusammenfassung'),
    'useCache': fields.Boolean(required=False, default=False, description='Ob der Cache verwendet werden soll')
})

# Response-Modelle definieren
request_info_model = track_ns.model('RequestInfo', {
    'processor': fields.String(description='Name des Prozessors'),
    'timestamp': fields.String(description='Zeitstempel der Anfrage'),
    'parameters': fields.Raw(description='Anfrageparameter')
})

process_info_model = track_ns.model('ProcessInfo', {
    'id': fields.String(description='Eindeutige Prozess-ID'),
    'main_processor': fields.String(description='Hauptprozessor'),
    'sub_processors': fields.List(fields.String, description='Unterprozessoren'),
    'started': fields.String(description='Startzeitpunkt'),
    'completed': fields.String(description='Endzeitpunkt'),
    'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
    'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
})

error_info_model = track_ns.model('ErrorInfo', {
    'code': fields.String(description='Fehlercode'),
    'message': fields.String(description='Fehlermeldung'),
    'details': fields.Raw(description='Detaillierte Fehlerinformationen')
})

track_input_model = track_ns.model('TrackInput', {
    'track_name': fields.String(description='Name des Tracks'),
    'template': fields.String(description='Name des Templates für die Zusammenfassung'),
    'target_language': fields.String(description='Zielsprache für die Zusammenfassung')
})

track_output_model = track_ns.model('TrackOutput', {
    'summary': fields.String(description='Generierte Zusammenfassung'),
    'metadata': fields.Raw(description='Metadaten zur Zusammenfassung'),
    'structured_data': fields.Raw(description='Strukturierte Daten aus der Zusammenfassung')
})

event_data_model = track_ns.model('EventData', {
    'input': fields.Raw(description='Event-Eingabedaten'),
    'output': fields.Raw(description='Event-Ausgabedaten')
})

track_data_model = track_ns.model('TrackData', {
    'input': fields.Nested(track_input_model),
    'output': fields.Nested(track_output_model),
    'events': fields.List(fields.Nested(event_data_model)),
    'event_count': fields.Integer(description='Anzahl der Events'),
    'query': fields.String(description='Der an das LLM gesendete Text'),
    'context': fields.Raw(description='Der an das LLM gesendete Kontext')
})

track_response_model = track_ns.model('TrackResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(request_info_model),
    'process': fields.Nested(process_info_model),
    'data': fields.Nested(track_data_model),
    'error': fields.Nested(error_info_model)
})


@track_ns.route('/<string:track_name>/summary')
class TrackSummaryEndpoint(Resource):
    """Endpoint für die Erstellung von Track-Zusammenfassungen."""
    
    @track_ns.doc(
        description='Erstellt eine Zusammenfassung für einen Track.',
        params={
            'track_name': 'Name des Tracks',
            'template': 'Name des Templates für die Zusammenfassung',
            'target_language': 'Zielsprache für die Zusammenfassung',
            'useCache': 'Ob der Cache verwendet werden soll (default: false)'
        }
    )
    @track_ns.response(200, 'Erfolg', track_response_model)
    @track_ns.response(400, 'Fehler bei der Verarbeitung', track_response_model)
    def post(self, track_name: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Erstellt eine Zusammenfassung für einen Track.
        
        Args:
            track_name: Name des Tracks
            
        Returns:
            Union[Dict[str, Any], tuple[Dict[str, Any], int]]: Die Zusammenfassung des Tracks oder eine Fehlermeldung
        """
        try:
            # Request-Daten parsen - versuche zuerst JSON, dann Query-Parameter
            data = {}
            try:
                json_data = request.get_json(silent=True)
                if json_data:
                    data = json_data
            except Exception:
                pass  # Ignoriere Fehler beim JSON-Parsing
            
            # Parameter extrahieren - zuerst aus JSON, dann aus Query-Parametern
            template = data.get('template', request.args.get('template', 'track-eco-social-summary'))
            target_language = data.get('target_language', request.args.get('target_language', 'de'))
            
            # useCache-Parameter extrahieren (Standard: False)
            use_cache_str = data.get('useCache', request.args.get('useCache', 'false'))
            # Konvertiere String zu Boolean
            use_cache = use_cache_str.lower() == 'true' if isinstance(use_cache_str, str) else bool(use_cache_str)
            
            # Prozessor initialisieren
            processor = TrackProcessor(resource_calculator)
            
            # Track-Zusammenfassung erstellen (asynchron)
            import asyncio
            try:
                # Versuche, den bestehenden Event-Loop zu verwenden
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Wenn der Loop bereits läuft, erstelle einen neuen
                    response = asyncio.run(processor.create_track_summary(
                        track_name=track_name,
                        template=template,
                        target_language=target_language,
                        use_cache=use_cache
                    ))
                else:
                    # Verwende den bestehenden Loop
                    response = loop.run_until_complete(processor.create_track_summary(
                        track_name=track_name,
                        template=template,
                        target_language=target_language,
                        use_cache=use_cache
                    ))
            except RuntimeError:
                # Fallback, wenn kein Event-Loop verfügbar ist
                response: TrackResponse = asyncio.run(processor.create_track_summary(
                    track_name=track_name,
                    template=template,
                    target_language=target_language,
                    use_cache=use_cache
                ))
            
            # Response in Dictionary umwandeln
            return response.to_dict()
            
        except (ValidationError, ProcessingError) as e:
            # Bei bekannten Fehlern 400 zurückgeben
            logger.warning(f"Fehler bei der Track-Verarbeitung: {e}")
            
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
                'Unerwarteter Fehler bei der Track-Verarbeitung',
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