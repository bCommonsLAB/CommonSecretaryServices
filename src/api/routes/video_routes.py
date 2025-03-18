# type: ignore
"""
Video-Prozessor API-Routen.
Enthält alle Endpoints zur Verarbeitung von Video-Dateien und YouTube-Videos.
"""
from flask import request
from flask_restx import Model, Namespace, OrderedModel, Resource, fields
from typing import Dict, Any, Union, Optional
import traceback
import asyncio
import uuid
from werkzeug.datastructures import FileStorage
import time
from datetime import datetime
import os
from pathlib import Path

from src.processors.video_processor import VideoProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.core.models.video import VideoSource, VideoResponse
from src.core.models.youtube import YoutubeResponse
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker, PerformanceTracker

# Initialisiere Logger
logger = get_logger(process_id="video-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
video_ns = Namespace('video', description='Video-Verarbeitungs-Operationen')

# Parser für Multipart-Formulardaten (für Datei-Uploads)
video_upload_parser = video_ns.parser()
video_upload_parser.add_argument('file', location='files', type=FileStorage, required=False, help='Video-Datei zum Hochladen')
video_upload_parser.add_argument('url', location='form', type=str, required=False, help='URL des Videos (alternativ zur Datei)')
video_upload_parser.add_argument('target_language', location='form', type=str, default='de', required=False, help='Zielsprache für die Transkription')
video_upload_parser.add_argument('source_language', location='form', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
video_upload_parser.add_argument('template', location='form', type=str, required=False, help='Optional Template für die Verarbeitung')
video_upload_parser.add_argument('useCache', location='form', type=str, default='true', required=False, help='Cache verwenden (true/false)')
video_upload_parser.add_argument('force_refresh', location='form', type=str, default='false', required=False, help='Cache ignorieren und Verarbeitung erzwingen (true/false)')

# Parser für JSON-Anfragen
video_json_parser = video_ns.parser()
video_json_parser.add_argument('url', location='json', type=str, required=True, help='URL des Videos')
video_json_parser.add_argument('target_language', location='json', type=str, default='de', required=False, help='Zielsprache für die Transkription')
video_json_parser.add_argument('source_language', location='json', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
video_json_parser.add_argument('template', location='json', type=str, required=False, help='Optional Template für die Verarbeitung')
video_json_parser.add_argument('useCache', location='json', type=bool, default=True, required=False, help='Cache verwenden (default: True)')
video_json_parser.add_argument('force_refresh', location='json', type=bool, default=False, required=False, help='Cache ignorieren und Verarbeitung erzwingen (default: False)')

# Parser für YouTube-Anfragen
youtube_parser = video_ns.parser()
youtube_parser.add_argument('url', location='json', type=str, required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', help='YouTube Video URL')
youtube_parser.add_argument('source_language', location='json', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
youtube_parser.add_argument('target_language', location='json', type=str, default='de', required=False, help='Zielsprache (ISO 639-1 code)')
youtube_parser.add_argument('template', location='json', type=str, default='youtube', required=False, help='Template für die Verarbeitung')
youtube_parser.add_argument('useCache', location='json', type=bool, default=True, required=False, help='Cache verwenden (default: True)')

# Parser für YouTube-Anfragen mit Formular
youtube_form_parser = video_ns.parser()
youtube_form_parser.add_argument('url', location='form', type=str, required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', help='YouTube Video URL')
youtube_form_parser.add_argument('source_language', location='form', type=str, default='auto', required=False, help='Quellsprache (auto für automatische Erkennung)')
youtube_form_parser.add_argument('target_language', location='form', type=str, default='de', required=False, help='Zielsprache (ISO 639-1 code)')
youtube_form_parser.add_argument('template', location='form', type=str, default='youtube', required=False, help='Template für die Verarbeitung')
youtube_form_parser.add_argument('useCache', location='form', type=str, default='true', required=False, help='Cache verwenden (true/false)')

# Definiere Error-Modell, identisch zum alten Format
error_model: Model | OrderedModel = video_ns.model('Error', {
    'error': fields.String(description='Fehlermeldung')
})

# Definiere Modelle für die API-Dokumentation - IDENTISCH zur alten Version
youtube_response: Model | OrderedModel = video_ns.model('YoutubeResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(video_ns.model('YoutubeRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(video_ns.model('YoutubeProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(video_ns.model('YoutubeData', {
        'metadata': fields.Raw(description='Video Metadaten'),
        'transcription': fields.Raw(description='Transkriptionsergebnis (wenn verfügbar)')
    })),
    'error': fields.Nested(video_ns.model('YoutubeError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Explizites Modell für Video-Responses
video_response: Model | OrderedModel = video_ns.model('VideoResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(video_ns.model('VideoRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(video_ns.model('VideoProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(video_ns.model('VideoData', {
        'metadata': fields.Raw(description='Video Metadaten'),
        'transcription': fields.Raw(description='Transkriptionsergebnis (wenn verfügbar)')
    })),
    'error': fields.Nested(video_ns.model('VideoError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Model für Youtube-URLs und Parameter
youtube_input = video_ns.model('YoutubeInput', {
    'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache (ISO 639-1 code)'),
    'template': fields.String(required=False, default='youtube', description='Template für die Verarbeitung (default: youtube)'),
    'useCache': fields.Boolean(required=False, default=True, description='Cache verwenden (default: True)')
})

# Model für Video-Requests (für JSON-Anfragen)
video_request = video_ns.model('VideoRequest', {
    'url': fields.String(required=False, description='URL des Videos'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache für die Transkription'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'template': fields.String(required=False, description='Optional Template für die Verarbeitung'),
    'useCache': fields.Boolean(required=False, default=True, description='Cache verwenden (default: True)')
})

# Helper-Funktionen zum Abrufen der Prozessoren
def get_video_processor(process_id: Optional[str] = None) -> VideoProcessor:
    """Get or create video processor instance with process ID"""
    if not process_id:
        process_id = str(uuid.uuid4())
    return VideoProcessor(resource_calculator, process_id=process_id)

def get_youtube_processor(process_id: Optional[str] = None) -> YoutubeProcessor:
    """Get or create youtube processor instance with process ID"""
    if not process_id:
        process_id = str(uuid.uuid4())
    return YoutubeProcessor(resource_calculator, process_id=process_id)

# Hilfsfunktion für die YouTube-Verarbeitung
async def process_youtube(url: str, source_language: str = 'auto', target_language: str = 'de', 
                          template: str = 'youtube', use_cache: bool = True, process_id: Optional[str] = None) -> YoutubeResponse:
    """
    Verarbeitet eine YouTube-URL und extrahiert den Audio-Inhalt.
    
    Args:
        url: Die YouTube-URL
        source_language: Die Quellsprache des Videos (auto für automatische Erkennung)
        target_language: Die Zielsprache für die Transkription
        template: Das zu verwendende Template
        use_cache: Ob der Cache verwendet werden soll
        process_id: Optional eine eindeutige Prozess-ID
        
    Returns:
        YoutubeResponse mit den Verarbeitungsergebnissen
    """
    if not process_id:
        process_id = str(uuid.uuid4())
    
    youtube_processor = get_youtube_processor(process_id)
    logger.info(f"Verarbeite YouTube-URL: {url} mit Prozess-ID: {process_id}")
    
    result = await youtube_processor.process(
        url=url,
        source_language=source_language,
        target_language=target_language,
        template=template,
        use_cache=use_cache
    )
    
    return result

# Hilfsfunktion für die Video-Verarbeitung
async def process_video(source: VideoSource, binary_data: Optional[bytes] = None, source_language: str = 'auto', target_language: str = 'de',
                       template: Optional[str] = None, use_cache: bool = True, 
                       force_refresh: bool = False, process_id: Optional[str] = None) -> VideoResponse:
    """
    Verarbeitet ein Video und extrahiert den Audio-Inhalt.
    
    Args:
        source: Die VideoSource (URL oder Datei)
        binary_data: Die Binärdaten des Videos (optional)
        source_language: Die Quellsprache des Videos (auto für automatische Erkennung)
        target_language: Die Zielsprache für die Transkription
        template: Das zu verwendende Template (optional)
        use_cache: Ob der Cache verwendet werden soll
        force_refresh: Ob der Cache ignoriert und die Verarbeitung erzwungen werden soll
        process_id: Optional eine eindeutige Prozess-ID
        
    Returns:
        VideoResponse mit den Verarbeitungsergebnissen
    """
    if not process_id:
        process_id = str(uuid.uuid4())
    
    processor: VideoProcessor = get_video_processor(process_id)
    logger.info(f"Starte Video-Verarbeitung mit Prozess-ID: {process_id}")
    
    # Video verarbeiten mit den vom Benutzer angegebenen Cache-Einstellungen
    result: VideoResponse = await processor.process(
        source=source,
        binary_data=binary_data,
        target_language=target_language,
        source_language=source_language,
        template=template,
        use_cache=use_cache
    )
    
    # Wenn force_refresh aktiviert ist, sollte die Prozessorlogik dies bereits berücksichtigt haben
    # In Zukunft kann hier zusätzliche Logik für force_refresh hinzugefügt werden, wenn der Prozessor dies unterstützt
    
    return result

# YouTube-Endpunkt
@video_ns.route('/youtube')
class YoutubeEndpoint(Resource):
    @video_ns.expect(youtube_form_parser)
    @video_ns.response(200, 'Erfolg', youtube_response)
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.doc(id='process_youtube',
                 description='Verarbeitet ein Youtube-Video und extrahiert den Audio-Inhalt. Unterstützt sowohl JSON als auch Formular-Anfragen.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet ein Youtube-Video und extrahiert den Audio-Inhalt.
        
        Benötigt eine gültige YouTube-URL und unterstützt verschiedene Parameter zur Steuerung der Verarbeitung.
        Die Verarbeitung umfasst das Herunterladen des Videos, die Extraktion der Audio-Spur und die Transkription des Inhalts.
        
        Die Anfrage kann entweder als JSON oder als Formular (multipart/form-data) gesendet werden.
        """
        try:
            # Prozess-ID für die Verarbeitung
            process_id = str(uuid.uuid4())
            tracker = get_performance_tracker() or get_performance_tracker(process_id)
            
            # Parameter verarbeiten
            url = None
            source_language = 'auto'
            target_language = 'de'
            template = 'youtube'
            use_cache = True
            
            # Prüfe, ob die Anfrage als Formular oder als JSON gesendet wurde
            if request.form and 'url' in request.form:
                # Formular-Anfrage
                url = request.form.get('url')
                source_language = request.form.get('source_language', 'auto')
                target_language = request.form.get('target_language', 'de')
                template = request.form.get('template', 'youtube')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
            else:
                # JSON-Anfrage
                args = youtube_parser.parse_args()
                url = args.get('url')
                source_language = args.get('source_language', 'auto')
                target_language = args.get('target_language', 'de')
                template = args.get('template', 'youtube')
                use_cache = args.get('useCache', True)

            if not url:
                raise ProcessingError("Youtube-URL ist erforderlich")
            
            # Verarbeite YouTube-Video mit der Hilfsfunktion
            result = asyncio.run(process_youtube(
                url=url,
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache,
                process_id=process_id
            ))
            
            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker and hasattr(tracker, 'eval_result'):
                tracker.eval_result(result)
            
            # Konvertiere Ergebnis in Dict und gib es zurück
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
        except ProcessingError as e:
            logger.error("Verarbeitungsfehler",
                        error=e,
                        error_type="ProcessingError",
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': getattr(e, 'error_code', 'ProcessingError'),
                    'message': str(e),
                    'details': getattr(e, 'details', {})
                }
            }, 400
        except Exception as e:
            logger.error("Youtube-Verarbeitungsfehler",
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
            }, 400

# Video-Verarbeitungs-Endpunkt
@video_ns.route('/process')
class VideoProcessEndpoint(Resource):
    @video_ns.doc(id='process_video', 
                 description='Verarbeitet ein Video und extrahiert den Audio-Inhalt. Unterstützt sowohl URLs als auch Datei-Uploads über Formular-Anfragen.')
    @video_ns.response(200, 'Erfolg', video_response)
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.expect(video_upload_parser)
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet ein Video und extrahiert den Audio-Inhalt.
        Unterstützt sowohl URLs als auch Datei-Uploads.
        
        Für Datei-Uploads verwende multipart/form-data mit dem Parameter 'file'.
        Für URL-basierte Verarbeitung kann entweder multipart/form-data mit dem Parameter 'url' 
        oder eine JSON-Anfrage mit dem Parameter 'url' verwendet werden.
        """
        try:
            # Initialisiere Variablen
            source: VideoSource = None
            binary_data: Optional[bytes] = None
            target_language: str = 'de'
            source_language: str = 'auto'
            template: Optional[str] = None
            use_cache: bool = True
            force_refresh: bool = False
            process_id = str(uuid.uuid4())

            # Prüfe ob Datei oder URL
            if request.files and 'file' in request.files and request.files['file'].filename:
                # File Upload
                uploaded_file: FileStorage = request.files['file']
                # Lese binäre Daten, aber speichere sie NICHT in der VideoSource
                binary_data = uploaded_file.read()
                # Größe der Datei bestimmen
                file_size = len(binary_data)
                # Aktueller Zeitstempel
                upload_timestamp = datetime.now().isoformat()
                # Erstelle VideoSource mit zusätzlichen Identifikationsmerkmalen
                source = VideoSource(
                    file_name=uploaded_file.filename,
                    file_size=file_size,
                    upload_timestamp=upload_timestamp
                )
                # Parameter aus form-data
                target_language = request.form.get('target_language', 'de')
                source_language = request.form.get('source_language', 'auto')
                template = request.form.get('template')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
                force_refresh_str = request.form.get('force_refresh', 'false')
                force_refresh = force_refresh_str.lower() == 'true'
                
                logger.info(f"Verarbeite hochgeladene Datei: {uploaded_file.filename}")
            elif request.form and 'url' in request.form and request.form['url']:
                # URL aus form-data
                url = request.form.get('url')
                source = VideoSource(url=url)
                
                # Parameter aus form-data
                target_language = request.form.get('target_language', 'de')
                source_language = request.form.get('source_language', 'auto')
                template = request.form.get('template')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
                force_refresh_str = request.form.get('force_refresh', 'false')
                force_refresh = force_refresh_str.lower() == 'true'
                
                logger.info(f"Verarbeite Video-URL aus form-data: {url}")
            else:
                # JSON Request
                data = request.get_json()
                if not data or 'url' not in data:
                    raise ProcessingError("Entweder URL oder Datei muss angegeben werden")
                
                url = data.get('url')
                source = VideoSource(url=url)
                
                # Parameter aus JSON
                target_language = data.get('target_language', 'de')
                source_language = data.get('source_language', 'auto')
                template = data.get('template')
                use_cache = data.get('useCache', True)
                force_refresh = data.get('force_refresh', False)
                
                logger.info(f"Verarbeite Video-URL aus JSON: {url}")

            if not source:
                raise ProcessingError("Keine gültige Video-Quelle gefunden")

            # Verarbeite Video mit Hilfsfunktion
            result: VideoResponse = asyncio.run(process_video(
                source=source,
                binary_data=binary_data,  # Übergebe die Binärdaten separat
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache,
                force_refresh=force_refresh,
                process_id=process_id
            ))
            
            # Konvertiere Ergebnis in Dict und gib es zurück
            return result.to_dict()

        except ProcessingError as e:
            logger.error(f"Verarbeitungsfehler: {str(e)}", exc_info=True)
            return {
                'status': 'error',
                'error': {
                    'code': 'PROCESSING_ERROR',
                    'message': str(e),
                    'details': getattr(e, 'details', {})
                }
            }, 400
        except Exception as e:
            logger.error("Video-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
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