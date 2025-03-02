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

# Model für Youtube-URLs und Parameter
youtube_input = video_ns.model('YoutubeInput', {
    'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache (ISO 639-1 code)'),
    'template': fields.String(required=False, default=None, description='Template für die Verarbeitung')
})

# Model für Video-Requests
video_request = video_ns.model('VideoRequest', {
    'url': fields.String(required=False, description='URL des Videos'),
    'file': fields.Raw(required=False, description='Hochgeladene Video-Datei'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache für die Transkription'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'template': fields.String(required=False, description='Optional Template für die Verarbeitung'),
    'useCache': fields.Boolean(required=False, default=True, description='Cache verwenden (default: True)')
})

# Helper-Funktionen zum Abrufen der Prozessoren
def get_video_processor(process_id: Optional[str] = None) -> VideoProcessor:
    """Get or create video processor instance with process ID"""
    return VideoProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

def get_youtube_processor(process_id: Optional[str] = None) -> YoutubeProcessor:
    """Get or create youtube processor instance with process ID"""
    return YoutubeProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

# YouTube-Endpunkt - exakt wie in der alten routes.py
@video_ns.route('/youtube')
class YoutubeEndpoint(Resource):
    @video_ns.expect(youtube_input)
    @video_ns.response(200, 'Erfolg', youtube_response)
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.doc(description='Verarbeitet ein Youtube-Video')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet ein Youtube-Video"""
        process_id = str(uuid.uuid4())
        tracker: PerformanceTracker | None = get_performance_tracker() or get_performance_tracker(process_id)
        youtube_processor: YoutubeProcessor = get_youtube_processor(process_id)
        
        try:
            data = request.get_json()
            if not data:
                raise ProcessingError("Keine Daten erhalten")
                
            url = data.get('url')
            source_language = data.get('source_language', 'auto')
            target_language = data.get('target_language', 'de')
            template = data.get('template')

            if not url:
                raise ProcessingError("Youtube-URL ist erforderlich")

            result: YoutubeResponse = asyncio.run(youtube_processor.process(
                file_path=url,
                source_language=source_language,
                target_language=target_language,
                template=template
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
        finally:
            if youtube_processor and youtube_processor.logger:
                youtube_processor.logger.info("Youtube-Verarbeitung beendet")

# Video-Verarbeitungs-Endpunkt - exakt wie in der alten routes.py
@video_ns.route('/process')
class VideoProcessEndpoint(Resource):
    @video_ns.expect(video_request)
    @video_ns.response(200, 'Erfolg', youtube_response)
    @video_ns.response(400, 'Validierungsfehler', error_model)
    @video_ns.doc(description='Verarbeitet ein Video und extrahiert den Audio-Inhalt. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet ein Video und extrahiert den Audio-Inhalt.
        Unterstützt sowohl URLs als auch Datei-Uploads.
        """
        try:
            # Initialisiere Variablen
            source: VideoSource
            target_language: str = 'de'
            source_language: str = 'auto'
            template: Optional[str] = None
            use_cache: bool = True

            # Prüfe ob Datei oder URL
            if request.files and 'file' in request.files:
                # File Upload
                uploaded_file: FileStorage = request.files['file']
                file_content = uploaded_file.read()
                source = VideoSource(
                    file=file_content,
                    file_name=uploaded_file.filename
                )
                # Parameter aus form-data
                target_language = request.form.get('target_language', 'de')
                source_language = request.form.get('source_language', 'auto')
                template = request.form.get('template')
                use_cache_str = request.form.get('useCache', 'true')
                use_cache = use_cache_str.lower() == 'true'
            else:
                # JSON Request
                data = request.get_json()
                if not data or 'url' not in data:
                    raise ProcessingError("Entweder URL oder Datei muss angegeben werden")
                source = VideoSource(url=data['url'])
                # Parameter aus JSON
                target_language = data.get('target_language', 'de')
                source_language = data.get('source_language', 'auto')
                template = data.get('template')
                use_cache = data.get('useCache', True)

            # Initialisiere Prozessor
            process_id = str(uuid.uuid4())
            processor = VideoProcessor(resource_calculator, process_id)

            # Verarbeite Video
            result: VideoResponse = asyncio.run(processor.process(
                source=source,
                target_language=target_language,
                source_language=source_language,
                template=template,
                use_cache=use_cache
            ))

            return result.to_dict()

        except ProcessingError as e:
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