"""
@fileoverview Common API Routes - Flask-RESTX endpoints for general operations

@description
General API routes. Contains basic endpoints like home and example files.
This file defines REST API endpoints for general operations with Flask-RESTX,
including Notion integration and health checks.

Main endpoints:
- GET /api/common/home: Home endpoint
- POST /api/common/notion: Notion block processing
- GET /api/common/health: Health check for common service

Features:
- JSON-based request/response
- Notion block processing (currently not fully implemented)
- Health check endpoints
- Swagger UI documentation

@module api.routes.common_routes

@exports
- common_ns: Namespace - Flask-RESTX namespace for common endpoints

@usedIn
- src.api.routes.__init__: Registers common_ns namespace

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- Internal: src.processors.session_processor - SessionProcessor (for Notion processing)
"""
from flask import Response, send_file, request
from flask_restx import Namespace, Resource, fields, Model  # type: ignore
from typing import Dict, Any, Union, TypeVar, Callable, Type, Optional, cast
import os
import traceback
import mimetypes
from pathlib import Path
import sys
import asyncio

from src.processors.session_processor import SessionProcessor
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.logger import ProcessingLogger

# Typvariable für Dekoratoren
T = TypeVar('T')

# Typ-Definitionen für flask_restx
RouteDecorator = Callable[[Type[Resource]], Type[Resource]]
DocDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]
ResponseDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]
ModelType = TypeVar('ModelType', bound=Union[Model, Model])

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="common-api")

# Initialisiere Resource Calculator für Notion-Verarbeitung
resource_calculator = ResourceCalculator()

# Erstelle Namespace
common_ns = Namespace('common', description='Allgemeine Operationen')

# Models für Notion-Verarbeitung
notion_request_model = cast(ModelType, common_ns.model('NotionRequest', {  # type: ignore
    'blocks': fields.List(fields.Raw(description='Notion Block Struktur'))
}))

