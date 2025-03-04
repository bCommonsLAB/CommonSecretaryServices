"""
Allgemeine API-Routen.
Enthält grundlegende Endpoints wie Home und Beispieldateien.
"""
from flask import Response, send_file
from flask_restx import Namespace, Resource  # type: ignore
from typing import Dict, Any, Union, TypeVar, Callable, Type
import os
import traceback
import mimetypes
from pathlib import Path
import sys

from src.utils.logger import get_logger
from utils.logger import ProcessingLogger

# Typvariable für Dekoratoren
T = TypeVar('T')

# Typ-Definitionen für flask_restx
RouteDecorator = Callable[[Type[Resource]], Type[Resource]]
DocDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]
ResponseDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="common-api")

# Erstelle Namespace
common_ns = Namespace('common', description='Allgemeine Operationen')

# Home-Endpoint
@common_ns.route('/')  # type: ignore
class HomeEndpoint(Resource):
    @common_ns.doc(description='API Willkommensseite')  # type: ignore
    def get(self) -> Dict[str, str]:
        """API Willkommensseite"""
        return {'message': 'Welcome to the Processing Service API!'}

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