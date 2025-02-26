from typing import Dict, Any, Optional, Union, cast, IO, List
from pathlib import Path
import os
import tempfile
import traceback
import uuid
import time
from datetime import datetime
import asyncio
from werkzeug.datastructures import FileStorage
from werkzeug.wrappers import Response
from flask import send_file
import mimetypes
import json

from flask import request, Blueprint
from flask_restx import Namespace, Resource, Api, fields, inputs  # type: ignore

from src.core.models.notion import NotionResponse
from src.core.models.event import BatchEventResponse
from src.core.models.event import EventResponse
from src.core.models.youtube import YoutubeResponse
from src.processors.imageocr_processor import ImageOCRResponse
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.core.models.transformer import TransformerResponse
from src.core.rate_limiting import RateLimiter
from src.core.resource_tracking import ResourceCalculator
from src.core.models.audio import AudioResponse

from src.processors.audio_processor import AudioProcessor
from src.processors.imageocr_processor import ImageOCRProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.processors.metadata_processor import (
    MetadataProcessor,
    MetadataResponse
)
from src.processors.pdf_processor import PDFProcessor

from src.utils.logger import get_logger, ProcessingLogger
from src.utils.performance_tracker import (
    get_performance_tracker,
    clear_performance_tracker,
    PerformanceTracker
)

from src.core.models.video import VideoSource, VideoResponse
from src.processors.video_processor import VideoProcessor

from src.processors.event_processor import EventProcessor

# Type Aliases
MetadataEndpointResponse = Dict[str, Any]

# Initialisiere Resource Calculator und Logger
resource_calculator = ResourceCalculator()
logger: ProcessingLogger = get_logger(process_id="api")

# Blueprint und API Setup
blueprint = Blueprint('api', __name__)
api = Api(
    blueprint,
    title='Common Secretary Services API',
    version='1.0',
    description='API für die Verarbeitung von verschiedenen Medientypen'
)

# API Namespaces definieren
audio_ns: Namespace = api.namespace('audio', description='Audio-Verarbeitungs-Operationen')  # type: ignore
youtube_ns: Namespace = api.namespace('youtube', description='YouTube-Verarbeitungs-Operationen')  # type: ignore
metadata_ns: Namespace = api.namespace('metadata', description='Metadaten-Verarbeitungs-Operationen')  # type: ignore

# Initialisiere Rate Limiter
rate_limiter = RateLimiter(requests_per_hour=100, max_file_size=50 * 1024 * 1024)  # 50MB

# Initialisierung der gemeinsam genutzten Komponenten
resource_calculator = ResourceCalculator()
rate_limiter = RateLimiter(
    requests_per_hour=100,
    max_file_size=50 * 1024 * 1024  # 50MB
)

def _track_llm_usage(model: str, tokens: int, duration: float, purpose: str = "api") -> None:
    """Standardisiertes LLM-Tracking für die API."""
    try:
        if not model:
            raise ValueError("model darf nicht leer sein")
        if tokens <= 0:
            raise ValueError("tokens muss positiv sein")
        if duration < 0:
            raise ValueError("duration muss nicht-negativ sein")
                
        resource_calculator.track_usage(
            tokens=tokens,
            model=model,
            duration=duration
        )
        
        logger.info(
            "LLM-Nutzung getrackt",
            model=model,
            tokens=tokens,
            duration=duration,
            purpose=purpose
        )
    except Exception as e:
        logger.warning(
            "LLM-Tracking fehlgeschlagen",
            error=e,
            model=model,
            tokens=tokens,
            duration=duration
        )

def _calculate_llm_cost(model: str, tokens: int) -> float:
    """Berechnet die Kosten für LLM-Nutzung."""
    try:
        return resource_calculator.calculate_cost(tokens=tokens, model=model)
    except Exception as e:
        logger.warning(
            "LLM-Kostenberechnung fehlgeschlagen",
            error=e,
            model=model,
            tokens=tokens
        )
        return 0.0

@blueprint.before_request
def setup_request() -> None:
    """
    Bereitet die Request-Verarbeitung vor und prüft das Rate Limit.
    Initialisiert den Performance-Tracker für den Request.
    """
    # Rate Limit prüfen
    ip = request.remote_addr or 'unknown'
    endpoint = request.endpoint or 'unknown'
    
    if not rate_limiter.is_allowed(ip):
        raise RateLimitExceeded(f"Rate limit exceeded for IP {ip}")
    
    # Performance Tracking initialisieren
    process_id = str(uuid.uuid4())
    tracker = get_performance_tracker(process_id)
    
    # Setze Endpoint-Informationen
    user_agent = request.headers.get('User-Agent', 'unknown')
    if tracker:
        tracker.set_endpoint_info(endpoint, ip, user_agent)

@blueprint.after_request
def cleanup_request(response: Response) -> Response:
    """
    Räumt nach der Request-Verarbeitung auf.
    Schließt den Performance-Tracker ab und entfernt ihn.
    
    Args:
        response: Die Flask Response
        
    Returns:
        Die unveränderte Response
    """
    tracker = get_performance_tracker()
    if tracker:
        # Setze Error-Status wenn die Response einen Fehler anzeigt
        if response.status_code >= 400:
            error_data = response.get_json()
            error_message = error_data.get('error', 'Unknown error') if error_data else 'Unknown error'
            tracker.set_error(error_message)
            
        tracker.complete_tracking()
        clear_performance_tracker()
    return response

@blueprint.errorhandler(Exception)
def handle_error(error: Exception) -> tuple[Dict[str, str], int]:
    """
    Globaler Fehlerhandler für alle Exceptions.
    
    Args:
        error: Die aufgetretene Exception
        
    Returns:
        Tuple aus Fehlermeldung und HTTP Status Code
    """
    tracker: PerformanceTracker | None = get_performance_tracker()
    if tracker:
        tracker.set_error(str(error), error_type=error.__class__.__name__)
    
    logger.error("API Fehler",
                error=error,
                error_type=error.__class__.__name__,
                endpoint=request.endpoint,
                ip=request.remote_addr)
    return {'error': str(error)}, 500

def get_pdf_processor(process_id: Optional[str] = None) -> PDFProcessor:
    """Get or create PDF processor instance with process ID"""
    return PDFProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

def get_imageocr_processor(process_id: Optional[str] = None) -> ImageOCRProcessor:
    """Get or create ImageOCR processor instance with process ID"""
    return ImageOCRProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

def get_youtube_processor(process_id: Optional[str] = None) -> YoutubeProcessor:
    """Get or create Youtube processor instance with process ID"""
    return YoutubeProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

def get_audio_processor(process_id: Optional[str] = None) -> AudioProcessor:
    """Get or create audio processor instance with process ID"""
    return AudioProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

def get_transformer_processor(process_id: Optional[str] = None) -> TransformerProcessor:
    """Get or create transformer processor instance with process ID"""
    return TransformerProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

def get_metadata_processor(process_id: Optional[str] = None) -> MetadataProcessor:
    """Get or create metadata processor instance with process ID"""
    return MetadataProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

# Initialisiere Parser
file_upload = api.parser()
file_upload.add_argument('file', type=FileStorage, location='files', required=True, help='Die zu verarbeitende Datei')

# ImageOCR Upload Parser
imageocr_upload_parser = api.parser()
imageocr_upload_parser.add_argument('file', type=FileStorage, location='files', required=True, help='Bilddatei')
imageocr_upload_parser.add_argument('template', type=str, location='form', required=False, help='Template für die Transformation')
imageocr_upload_parser.add_argument('context', type=str, location='form', required=False, help='JSON-Kontext für die Verarbeitung')

# PDF Upload Parser
pdf_upload_parser = api.parser()
pdf_upload_parser.add_argument('file',
                          type=FileStorage,
                          location='files',
                          required=True,
                          help='PDF-Datei')
