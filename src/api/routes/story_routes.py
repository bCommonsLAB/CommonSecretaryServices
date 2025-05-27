"""
Story-Routen für die API.
Diese Datei definiert die Endpunkte für die Story-Generierung aus Topics in der Datenbank.
"""
from flask import request
from flask_restx import Namespace, Resource, fields  # type: ignore
import json
from typing import Any, Dict, Union, Tuple, Literal
from bson import ObjectId  # type: ignore
from datetime import datetime

from src.core.models.story import StoryProcessorInput, StoryResponse
from src.core.resource_tracking import ResourceCalculator
from src.processors.story_processor import StoryProcessor

# Erstelle einen neuen Namespace für Story-Routen
story_ns = Namespace('story', description='Story Generierung und Verwaltung')

# Benutzerdefinierter JSONEncoder für komplexe Objekte
class CustomJSONEncoder(json.JSONEncoder):
    """JSONEncoder, der Objekte mit to_dict-Methode, ObjectId und datetime korrekt serialisiert."""
    def default(self, o: Any) -> Any:
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, 'to_dict') and callable(getattr(o, 'to_dict')):
            return o.to_dict()
        return super().default(o)

# Hilfsfunktion für JSON-Serialisierung
def jsonify(data: Any) -> Dict[str, Any]:
    """Serialisiert komplexe Objekte in JSON-serialisierbare Dictionarys."""
    return json.loads(json.dumps(data, cls=CustomJSONEncoder))

# Definiere Request-Modelle für die API-Dokumentation
story_input_model = story_ns.model('StoryInput', {  # type: ignore
    'topic_id': fields.String(required=True, description='ID des Themas', example='Gemeinschaftsbildung'),
    'event': fields.String(required=True, description='Event, zu dem das Thema gehört', example='FOSDEM 2025'),
    'target_group': fields.String(required=True, description='Zielgruppe für die Story', example='ecosocial'),
    'languages': fields.List(fields.String, required=True, description='Sprachen für die Story-Generierung', example=['de']),
    'detail_level': fields.Integer(required=False, default=3, description='Detailgrad der Story (1-5)', example=3),
    'session_ids': fields.List(fields.String, required=False, description='Optionale Liste von Session-IDs', example=[]),
    'use_cache': fields.Boolean(required=False, default=False, description='Ob der Cache verwendet werden soll', example=False)
})

# Definiere Antwortmodelle für die API-Dokumentation
story_response_model = story_ns.model('StoryResponse', {  # type: ignore
    'status': fields.String(required=True, description='Status der Anfrage (success/error)'),
    'request': fields.Raw(required=True, description='Details zur Anfrage'),
    'process': fields.Raw(required=True, description='Informationen zum Verarbeitungsprozess'),
    'data': fields.Raw(required=False, description='Generierte Story-Daten'),
    'error': fields.Raw(required=False, description='Fehlerinformationen bei Misserfolg')
})