# Verwende type: ignore für die verschachtelten Modelle
notion_response_model = cast(ModelType, common_ns.model('NotionResponse', {  # type: ignore
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(cast(ModelType, common_ns.model('NotionRequestInfo', {  # type: ignore
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    }))),
    'process': fields.Nested(cast(ModelType, common_ns.model('NotionProcessInfo', {  # type: ignore
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    }))),
    'data': fields.Nested(cast(ModelType, common_ns.model('NotionData', {  # type: ignore
        'input': fields.List(fields.Raw(description='Notion Blocks')),
        'output': fields.Nested(cast(ModelType, common_ns.model('Newsfeed', {  # type: ignore
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
    'error': fields.Nested(cast(ModelType, common_ns.model('NotionError', {  # type: ignore
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    })))
}))

# Error-Modell
error_model = cast(ModelType, common_ns.model('Error', {  # type: ignore
    'error': fields.String(description='Fehlermeldung')
}))

# Modell für den Obsidian-Export hinzufügen
obsidian_export_model = cast(ModelType, common_ns.model('ObsidianExportRequest', {  # type: ignore
    'source_dir': fields.String(required=True, description='Quellverzeichnis des Events', default="sessions"),
    'target_dir': fields.String(required=True, description='Zielverzeichnis für den Obsidian-Export', default="obsidian"),
    'event_name': fields.String(required=True, description='Name des Events', default="FOSDEM 2025"),
    'languages': fields.List(fields.String, description='Zu exportierende Sprachen', default=['de', 'en']),
    'export_mode': fields.String(description='Export-Modus (copy, regenerate, hybrid)', default='copy', enum=['copy', 'regenerate', 'hybrid']),
    'preserve_changes': fields.Boolean(description='Änderungen beibehalten', default=True),
    'force_overwrite': fields.Boolean(description='Überschreiben erzwingen', default=False),
    'include_assets': fields.Boolean(description='Assets einschließen', default=True)
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

# Home-Endpoint
@common_ns.route('/')  # type: ignore
class HomeEndpoint(Resource):
    @common_ns.doc(description='API Willkommensseite')  # type: ignore
    def get(self) -> Dict[str, str]:
        """API Willkommensseite"""
        return {'message': 'Welcome to the Processing Service API!'}

# Notion-Block-Verarbeitung
@common_ns.route('/notion')  # type: ignore
class NotionEndpoint(Resource):
    @common_ns.expect(notion_request_model)  # type: ignore
    @common_ns.doc(description='Verarbeitet Notion Blocks und erstellt einen mehrsprachigen Newsfeed-Eintrag')  # type: ignore
    @common_ns.response(200, 'Erfolg', notion_response_model)  # type: ignore
    @common_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
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
                
                # TODO: Die Notion-Block-Verarbeitung muss im SessionProcessor implementiert werden
                # Diese Funktionalität fehlt aktuell nach der Umbenennung von EventProcessor zu SessionProcessor
                return {'error': 'NotionBlock-Verarbeitung nicht implementiert im SessionProcessor'}, 501
                
                # Alte Implementierung mit EventProcessor:
                # processor: SessionProcessor = get_session_processor()
                # result: NotionResponse = await processor.process_notion_blocks(blocks)
                # return result.to_dict()
                
            except Exception as e:
                return handle_processing_error(e)
        
        return asyncio.run(process_request())

# Samples-Endpoints
@common_ns.route('/samples')  # type: ignore
class SamplesEndpoint(Resource):
    @common_ns.doc(description='Listet alle verfügbaren Beispieldateien auf')  # type: ignore
    def get(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Gibt eine Liste aller verfügbaren Beispieldateien zurück."""
        try:
            # Samples-Verzeichnis - Korrigierter Pfad
            # Wir gehen vom aktuellen Verzeichnis aus, nicht vom Modul-Verzeichnis
            samples_dir: Path = Path(os.getcwd()) / 'tests' / 'samples'
            
            # Debug-Logging
            print(f"Suche Beispieldateien in: {samples_dir}", file=sys.stderr)
            print(f"Verzeichnis existiert: {samples_dir.exists()}", file=sys.stderr)
            print(f"Verzeichnis ist Verzeichnis: {samples_dir.is_dir()}", file=sys.stderr)
            
            # Dateien auflisten
            files: list[dict[str, Any]] = []
            if samples_dir.exists() and samples_dir.is_dir():
                print(f"Dateien im Verzeichnis: {list(samples_dir.glob('*'))}", file=sys.stderr)
                for file_path in samples_dir.glob('*'):
                    if file_path.is_file():
                        print(f"Gefundene Datei: {file_path.name}", file=sys.stderr)
                        files.append({
                            'name': file_path.name,
                            'size': file_path.stat().st_size,
                            'type': file_path.suffix.lstrip('.'),
                            'url': f'/api/samples/{file_path.name}'
                        })
            else:
                print(f"Samples-Verzeichnis nicht gefunden: {samples_dir}", file=sys.stderr)
            
            return {
                'status': 'success',
                'data': {
                    'files': files
                }
            }
        except Exception as e:
            print(f"Fehler beim Auflisten der Beispieldateien: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return {
                'status': 'error',
                'error': {
                    'code': 'SAMPLE_LIST_ERROR',
                    'message': str(e)
                }
            }, 500

@common_ns.route('/samples/<string:filename>')  # type: ignore
class SampleFileEndpoint(Resource):
    @common_ns.doc(description='Lädt eine bestimmte Beispieldatei herunter')  # type: ignore
    @common_ns.response(200, 'Erfolg')  # type: ignore
    @common_ns.response(404, 'Datei nicht gefunden')  # type: ignore
    def get(self, filename: str) -> Any:
        """Lädt eine bestimmte Beispieldatei herunter."""
        try:
            # Samples-Verzeichnis - Korrigierter Pfad
            samples_dir: Path = Path(os.getcwd()) / 'tests' / 'samples'
            
            # Debug-Logging
            print(f"Suche Datei {filename} in: {samples_dir}", file=sys.stderr)
            
            # Prüfe ob Datei existiert und im samples Verzeichnis liegt
            file_path: Path = samples_dir / filename
            print(f"Vollständiger Dateipfad: {file_path}", file=sys.stderr)
            print(f"Datei existiert: {file_path.exists()}", file=sys.stderr)
            print(f"Datei ist Datei: {file_path.is_file()}", file=sys.stderr)
            
            if not file_path.is_file() or samples_dir not in file_path.parents:
                print(f"Datei nicht gefunden: {file_path}", file=sys.stderr)
                return {
                    'status': 'error',
                    'error': {
                        'code': 'FILE_NOT_FOUND',
                        'message': f'Datei {filename} nicht gefunden'
                    }
                }, 404
            
            # Bestimme den MIME-Type
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                # Fallback für Videos
                if filename.lower().endswith(('.mp4', '.avi', '.mov', '.wmv')):
                    mime_type = 'video/mp4'
                else:
                    mime_type = 'application/octet-stream'
            
            print(f"Sende Datei {filename} mit MIME-Type {mime_type}", file=sys.stderr)
            
            # Sende Datei mit angepassten Headern
            response: Response = send_file(
                file_path,
                mimetype=mime_type,
                as_attachment=False,  # Wichtig für Streaming
                download_name=filename
            )
            
            # Cache-Control Header setzen
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            # Content-Disposition für Streaming anpassen
            response.headers['Content-Disposition'] = 'inline'
            
            # Zusätzliche Header für Video-Streaming
            if mime_type and mime_type.startswith('video/'):
                response.headers['Accept-Ranges'] = 'bytes'
                response.headers['X-Content-Type-Options'] = 'nosniff'
            
            return response
            
        except Exception as e:
            print(f"Fehler beim Herunterladen der Beispieldatei: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return {
                'status': 'error',
                'error': {
                    'code': 'SAMPLE_DOWNLOAD_ERROR',
                    'message': str(e)
                }
            }, 500