pdf_upload_parser.add_argument('extraction_method',
                          type=str,
                          location='form',
                          default='native',
                          choices=['native', 'ocr', 'both'],
                          help='Extraktionsmethode (native=nur Text, ocr=nur OCR, both=beides)')
pdf_upload_parser.add_argument('template',
                          type=str,
                          location='form',
                          required=False,
                          help='Template für die Transformation')
pdf_upload_parser.add_argument('context',
                          type=str,
                          location='form',
                          required=False,
                          help='JSON-Kontext für die Verarbeitung')

# Model für Youtube-URLs und Parameter
youtube_input = api.model('YoutubeInput', {
    'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
    'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache (ISO 639-1 code)'),
    'template': fields.String(required=False, default=None, description='Template für die Verarbeitung')
})

# Response Models
error_model = api.model('Error', {
    'error': fields.String(description='Fehlermeldung')
})

pdf_response = api.model('PDFResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(api.model('PDFRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(api.model('PDFProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(api.model('PDFData', {
        'metadata': fields.Nested(api.model('PDFMetadata', {
            'file_name': fields.String(description='Dateiname'),
            'file_size': fields.Integer(description='Dateigröße in Bytes'),
            'page_count': fields.Integer(description='Anzahl der Seiten'),
            'format': fields.String(description='Dateiformat'),
            'process_dir': fields.String(description='Verarbeitungsverzeichnis'),
            'image_paths': fields.List(fields.String, description='Pfade zu generierten Bildern (bei OCR)'),
            'text_paths': fields.List(fields.String, description='Pfade zu extrahierten Texten'),
            'extraction_method': fields.String(description='Verwendete Extraktionsmethode (native/ocr/both)')
        })),
        'extracted_text': fields.String(description='Extrahierter Text (bei native/both)'),
        'ocr_text': fields.String(description='Via OCR erkannter Text (bei ocr/both)'),
        'process_id': fields.String(description='Prozess-ID')
    })),
    'error': fields.Nested(api.model('PDFError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

imageocr_response = api.model('ImageOCRResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(api.model('ImageOCRRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(api.model('ImageOCRProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(api.model('ImageOCRData', {
        'metadata': fields.Nested(api.model('ImageOCRMetadata', {
            'file_name': fields.String(description='Dateiname'),
            'file_size': fields.Integer(description='Dateigröße in Bytes'),
            'dimensions': fields.String(description='Bildabmessungen'),
            'format': fields.String(description='Bildformat'),
            'color_mode': fields.String(description='Farbmodus'),
            'dpi': fields.Raw(description='DPI-Informationen'),
            'process_dir': fields.String(description='Verarbeitungsverzeichnis')
        })),
        'extracted_text': fields.String(description='Extrahierter Text'),
        'process_id': fields.String(description='Prozess-ID')
    }))
})