@story_ns.route('/generate')  # type: ignore
class StoryGenerationEndpoint(Resource):
    @story_ns.doc(description='Generiert eine Story aus einem Thema in der Datenbank')  # type: ignore
    @story_ns.expect(story_input_model)  # type: ignore
    @story_ns.response(200, 'Story erfolgreich generiert', story_response_model)  # type: ignore
    @story_ns.response(400, 'Ungültige Anfrage', story_response_model)  # type: ignore
    @story_ns.response(404, 'Thema oder Zielgruppe nicht gefunden', story_response_model)  # type: ignore
    @story_ns.response(500, 'Interner Serverfehler', story_response_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], Literal[400]], Tuple[Dict[str, Any], Literal[500]]]:  # type: ignore
        """
        Generiert eine Story für ein Thema aus der Datenbank.
        
        Die Story wird im Verzeichnis stories/<event>_<target_group>/<topic_id> gespeichert
        und ist auch in der Antwort als Markdown-Text enthalten.
        """
        # Initialisiere data mit einem leeren Dictionary als Sicherheits-Fallback
        data = {}
        
        try:
            # Daten aus der Anfrage extrahieren
            data = request.json
            
            # Story-Processor-Input erstellen
            input_data = StoryProcessorInput(
                topic_id=data.get('topic_id'),  # type: ignore
                event=data.get('event'),  # type: ignore
                target_group=data.get('target_group'),  # type: ignore
                languages=data.get('languages', ['de']),  # type: ignore
                detail_level=data.get('detail_level', 3),  # type: ignore
                session_ids=data.get('session_ids'),  # type: ignore
                use_cache=data.get('use_cache', False)  # type: ignore
            )
            
            # Story-Processor initialisieren und Story generieren
            resource_calculator = ResourceCalculator()
            processor = StoryProcessor(resource_calculator=resource_calculator)
            
            # Synchron aufrufen mit asyncio.run
            import asyncio
            response: StoryResponse = asyncio.run(processor.process_story(input_data))
            
            # Antwort serialisieren
            return jsonify(response)
            
        except ValueError as e:
            # Behandlung von Validierungsfehlern
            return {  # type: ignore
                'status': 'error',
                'request': {
                    'input': data  # Verwende data anstelle von request.json
                },
                'process': {},
                'error': {
                    'code': 'VALIDATION_ERROR',
                    'message': str(e),
                    'details': {}
                }
            }, 400
            
        except Exception as e:
            # Allgemeine Fehlerbehandlung
            return {
                'status': 'error',
                'request': {
                    'input': data  # Verwende data anstelle von request.json
                },
                'process': {},
                'error': {
                    'code': 'INTERNAL_ERROR',
                    'message': f'Interner Fehler bei der Story-Generierung: {str(e)}',
                    'details': {
                        'error_type': type(e).__name__
                    }
                }
            }, 500

@story_ns.route('/topics')  # type: ignore
class TopicsEndpoint(Resource):
    @story_ns.doc(description='Gibt eine Liste aller verfügbaren Topics zurück')  # type: ignore
    @story_ns.response(200, 'Liste der Topics erfolgreich abgerufen')  # type: ignore
    def get(self):
        """
        Gibt eine Liste aller verfügbaren Topics zurück.
        
        Diese können für die Story-Generierung verwendet werden.
        """
        try:
            # Story-Processor initialisieren
            resource_calculator = ResourceCalculator()
            processor = StoryProcessor(resource_calculator=resource_calculator)
            
            # Alle Topics abrufen
            topics = processor.story_repository.get_all_topics()
            
            # Antwort formatieren
            return {
                'status': 'success',
                'request': {},
                'process': {},
                'data': {
                    'topics': topics
                }
            }
            
        except Exception as e:
            # Fehlerbehandlung
            return {
                'status': 'error',
                'request': {},
                'process': {},
                'error': {
                    'code': 'TOPICS_RETRIEVAL_ERROR',
                    'message': f'Fehler beim Abrufen der Topics: {str(e)}',
                    'details': {
                        'error_type': type(e).__name__
                    }
                }
            }, 500

@story_ns.route('/target-groups')  # type: ignore
class TargetGroupsEndpoint(Resource):
    @story_ns.doc(description='Gibt eine Liste aller verfügbaren Zielgruppen zurück')  # type: ignore
    @story_ns.response(200, 'Liste der Zielgruppen erfolgreich abgerufen')  # type: ignore
    def get(self):
        """
        Gibt eine Liste aller verfügbaren Zielgruppen zurück.
        
        Diese können für die Story-Generierung verwendet werden.
        """
        try:
            # Story-Processor initialisieren
            resource_calculator = ResourceCalculator()
            processor = StoryProcessor(resource_calculator=resource_calculator)
            
            # Alle Zielgruppen abrufen
            target_groups = processor.story_repository.get_all_target_groups()
            
            # Antwort formatieren
            return {
                'status': 'success',
                'request': {},
                'process': {},
                'data': {
                    'target_groups': target_groups
                }
            }
            
        except Exception as e:
            # Fehlerbehandlung
            return {
                'status': 'error',
                'request': {},
                'process': {},
                'error': {
                    'code': 'TARGET_GROUPS_RETRIEVAL_ERROR',
                    'message': f'Fehler beim Abrufen der Zielgruppen: {str(e)}',
                    'details': {
                        'error_type': type(e).__name__
                    }
                }
            }, 500

# Ende der Datei - die duplizierte post-Methode wurde entfernt 