youtube_response = api.model('YoutubeResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(api.model('YoutubeRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(api.model('YoutubeProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(api.model('YoutubeData', {
        'metadata': fields.Raw(description='Video Metadaten'),
        'transcription': fields.Raw(description='Transkriptionsergebnis (wenn verfügbar)')
    })),
    'error': fields.Nested(api.model('YoutubeError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

audio_response = api.model('AudioResponse', {
    'duration': fields.Float(description='Audio Länge in Sekunden'),
    'detected_language': fields.String(description='Erkannte Sprache (ISO 639-1)'),
    'output_text': fields.String(description='Transkribierter/übersetzter Text'),
    'original_text': fields.String(description='Original transkribierter Text'),
    'translated_text': fields.String(description='Übersetzter Text (falls übersetzt)'),
    'llm_model': fields.String(description='Verwendetes LLM-Modell'),
    'translation_model': fields.String(description='Verwendetes Übersetzungsmodell (falls übersetzt)'),
    'token_count': fields.Integer(description='Anzahl der verwendeten Tokens'),
    'segments': fields.List(fields.Raw, description='Liste der Audio-Segmente mit Zeitstempeln'),
    'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking'),
    'process_dir': fields.String(description='Verarbeitungsverzeichnis'),
    'args': fields.Raw(description='Verwendete Verarbeitungsparameter'),
    'from_cache': fields.Boolean(description='Gibt an, ob das Ergebnis aus dem Cache geladen wurde')
})

# Model für Audio-Upload Parameter
upload_parser = api.parser()
upload_parser.add_argument('file', location='files', type=FileStorage, required=True, help='Audio-Datei')
upload_parser.add_argument('source_language', location='form', type=str, default='de', help='Quellsprache (ISO 639-1 code, z.B. "en", "de")')
upload_parser.add_argument('target_language', location='form', type=str, default='de', help='Zielsprache (ISO 639-1 code, z.B. "en", "de")')
upload_parser.add_argument('template', location='form', type=str, default='', help='Optional Template für die Verarbeitung')
upload_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')  # type: ignore

@api.errorhandler(ProcessingError)  # type: ignore
@api.errorhandler(FileSizeLimitExceeded)  # type: ignore
@api.errorhandler(RateLimitExceeded)  # type: ignore
def handle_processing_error(error: Exception) -> tuple[Dict[str, str], int]:
    """Globaler Fehlerhandler für Verarbeitungsfehler"""
    logger.error("API Fehler",
                error=error,
                error_type=error.__class__.__name__,
                endpoint=request.endpoint,
                ip=request.remote_addr)
    return {'error': str(error)}, 400

@api.route('/process-pdf')
class PDFEndpoint(Resource):
    @api.expect(pdf_upload_parser)
    @api.response(200, 'Erfolg', pdf_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet eine PDF-Datei und extrahiert Informationen. Unterstützt verschiedene Extraktionsmethoden: native (Text), ocr (OCR) oder both (beides).')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine PDF-Datei"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            tracker = get_performance_tracker()
            process_id = str(uuid.uuid4())
            temp_file: IO[bytes] | None = None
            
            try:
                args = pdf_upload_parser.parse_args()
                uploaded_file = cast(FileStorage, args['file'])
                extraction_method = args.get('extraction_method', 'native')
                template = args.get('template')
                context_str = args.get('context')
                context = json.loads(context_str) if context_str else None
                
                if not uploaded_file.filename:
                    raise ProcessingError("Kein Dateiname angegeben")
                
                # Speichere Datei temporär
                suffix = Path(uploaded_file.filename).suffix
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                uploaded_file.save(temp_file.name)
                temp_file.close()
                
                # Verarbeitung der PDF-Datei
                processor = get_pdf_processor(process_id)
                
                if tracker:
                    with tracker.measure_operation('pdf_processing', 'PDFProcessor'):
                        result = await processor.process(
                            temp_file.name,
                            template=template,
                            context=context,
                            extraction_method=extraction_method
                        )
                        tracker.eval_result(result)
                else:
                    result = await processor.process(
                        temp_file.name,
                        template=template,
                        context=context,
                        extraction_method=extraction_method
                    )
                
                return result.to_dict()
                
            except Exception as e:
                logger.error("Fehler bei der PDF-Verarbeitung", error=e)
                logger.error(traceback.format_exc())
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
                if temp_file and os.path.exists(temp_file.name):
                    try:
                        os.unlink(temp_file.name)
                    except Exception as e:
                        logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
        
        # Führe die asynchrone Verarbeitung aus
        return asyncio.run(process_request())

@api.route('/process-imageocr')
class ImageOCREndpoint(Resource):
    @api.expect(imageocr_upload_parser)
    @api.response(200, 'Erfolg', imageocr_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Bild und extrahiert Text mittels OCR')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Bild mit OCR verarbeiten"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            from werkzeug.datastructures import ImmutableMultiDict, FileStorage
            
            args: ImmutableMultiDict[str, Any] = imageocr_upload_parser.parse_args()
            uploaded_file: FileStorage = cast(FileStorage, args.get('file'))
            template: Optional[str] = cast(Optional[str], args.get('template'))
            context_str: Optional[str] = cast(Optional[str], args.get('context'))
            context: Optional[Dict[str, Any]] = json.loads(context_str) if context_str else None
                
            if not uploaded_file.filename:
                raise ProcessingError("Kein Dateiname angegeben")
                
            tracker: PerformanceTracker | None = get_performance_tracker()
            process_id = str(uuid.uuid4())
            imageocr_processor: ImageOCRProcessor = get_imageocr_processor(process_id)
            temp_file: IO[bytes] | None = None
            
            if not any(uploaded_file.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
                return {'error': 'Nur PNG/JPG Dateien erlaubt'}, 400
            
            try:
                # Speichere Datei temporär
                suffix = Path(uploaded_file.filename).suffix
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                uploaded_file.save(temp_file.name)
                temp_file.close()
                
                result: ImageOCRResponse = await imageocr_processor.process(
                    file_path=temp_file.name,
                    template=template,
                    context=context
                )
                
                if tracker:
                    tracker.eval_result(result)
                
                return result.to_dict()
                
            except Exception as e:
                error_response: Dict[str, Any] = {
                    'status': 'error',
                    'error': {
                        'code': 'ProcessingError',
                        'message': f'Fehler bei der OCR-Verarbeitung: {e}'
                    }
                }
                logger.error("OCR-Verarbeitungsfehler", error=e)
                return error_response, 400
                
            finally:
                if temp_file and os.path.exists(temp_file.name):
                    try:
                        os.unlink(temp_file.name)
                    except Exception as e:
                        logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
                if imageocr_processor and imageocr_processor.logger:
                    imageocr_processor.logger.info("OCR-Verarbeitung beendet")
                    
        return asyncio.run(process_request())

@api.route('/process-youtube')
class YoutubeEndpoint(Resource):
    @api.expect(youtube_input)
    @api.response(200, 'Erfolg', youtube_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Youtube-Video')
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
            }
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

@api.route('/process-audio')
class AudioEndpoint(Resource):
    """Audio-Verarbeitungs-Endpunkt."""
    
    def _safe_delete(self, file_path: Union[str, Path]) -> None:
        """Löscht eine Datei sicher."""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning("Konnte temporäre Datei nicht löschen", error=e)

    @api.expect(upload_parser)
    @api.response(200, 'Erfolg', audio_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet eine Audio-Datei. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        source_language: str = 'de'  # Default-Wert
        target_language: str = 'de'  # Default-Wert
        try:
            # Parse request
            args = upload_parser.parse_args()
            audio_file = args.get('file')
            source_language = args.get('source_language', 'de')
            target_language = args.get('target_language', 'de')
            template = args.get('template', '')
            use_cache = args.get('useCache', True)

            if not audio_file:
                raise ValueError("Keine Audio-Datei gefunden")

            # Validiere Dateiformat
            filename = audio_file.filename.lower()
            supported_formats = {'flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'wav', 'webm'}
            file_ext = Path(filename).suffix.lstrip('.')
            source_info = {
                'original_filename': audio_file.filename,
                'file_size': audio_file.content_length,
                'file_type': audio_file.content_type,
                'file_ext': file_ext
            }

            if file_ext not in supported_formats:
                raise ProcessingError(
                    f"Das Format '{file_ext}' wird nicht unterstützt. Unterstützte Formate: {', '.join(supported_formats)}",
                    details={'error_type': 'INVALID_FORMAT', 'supported_formats': list(supported_formats)}
                )

            # Verarbeite die Datei
            result = asyncio.run(process_file(
                audio_file, 
                source_info, 
                source_language, 
                target_language, 
                template,
                use_cache
            )) 

            return result

        except ProcessingError as e:
            logger.error("Audio-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__,
                        target_language=target_language)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': getattr(e, 'details', None)
                }
            }, 400
            
        except Exception as e:
            logger.error("Unerwarteter Fehler bei der Audio-Verarbeitung",
                        error=e,
                        error_type=type(e).__name__,
                        target_language=target_language)
            return {
                'status': 'error',
                'error': {
                    'code': 'INTERNAL_ERROR',
                    'message': 'Ein unerwarteter Fehler ist aufgetreten',
                    'details': {
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    }
                }
            }, 500

def _truncate_text(text: str, max_length: int = 50) -> str:
    """Kürzt einen Text auf die angegebene Länge und fügt '...' hinzu wenn gekürzt wurde."""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."

@api.route('/transform-text')
class TransformTextResource(Resource):
    @api.doc('transform_text')
    @api.expect(api.model('TransformTextInput', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'source_language': fields.String(default='de', description='Quellsprache (ISO 639-1 code, z.B. "en", "de")'),
        'target_language': fields.String(default='de', description='Zielsprache (ISO 639-1 code, z.B. "en", "de")'),
        'summarize': fields.Boolean(default=False, description='Optional: Text zusammenfassen')
    }))
    @api.response(200, 'Erfolg', api.model('TransformTextResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(api.model('RequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(api.model('ProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
            'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
        })),
        'data': fields.Nested(api.model('TransformData', {
            'input': fields.Nested(api.model('InputData', {
                'text': fields.String(description='Ursprünglicher Text'),
                'language': fields.String(description='Quellsprache'),
                'format': fields.String(description='Eingabeformat')
            })),
            'output': fields.Nested(api.model('OutputData', {
                'text': fields.String(description='Transformierter Text'),
                'language': fields.String(description='Zielsprache'),
                'format': fields.String(description='Ausgabeformat')
            }))
        })),
        'error': fields.Nested(api.model('ErrorInfo', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    def post(self):
        """Transformiert Text mit optionaler Zusammenfassung."""
        try:
            data: Any = request.get_json()
            if not data:
                raise ValueError("Keine Daten erhalten")

            # Extrahiere Parameter
            source_text = data.get('text')
            source_language = data.get('source_language', 'de')
            target_language = data.get('target_language', 'de')
            summarize = data.get('summarize', False)

            # Validiere Eingaben
            if not source_text:
                raise ValueError("text ist erforderlich")

            # Erstelle Transformer Processor
            processor = get_transformer_processor(str(uuid.uuid4()))

            # Transformiere Text
            result = processor.transform(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize
            )

            # Die Response ist bereits standardisiert durch ResponseFactory
            return result.to_dict()

        except Exception as e:
            api.abort(400, str(e))

@api.route('/transform-template')
class TemplateTransformEndpoint(Resource):
    @api.expect(api.model('TransformTemplateInput', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'source_language': fields.String(default='de', description='Quellsprache (ISO 639-1 code, z.B. "en", "de")'),
        'target_language': fields.String(default='de', description='Zielsprache (ISO 639-1 code, z.B. "en", "de")'),
        'template': fields.String(required=True, description='Name des Templates (ohne .md Endung)'),
        'context': fields.String(required=False, description='Kontextinformationen für die Template-Verarbeitung')
    }))
    @api.response(200, 'Erfolg', api.model('TransformerTemplateResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(api.model('RequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(api.model('ProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'sub_processors': fields.List(fields.String, description='Unterprozessoren'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
            'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
        })),
        'data': fields.Raw(description='Transformationsergebnis'),
        'error': fields.Nested(api.model('ErrorInfo', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Text mit Template transformieren"""
        from flask import request  # Import im Methodenkontext
        data: Any = request.get_json()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            # Zeitmessung für Gesamtprozess starten
            process_start = time.time()
            
            transformer_processor: TransformerProcessor = get_transformer_processor(tracker.process_id if tracker else None)
            result: TransformerResponse = transformer_processor.transformByTemplate(
                source_text=data['text'],
                source_language=data.get('source_language', 'de'),
                target_language=data.get('target_language', 'de'),
                template=data['template'],
                context=data.get('context', {})
            )

            # Tracke LLM-Nutzung wenn vorhanden
            if result.llm_info:
                for request in result.llm_info.requests:
                    _track_llm_usage(
                        model=request.model,
                        tokens=request.tokens,
                        duration=request.duration,
                        purpose='template_transformation'
                    )

            # Berechne Gesamtkosten
            total_cost = 0.0
            if result.llm_info:
                for request in result.llm_info.requests:
                    total_cost += _calculate_llm_cost(
                        model=request.model,
                        tokens=request.tokens
                    )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker:
                tracker.eval_result(result)
            
            # Erstelle Response
            response: Dict[str, Any] = {
                'status': 'error' if result.error else 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_text': _truncate_text(data['text']),
                        'source_language': data.get('source_language', 'de'),
                        'target_language': data.get('target_language', 'de'),
                        'template': data['template'],
                        'context': data.get('context', {}),
                        'duration_ms': process_duration
                    }
                },
                'process': result.process.to_dict(),  # Nutze die to_dict() Methode von ProcessInfo
                'data': {
                    'input': {
                        'text': data['text'],
                        'language': data.get('source_language', ''),
                        'template': data['template'],
                        'context': data.get('context', {})
                    },
                    'output': {
                        'text': result.data.output.text if not result.error else None,
                        'language': result.data.output.language if not result.error else None,
                        'structured_data': result.data.output.structured_data if hasattr(result.data.output, 'structured_data') and not result.error else {}
                    }
                }
            }

            # Füge error-Informationen hinzu wenn vorhanden
            if result.error:
                response['error'] = {
                    'code': result.error.code,
                    'message': result.error.message,
                    'details': result.error.details if hasattr(result.error, 'details') else {}
                }
                return response, 400
            
            return response
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            return {
                'status': 'error',
                'error': {
                    'code': error.__class__.__name__,
                    'message': str(error),
                    'details': {}
                }
            }, 400
        except Exception as error:
            logger.error(
                'Fehler bei der Template-Transformation',
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                'status': 'error',
                'error': {
                    'code': 'ProcessingError', 
                    'message': f'Fehler bei der Template-Transformation: {error}',
                    'details': {}
                }
            }, 400

@api.route('/transform-html-table')
class HtmlTableTransformEndpoint(Resource):
    @api.expect(api.model('TransformHtmlTableInput', {
        'source_url': fields.String(required=True, description='Die URL der Webseite mit der HTML-Tabelle'),
        'output_format': fields.String(default='json', enum=['json'], description='Ausgabeformat (aktuell nur JSON unterstützt)'),
        'table_index': fields.Integer(required=False, description='Optional - Index der gewünschten Tabelle (0-basiert). Wenn nicht angegeben, werden alle Tabellen zurückgegeben.'),
        'start_row': fields.Integer(required=False, description='Optional - Startzeile für das Paging (0-basiert)'),
        'row_count': fields.Integer(required=False, description='Optional - Anzahl der zurückzugebenden Zeilen')
    }))
    @api.response(200, 'Erfolg', api.model('HtmlTableTransformResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(api.model('RequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(api.model('ProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden')
        })),
        'data': fields.Nested(api.model('HtmlTableData', {
            'input': fields.Nested(api.model('TableInput', {
                'text': fields.String(description='Original URL'),
                'language': fields.String(description='Eingabesprache'),
                'format': fields.String(description='Eingabeformat')
            })),
            'output': fields.Nested(api.model('TableOutput', {
                'text': fields.String(description='Transformierter Text (JSON)'),
                'language': fields.String(description='Ausgabesprache'),
                'format': fields.String(description='Ausgabeformat'),
                'structured_data': fields.Raw(description='Strukturierte Tabellendaten', example={
                    "url": "https://example.com",
                    "table_count": 1,
                    "tables": [{
                        "table_index": 0,
                        "headers": ["Name", "Alter"],
                        "rows": [{"Name": "Max", "Alter": "30"}],
                        "metadata": {
                            "total_rows": 1,
                            "column_count": 2,
                            "has_group_info": False,
                            "paging": {
                                "start_row": 0,
                                "row_count": 1,
                                "has_more": False
                            }
                        }
                    }]
                })
            }))
        })),
        'error': fields.Nested(api.model('ErrorInfo', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """HTML-Tabellen von einer Webseite in JSON transformieren"""
        data = request.get_json()
        tracker = get_performance_tracker()
        process_start = time.time()
        
        try:
            # Konvertiere numerische Parameter explizit zu Integer
            table_index = int(data.get('table_index')) if data.get('table_index') is not None else None
            start_row = int(data.get('start_row')) if data.get('start_row') is not None else None
            row_count = int(data.get('row_count')) if data.get('row_count') is not None else None

            transformer_processor = get_transformer_processor(tracker.process_id if tracker else None)
            result = transformer_processor.transformHtmlTable(
                source_url=data['source_url'],
                output_format=data.get('output_format', 'json'),
                table_index=table_index,
                start_row=start_row,
                row_count=row_count
            )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker:
                tracker.eval_result(result)
            
            # Erstelle Response
            response = {
                'status': 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_url': data['source_url'],
                        'output_format': data.get('output_format', 'json'),
                        'table_index': data.get('table_index'),
                        'start_row': data.get('start_row'),
                        'row_count': data.get('row_count'),
                        'duration_ms': process_duration
                    }
                },
                'process': {
                    'id': tracker.process_id if tracker else None,
                    'main_processor': 'transformer',
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': process_duration
                },
                'data': {
                    'input': {
                        'text': result.data.input.text,
                        'language': result.data.input.language,
                        'format': result.data.input.format.value
                    },
                    'output': {
                        'text': result.data.output.text,
                        'language': result.data.output.language,
                        'format': result.data.output.format.value,
                        'structured_data': result.data.output.structured_data
                    }
                }
            }

            if result.error:
                response['error'] = {
                    'code': result.error.code,
                    'message': result.error.message,
                    'details': result.error.details
                }
                return response, 400

            return response

        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            return {
                'status': 'error',
                'error': {
                    'code': error.__class__.__name__,
                    'message': str(error)
                }
            }, 400
        except Exception as error:
            logger.error(
                'Fehler bei der HTML-Tabellen-Transformation',
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                'status': 'error',
                'error': {
                    'code': 'ProcessingError',
                    'message': f'Fehler bei der HTML-Tabellen-Transformation: {error}'
                }
            }, 400


@api.route('/')
class Home(Resource):
    @api.doc(description='API Willkommensseite')
    def get(self):
        """API Willkommensseite"""
        return {'message': 'Welcome to the Processing Service API!'}

# Metadata Models
metadata_technical = api.model('TechnicalMetadata', {
    'file_size': fields.Integer(description='Dateigröße in Bytes'),
    'file_mime': fields.String(description='MIME-Type der Datei'),
    'file_extension': fields.String(description='Dateiendung'),
    'media_duration': fields.Float(description='Länge des Mediums in Sekunden', required=False),
    'media_bitrate': fields.Integer(description='Bitrate in kbps', required=False),
    'media_channels': fields.Integer(description='Anzahl der Audiokanäle', required=False),
    'media_samplerate': fields.Integer(description='Abtastrate in Hz', required=False),
    'image_width': fields.Integer(description='Bildbreite in Pixeln', required=False),
    'image_height': fields.Integer(description='Bildhöhe in Pixeln', required=False),
    'image_colorspace': fields.String(description='Farbraum', required=False),
    'doc_pages': fields.Integer(description='Anzahl der Seiten', required=False),
    'doc_encrypted': fields.Boolean(description='Verschlüsselungsstatus', required=False)
})

metadata_content = api.model('ContentMetadata', {
    'type': fields.String(description='Art der Metadaten'),
    'created': fields.String(description='Erstellungszeitpunkt (ISO 8601)'),
    'modified': fields.String(description='Letzter Änderungszeitpunkt (ISO 8601)'),
    'title': fields.String(description='Haupttitel des Werks'),
    'subtitle': fields.String(description='Untertitel des Werks', required=False),
    'authors': fields.String(description='Komma-separierte Liste der Autoren', required=False),
    'publisher': fields.String(description='Verlag oder Publisher', required=False),
    'publicationDate': fields.String(description='Erscheinungsdatum', required=False),
    'isbn': fields.String(description='ISBN (bei Büchern)', required=False),
    'doi': fields.String(description='Digital Object Identifier', required=False),
    'edition': fields.String(description='Auflage', required=False),
    'language': fields.String(description='Sprache (ISO 639-1)', required=False),
    'subject_areas': fields.String(description='Komma-separierte Liste der Fachgebiete', required=False),
    'keywords': fields.String(description='Komma-separierte Liste der Schlüsselwörter', required=False),
    'abstract': fields.String(description='Kurzzusammenfassung', required=False),
    'temporal_start': fields.String(description='Beginn des behandelten Zeitraums', required=False),
    'temporal_end': fields.String(description='Ende des behandelten Zeitraums', required=False),
    'temporal_period': fields.String(description='Bezeichnung der Periode', required=False),
    'spatial_location': fields.String(description='Ortsname', required=False),
    'spatial_latitude': fields.Float(description='Geografische Breite', required=False),
    'spatial_longitude': fields.Float(description='Geografische Länge', required=False),
    'spatial_habitat': fields.String(description='Lebensraum/Biotop', required=False),
    'spatial_region': fields.String(description='Region/Gebiet', required=False),
    'rights_holder': fields.String(description='Rechteinhaber', required=False),
    'rights_license': fields.String(description='Lizenz', required=False),
    'rights_access': fields.String(description='Zugriffsrechte', required=False),
    'rights_usage': fields.String(description='Komma-separierte Liste der Nutzungsbedingungen', required=False),
    'rights_attribution': fields.String(description='Erforderliche Namensnennung', required=False),
    'rights_commercial': fields.Boolean(description='Kommerzielle Nutzung erlaubt', required=False),
    'rights_modifications': fields.Boolean(description='Modifikationen erlaubt', required=False),
    'resource_type': fields.String(description='Art der Ressource', required=False),
    'resource_format': fields.String(description='Physisches/digitales Format', required=False),
    'resource_extent': fields.String(description='Umfang', required=False),
    'source_title': fields.String(description='Titel der Quelle', required=False),
    'source_type': fields.String(description='Art der Quelle', required=False),
    'source_identifier': fields.String(description='Eindeutige Kennung der Quelle', required=False),
    'platform_type': fields.String(description='Art der Plattform', required=False),
    'platform_url': fields.String(description='URL zur Ressource', required=False),
    'platform_id': fields.String(description='Plattform-spezifische ID', required=False),
    'platform_uploader': fields.String(description='Uploader/Kanal', required=False),
    'platform_category': fields.String(description='Plattform-Kategorie', required=False),
    'platform_language': fields.String(description='Komma-separierte Liste der unterstützten Sprachen', required=False),
    'platform_region': fields.String(description='Komma-separierte Liste der verfügbaren Regionen', required=False),
    'platform_age_rating': fields.String(description='Altersfreigabe', required=False),
    'platform_subscription': fields.String(description='Erforderliches Abonnement', required=False),
    'event_type': fields.String(description='Art der Veranstaltung', required=False),
    'event_start': fields.String(description='Startzeit (ISO 8601)', required=False),
    'event_end': fields.String(description='Endzeit (ISO 8601)', required=False),
    'event_timezone': fields.String(description='Zeitzone', required=False),
    'event_format': fields.String(description='Veranstaltungsformat', required=False),
    'event_platform': fields.String(description='Verwendete Plattform', required=False),
    'event_recording_url': fields.String(description='Link zur Aufzeichnung', required=False),
    'social_platform': fields.String(description='Plattform', required=False),
    'social_handle': fields.String(description='Benutzername/Handle', required=False),
    'social_post_id': fields.String(description='Original Post-ID', required=False),
    'social_post_url': fields.String(description='Permalink zum Beitrag', required=False),
    'social_metrics_likes': fields.Integer(description='Anzahl der Likes', required=False),
    'social_metrics_shares': fields.Integer(description='Anzahl der Shares', required=False),
    'social_metrics_comments': fields.Integer(description='Anzahl der Kommentare', required=False),
    'social_metrics_views': fields.Integer(description='Anzahl der Aufrufe', required=False),
    'social_thread': fields.String(description='Komma-separierte Liste der IDs verknüpfter Beiträge', required=False),
    'blog_url': fields.String(description='Permalink zum Artikel', required=False),
    'blog_section': fields.String(description='Rubrik/Kategorie', required=False),
    'blog_series': fields.String(description='Zugehörige Serie/Reihe', required=False),
    'blog_reading_time': fields.Integer(description='Geschätzte Lesezeit in Minuten', required=False),
    'blog_tags': fields.String(description='Komma-separierte Liste der Blog-spezifischen Tags', required=False),
    'blog_comments_url': fields.String(description='Link zu Kommentaren', required=False),
    'community_target': fields.String(description='Komma-separierte Liste der Zielgruppen', required=False),
    'community_hashtags': fields.String(description='Komma-separierte Liste der verwendeten Hashtags', required=False),
    'community_mentions': fields.String(description='Komma-separierte Liste der erwähnten Accounts/Personen', required=False),
    'community_context': fields.String(description='Kontext/Anlass', required=False),
    'quality_review_status': fields.String(description='Review-Status', required=False),
    'quality_fact_checked': fields.Boolean(description='Faktencheck durchgeführt', required=False),
    'quality_peer_reviewed': fields.Boolean(description='Peer-Review durchgeführt', required=False),
    'quality_verified_by': fields.String(description='Komma-separierte Liste der Verifizierer', required=False),
    'citations': fields.String(description='Komma-separierte Liste der zitierten Werke', required=False),
    'methodology': fields.String(description='Verwendete Methodik', required=False),
    'funding': fields.String(description='Förderung/Finanzierung', required=False),
    'collection': fields.String(description='Zugehörige Sammlung', required=False),
    'archival_number': fields.String(description='Archivnummer', required=False),
    'status': fields.String(description='Status', required=False),
    'digital_published': fields.String(description='Erstveröffentlichung online (ISO 8601)', required=False),
    'digital_modified': fields.String(description='Letzte Online-Aktualisierung (ISO 8601)', required=False),
    'digital_version': fields.String(description='Versionsnummer/Stand', required=False),
    'digital_status': fields.String(description='Publikationsstatus', required=False)
})

metadata_response = api.model('MetadataResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Raw(description='Details zur Anfrage'),
    'process': fields.Raw(description='Informationen zur Verarbeitung'),
    'data': fields.Raw(description='Extrahierte Metadaten'),
    'error': fields.Raw(description='Fehlerinformationen (falls vorhanden)')
})

# Metadata Upload Parser
metadata_upload_parser = api.parser()
metadata_upload_parser.add_argument(
    'file', 
    type=FileStorage, 
    location='files',
    required=True,
    help='Die zu analysierende Datei'
)
metadata_upload_parser.add_argument(
    'content',
    type=str,
    location='form',
    required=False,
    help='Optionaler zusätzlicher Text für die Analyse'
)
metadata_upload_parser.add_argument(
    'context',
    type=str,  # JSON string
    location='form',
    required=False,
    help='Optionaler JSON-Kontext mit zusätzlichen Informationen'
)

async def process_file(uploaded_file: FileStorage, source_info: Dict[str, Any], source_language: str = 'de', target_language: str = 'de', template: str = '', use_cache: bool = True) -> Dict[str, Any]:
    """
    Verarbeitet eine hochgeladene Datei.
    
    Args:
        uploaded_file: Die hochgeladene Datei
        source_info: Informationen zur Quelle
        source_language: Die Quellsprache der Audio-Datei
        target_language: Die Zielsprache für die Verarbeitung
        template: Optional Template für die Verarbeitung
        use_cache: Ob der Cache verwendet werden soll (default: True)
        
    Returns:
        Dict mit den Verarbeitungsergebnissen
    
    Raises:
        ProcessingError: Wenn die Verarbeitung fehlschlägt
    """
    if not uploaded_file:
        raise ProcessingError("Keine Datei hochgeladen")
        
    # Erstelle temporäre Datei
    temp_file: IO[bytes] | None = None
    try:
        # Speichere Upload in temporärer Datei
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        uploaded_file.save(temp_file.name)
        
        # Verarbeite die Datei
        process_id = str(uuid.uuid4())
        processor: AudioProcessor = get_audio_processor(process_id)
        result: AudioResponse = await processor.process(
            audio_source=temp_file.name,
            source_info=source_info,
            source_language=source_language,
            target_language=target_language,
            template=template,
            use_cache=use_cache
        )
        return result.to_dict()
        
    finally:
        # Räume auf
        if temp_file:
            temp_file.close()
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass

@api.route('/extract-metadata')
class MetadataEndpoint(Resource):
    @api.expect(metadata_upload_parser)
    @api.response(200, 'Erfolg', metadata_response)
    @api.response(400, 'Validierungsfehler', error_model)
    def post(self) -> Union[MetadataEndpointResponse, tuple[Dict[str, Any], int]]:
        async def process_request() -> Union[MetadataEndpointResponse, tuple[Dict[str, Any], int]]:
            args = metadata_upload_parser.parse_args()
            uploaded_file = args.get('file')
            content = args.get('content')
            context = args.get('context')
            
            # Prozess-Tracking initialisieren
            process_id = str(uuid.uuid4())
            tracker: PerformanceTracker | None = get_performance_tracker() or get_performance_tracker(process_id)
            process_start: float = time.time()
                
            try:
                processor: MetadataProcessor = get_metadata_processor(process_id)
                result: MetadataResponse = await processor.process(
                    binary_data=uploaded_file,
                    content=content,
                    context=context
                )
                
                # Berechne Prozessdauer
                process_duration = int((time.time() - process_start) * 1000)
                
                # Füge Ressourcenverbrauch zum Tracker hinzu
                if tracker:
                    tracker.eval_result(result)
                
                # Response erstellen
                response: MetadataEndpointResponse = {
                    'status': 'error' if result.error else 'success',
                    'request': {
                        'processor': 'metadata',
                        'timestamp': datetime.now().isoformat(),
                        'parameters': {
                            'has_file': uploaded_file is not None,
                            'has_content': content is not None,
                            'context': context,
                            'duration_ms': process_duration
                        }
                    },
                    'process': result.process.to_dict(),  # Nutze die to_dict() Methode von ProcessInfo
                    'data': {
                        'technical': result.data.technical.to_dict() if result.data.technical else None,
                        'content': result.data.content.to_dict() if result.data.content else None
                    },
                    'error': None
                }

                # Fehlerbehandlung
                if result.error:
                    response['error'] = {
                        'code': result.error.code,
                        'message': result.error.message,
                        'details': result.error.details if hasattr(result.error, 'details') else {}
                    }
                    return response, 400
                
                return response
                
            except Exception as error:
                error_response: Dict[str, Any] = {
                    "status": "error",
                    "request": {},
                    "process": {},
                    "data": {},
                    "error": {
                        "code": "ProcessingError",
                        "message": f"Fehler bei der Metadaten-Extraktion: {str(error)}",
                        "details": {
                            "error_type": type(error).__name__,
                            "traceback": traceback.format_exc()
                        }
                    }
                }
                logger.error(
                    "Fehler bei der Metadaten-Extraktion",
                    error=error,
                    traceback=traceback.format_exc()
                )
                return error_response, 400

        # Führe die asynchrone Verarbeitung aus und warte auf das Ergebnis
        return asyncio.run(process_request())

@api.route('/process-video')
class VideoEndpoint(Resource):
    @api.expect(api.model('VideoRequest', {
        'url': fields.String(required=False, description='URL des Videos'),
        'file': fields.Raw(required=False, description='Hochgeladene Video-Datei'),
        'target_language': fields.String(required=False, default='de', description='Zielsprache für die Transkription'),
        'source_language': fields.String(required=False, default='auto', description='Quellsprache (auto für automatische Erkennung)'),
        'template': fields.String(required=False, description='Optional Template für die Verarbeitung'),
        'useCache': fields.Boolean(required=False, default=True, description='Cache verwenden (default: True)')
    }))
    @api.response(200, 'Erfolg', youtube_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Video und extrahiert den Audio-Inhalt. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')
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

@api.route('/samples')
class SamplesEndpoint(Resource):
    @api.doc(description='Listet alle verfügbaren Beispieldateien auf')
    def get(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Gibt eine Liste aller verfügbaren Beispieldateien zurück."""
        try:
            # Samples-Verzeichnis
            samples_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / 'tests' / 'samples'
            
            # Dateien auflisten
            files: list[dict[str, Any]] = []
            for file_path in samples_dir.glob('*'):
                if file_path.is_file():
                    files.append({
                        'name': file_path.name,
                        'size': file_path.stat().st_size,
                        'type': file_path.suffix.lstrip('.'),
                        'url': f'/api/samples/{file_path.name}'
                    })
            
            return {
                'status': 'success',
                'data': {
                    'files': files
                }
            }
        except Exception as e:
            logger.error("Fehler beim Auflisten der Beispieldateien",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            return {
                'status': 'error',
                'error': {
                    'code': 'SAMPLE_LIST_ERROR',
                    'message': str(e)
                }
            }, 500

@api.route('/samples/<string:filename>')
class SampleFileEndpoint(Resource):
    @api.doc(description='Lädt eine bestimmte Beispieldatei herunter')
    @api.response(200, 'Erfolg')
    @api.response(404, 'Datei nicht gefunden')
    def get(self, filename: str) -> Any:
        """Lädt eine bestimmte Beispieldatei herunter."""
        try:
            # Samples-Verzeichnis
            samples_dir: Path = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / 'tests' / 'samples'
            
            # Prüfe ob Datei existiert und im samples Verzeichnis liegt
            file_path: Path = samples_dir / filename
            if not file_path.is_file() or samples_dir not in file_path.parents:
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
            
            # Sende Datei mit angepassten Headern
            response = send_file(
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
            logger.error("Fehler beim Herunterladen der Beispieldatei",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            return {
                'status': 'error',
                'error': {
                    'code': 'SAMPLE_DOWNLOAD_ERROR',
                    'message': str(e)
                }
            }, 500

@api.route('/scrape-event-infos')
class EventEndpoint(Resource):
    @api.expect(api.model('EventRequest', {
        'event': fields.String(required=True, description='Name der Veranstaltung (z.B. "FOSDEM 2025")'),
        'session': fields.String(required=True, description='Name der Session (z.B. "Welcome to FOSDEM 2025")'),
        'url': fields.String(required=True, description='URL zur Event-Seite'),
        'filename': fields.String(required=True, description='Zieldateiname für die Markdown-Datei'),
        'track': fields.String(required=True, description='Track/Kategorie der Session'),
        'day': fields.String(required=False, description='Veranstaltungstag im Format YYYY-MM-DD'),
        'starttime': fields.String(required=False, description='Startzeit im Format HH:MM'),
        'endtime': fields.String(required=False, description='Endzeit im Format HH:MM'),
        'speakers': fields.List(fields.String, required=False, description='Liste der Vortragenden'),
        'video_url': fields.String(required=False, description='Optional, URL zum Video'),
        'attachments_url': fields.String(required=False, description='Optional, URL zu Anhängen'),
        'source_language': fields.String(required=False, default='en', description='Quellsprache (Standard: en)'),
        'target_language': fields.String(required=False, default='de', description='Zielsprache (Standard: de)')
    }))
    @api.response(200, 'Erfolg', api.model('EventResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(api.model('EventRequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(api.model('EventProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
            'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
        })),
        'data': fields.Nested(api.model('EventData', {
            'input': fields.Raw(description='Eingabedaten'),
            'output': fields.Raw(description='Ausgabedaten')
        })),
        'error': fields.Nested(api.model('EventError', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet Event-Informationen und zugehörige Medien')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet Event-Informationen und zugehörige Medien."""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            try:
                data = request.get_json()
                if not data:
                    raise ProcessingError("Keine Daten erhalten")

                # Validiere erforderliche Felder
                required_fields = ['event', 'session', 'url', 'filename', 'track']
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    raise ProcessingError(f"Fehlende Pflichtfelder: {', '.join(missing_fields)}")

                # Prozess-Tracking initialisieren
                process_id = str(uuid.uuid4())
                tracker: PerformanceTracker | None = get_performance_tracker() or get_performance_tracker(process_id)

                # Initialisiere Event-Processor
                processor: EventProcessor = get_event_processor(process_id)

                # Verarbeite Event
                result: EventResponse = await processor.process_event(
                    event=data['event'],
                    session=data['session'],
                    url=data['url'],
                    filename=data['filename'],
                    track=data['track'],
                    day=data.get('day'),
                    starttime=data.get('starttime'),
                    endtime=data.get('endtime'),
                    speakers=data.get('speakers', []),
                    video_url=data.get('video_url'),
                    attachments_url=data.get('attachments_url'),
                    source_language=data.get('source_language', 'en'),
                    target_language=data.get('target_language', 'de')
                )

                # Füge Ressourcenverbrauch zum Tracker hinzu
                if tracker:
                    tracker.eval_result(result)
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
                logger.error("Event-Verarbeitungsfehler",
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

        # Führe die asynchrone Verarbeitung aus
        return asyncio.run(process_request())

def get_event_processor(process_id: Optional[str] = None) -> EventProcessor:
    """Get or create event processor instance with process ID"""
    return EventProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

@api.route('/scrape-many-events')
class BatchEventEndpoint(Resource):
    """Endpoint für die Batch-Verarbeitung von Events."""
    
    @api.expect(api.model('BatchEventRequest', {
        'events': fields.List(fields.Nested(api.model('EventRequestItem', {
            'event': fields.String(required=True, description='Name der Veranstaltung (z.B. "FOSDEM 2025")'),
            'session': fields.String(required=True, description='Name der Session (z.B. "Welcome to FOSDEM 2025")'),
            'url': fields.String(required=True, description='URL zur Event-Seite'),
            'filename': fields.String(required=True, description='Zieldateiname für die Markdown-Datei'),
            'track': fields.String(required=True, description='Track/Kategorie der Session'),
            'day': fields.String(required=False, description='Veranstaltungstag im Format YYYY-MM-DD'),
            'starttime': fields.String(required=False, description='Startzeit im Format HH:MM'),
            'endtime': fields.String(required=False, description='Endzeit im Format HH:MM'),
            'speakers': fields.List(fields.String, required=False, description='Liste der Vortragenden'),
            'video_url': fields.String(required=False, description='Optional, URL zum Video'),
            'attachments_url': fields.String(required=False, description='Optional, URL zu Anhängen'),
            'source_language': fields.String(required=False, default='en', description='Quellsprache (Standard: en)'),
            'target_language': fields.String(required=False, default='de', description='Zielsprache (Standard: de)')
        })), required=True, description='Liste der zu verarbeitenden Events')
    }))
    @api.response(200, 'Erfolg', api.model('BatchEventResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(api.model('BatchRequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(api.model('BatchProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
            'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
        })),
        'data': fields.Nested(api.model('BatchEventData', {
            'input': fields.Raw(description='Batch-Eingabedaten'),
            'output': fields.Raw(description='Batch-Ausgabedaten')
        })),
        'error': fields.Nested(api.model('BatchError', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet mehrere Events sequentiell')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet mehrere Events sequentiell."""
        
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            try:
                # Validiere Request-Daten
                if not request.is_json:
                    return {"error": "Content-Type must be application/json"}, 400
                
                data = request.get_json()
                if not data or "events" not in data:
                    return {"error": "Request must contain 'events' list"}, 400
                
                events: List[Dict[str, Any]] = data["events"]
                if not events:
                    return {"error": "Events list must not be empty"}, 400
                
                # Initialisiere Event-Processor
                processor: EventProcessor = get_event_processor()
                
                # Verarbeite Events sequentiell
                result: BatchEventResponse = await processor.process_many_events(events)
                
                return result.to_dict()
                
            except Exception as e:
                return {
                    "error": str(e),
                    "details": {
                        "type": type(e).__name__,
                        "traceback": traceback.format_exc()
                    }
                }, 500
        
        return asyncio.run(process_request())

@api.route('/scrape-notion-page')
class NotionEndpoint(Resource):
    @api.expect(api.model('NotionRequest', {
        'blocks': fields.List(fields.Raw(description='Notion Block Struktur'))
    }))
    @api.response(200, 'Erfolg', api.model('NotionResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(api.model('NotionRequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(api.model('NotionProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
            'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
        })),
        'data': fields.Nested(api.model('NotionData', {
            'input': fields.List(fields.Raw(description='Notion Blocks')),
            'output': fields.Nested(api.model('Newsfeed', {
                'id': fields.String(description='Eindeutige Newsfeed-ID'),
                'title_DE': fields.String(description='Deutscher Titel'),
                'intro_DE': fields.String(description='Deutsche Einleitung'),
                'title_IT': fields.String(description='Italienischer Titel'),
                'intro_IT': fields.String(description='Italienische Einleitung'),
                'image': fields.String(description='Bild-URL'),
                'content_DE': fields.String(description='Deutscher Inhalt'),
                'content_IT': fields.String(description='Italienischer Inhalt')
            }))
        })),
        'error': fields.Nested(api.model('NotionError', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet Notion Blocks und erstellt mehrsprachigen Newsfeed-Inhalt (DE->IT)')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet Notion Blocks und erstellt einen mehrsprachigen Newsfeed-Eintrag.
        """
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            try:
                # Parse Request
                data = request.get_json()
                if not data or 'blocks' not in data:
                    return {'error': 'Keine Blocks gefunden'}, 400
                
                blocks_raw = data['blocks']
                if not isinstance(blocks_raw, list):
                    return {'error': 'Blocks müssen als Liste übergeben werden'}, 400
                
                blocks: List[Dict[str, Any]] = blocks_raw
                
                # Verarbeite Blocks
                processor: EventProcessor = get_event_processor()
                result: NotionResponse = await processor.process_notion_blocks(blocks)
                
                return result.to_dict()
                
            except Exception as e:
                return handle_processing_error(e)
        
        return asyncio.run(process_request())

# API Models
notion_response = api.model('NotionResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(api.model('NotionRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(api.model('NotionProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(api.model('NotionData', {
        'input': fields.List(fields.Raw(description='Notion Blocks')),
        'output': fields.Nested(api.model('Newsfeed', {
            'id': fields.String(description='Eindeutige Newsfeed-ID (parent_id des ersten Blocks)'),
            'title_DE': fields.String(description='Deutscher Titel'),
            'intro_DE': fields.String(description='Deutsche Einleitung'),
            'title_IT': fields.String(description='Italienischer Titel'),
            'intro_IT': fields.String(description='Italienische Einleitung'),
            'image': fields.String(description='Bild-URL'),
            'content_DE': fields.String(description='Deutscher Inhalt'),
            'content_IT': fields.String(description='Italienischer Inhalt')
        }))
    })),
    'error': fields.Nested(api.model('NotionError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Event-Processor Modelle
event_input = api.model('EventInput', {
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
})

batch_event_input = api.model('BatchEventInput', {
    'events': fields.List(fields.Nested(event_input), required=True, description='Liste von Event-Daten')
})

event_response = api.model('EventResponse', {
    'status': fields.String(required=True, description='Status der Anfrage'),
    'request': fields.Raw(required=True, description='Anfrageinformationen'),
    'process': fields.Raw(required=True, description='Prozessinformationen'),
    'data': fields.Raw(required=False, description='Ergebnisdaten'),
    'error': fields.Raw(required=False, description='Fehlerinformationen')
})

batch_event_response = api.model('BatchEventResponse', {
    'status': fields.String(required=True, description='Status der Anfrage'),
    'request': fields.Raw(required=True, description='Anfrageinformationen'),
    'process': fields.Raw(required=True, description='Prozessinformationen'),
    'data': fields.Raw(required=False, description='Ergebnisdaten'),
    'error': fields.Raw(required=False, description='Fehlerinformationen')
})

# Async Event-Processor Modelle
async_event_input = api.model('AsyncEventInput', {
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
    'target_language': fields.String(required=False, default='de', description='Zielsprache'),
    'webhook_url': fields.String(required=True, description='URL für den Webhook-Callback'),
    'webhook_headers': fields.Raw(required=False, description='HTTP-Header für den Webhook'),
    'include_markdown': fields.Boolean(required=False, default=True, description='Markdown-Inhalt im Webhook einschließen'),
    'include_metadata': fields.Boolean(required=False, default=True, description='Metadaten im Webhook einschließen'),
    'event_id': fields.String(required=False, description='Eindeutige ID für das Event')
})

async_batch_event_input = api.model('AsyncBatchEventInput', {
    'events': fields.List(fields.Nested(event_input), required=True, description='Liste von Event-Daten'),
    'webhook_url': fields.String(required=True, description='URL für den Webhook-Callback'),
    'webhook_headers': fields.Raw(required=False, description='HTTP-Header für den Webhook'),
    'include_markdown': fields.Boolean(required=False, default=True, description='Markdown-Inhalt im Webhook einschließen'),
    'include_metadata': fields.Boolean(required=False, default=True, description='Metadaten im Webhook einschließen'),
    'batch_id': fields.String(required=False, description='Eindeutige ID für den Batch')
})

# Hilfsfunktion zum Abrufen des Event-Processors
def get_event_processor(process_id: Optional[str] = None) -> EventProcessor:
    """
    Erstellt eine Instanz des Event-Processors.
    
    Args:
        process_id: Optional, die Process-ID vom API-Layer
        
    Returns:
        EventProcessor: Eine Instanz des Event-Processors
    """
    return EventProcessor(resource_calculator=resource_calculator, process_id=process_id)

@api.route('/process-event')
class EventEndpoint(Resource):
    @api.expect(event_input)
    @api.response(200, 'Erfolg', event_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Event mit allen zugehörigen Medien')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet ein Event mit allen zugehörigen Medien"""
        process_id = str(uuid.uuid4())
        tracker: Optional[PerformanceTracker] = get_performance_tracker() or get_performance_tracker(process_id)
        event_processor: EventProcessor = get_event_processor(process_id)
        
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
            }, 400
        finally:
            if event_processor and event_processor.logger:
                event_processor.logger.info("Event-Verarbeitung beendet")

@api.route('/process-events')
class BatchEventEndpoint(Resource):
    @api.expect(batch_event_input)
    @api.response(200, 'Erfolg', batch_event_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet mehrere Events sequentiell')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet mehrere Events sequentiell"""
        process_id = str(uuid.uuid4())
        tracker: Optional[PerformanceTracker] = get_performance_tracker() or get_performance_tracker(process_id)
        event_processor: EventProcessor = get_event_processor(process_id)
        
        try:
            data = request.get_json()
            if not data:
                raise ProcessingError("Keine Daten erhalten")
                
            events = data.get('events', [])
            if not events:
                raise ProcessingError("Keine Events gefunden")
            
            # Verarbeite die Events
            result: BatchEventResponse = asyncio.run(event_processor.process_many_events(
                events=events
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
            logger.error("Batch-Event-Verarbeitungsfehler",
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
            if event_processor and event_processor.logger:
                event_processor.logger.info("Batch-Event-Verarbeitung beendet")

@api.route('/process-event-async')
class AsyncEventEndpoint(Resource):
    @api.expect(async_event_input)
    @api.response(200, 'Erfolg', event_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Event asynchron und sendet einen Webhook-Callback nach Abschluss')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet ein Event asynchron und sendet einen Webhook-Callback nach Abschluss"""
        process_id = str(uuid.uuid4())
        tracker: Optional[PerformanceTracker] = get_performance_tracker() or get_performance_tracker(process_id)
        event_processor: EventProcessor = get_event_processor(process_id)
        
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
            webhook_url = data.get('webhook_url')
            webhook_headers = data.get('webhook_headers', {})
            include_markdown = data.get('include_markdown', True)
            include_metadata = data.get('include_metadata', True)
            event_id = data.get('event_id')
            
            # Validiere Pflichtfelder
            if not all([event, session, url, filename, track, webhook_url]):
                raise ProcessingError("Pflichtfelder fehlen: event, session, url, filename, track, webhook_url")
            
            # Verarbeite das Event asynchron
            result: EventResponse = asyncio.run(event_processor.process_event_async(
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
                webhook_url=webhook_url,
                webhook_headers=webhook_headers,
                include_markdown=include_markdown,
                include_metadata=include_metadata,
                event_id=event_id
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
            logger.error("Async-Event-Verarbeitungsfehler",
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
            if event_processor and event_processor.logger:
                event_processor.logger.info("Async-Event-Verarbeitung initiiert")

@api.route('/process-events-async')
class AsyncBatchEventEndpoint(Resource):
    @api.expect(async_batch_event_input)
    @api.response(200, 'Erfolg', batch_event_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet mehrere Events asynchron und sendet Webhook-Callbacks nach Abschluss jedes Events')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet mehrere Events asynchron und sendet Webhook-Callbacks nach Abschluss jedes Events"""
        process_id = str(uuid.uuid4())
        tracker: Optional[PerformanceTracker] = get_performance_tracker() or get_performance_tracker(process_id)
        event_processor: EventProcessor = get_event_processor(process_id)
        
        try:
            data = request.get_json()
            if not data:
                raise ProcessingError("Keine Daten erhalten")
                
            events = data.get('events', [])
            webhook_url = data.get('webhook_url')
            webhook_headers = data.get('webhook_headers', {})
            include_markdown = data.get('include_markdown', True)
            include_metadata = data.get('include_metadata', True)
            batch_id = data.get('batch_id')
            
            if not events:
                raise ProcessingError("Keine Events gefunden")
                
            if not webhook_url:
                raise ProcessingError("Webhook-URL ist erforderlich")
            
            # Verarbeite die Events asynchron
            result: BatchEventResponse = asyncio.run(event_processor.process_many_events_async(
                events=events,
                webhook_url=webhook_url,
                webhook_headers=webhook_headers,
                include_markdown=include_markdown,
                include_metadata=include_metadata,
                batch_id=batch_id
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
            logger.error("Async-Batch-Event-Verarbeitungsfehler",
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
            if event_processor and event_processor.logger:
                event_processor.logger.info("Async-Batch-Event-Verarbeitung initiiert")