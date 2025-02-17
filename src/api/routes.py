from typing import Dict, Any, Optional, Union, cast
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

from flask import request, Blueprint
from flask_restx import Namespace, Resource, Api, fields, reqparse

from core.models.youtube import YoutubeResponse
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.core.models.transformer import TransformerResponse
from src.core.rate_limiting import RateLimiter
from src.core.resource_tracking import ResourceCalculator
from src.core.models.audio import AudioResponse

from src.processors.audio_processor import AudioProcessor
from src.processors.image_processor import ImageProcessor
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
audio_ns: Namespace = api.namespace('audio', description='Audio-Verarbeitungs-Operationen')
youtube_ns: Namespace = api.namespace('youtube', description='YouTube-Verarbeitungs-Operationen')
metadata_ns: Namespace = api.namespace('metadata', description='Metadaten-Verarbeitungs-Operationen')

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

def get_image_processor(process_id: Optional[str] = None) -> ImageProcessor:
    """Get or create image processor instance with process ID"""
    return ImageProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

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

# Parser für File-Uploads
file_upload: reqparse.RequestParser = reqparse.RequestParser()
file_upload.add_argument('file',  # type: ignore
                        type=FileStorage, 
                        location='files', 
                        required=True,
                        help='Die zu verarbeitende Datei')
file_upload.add_argument('source_language',  # type: ignore
                        type=str,
                        location='form',
                        default='de',
                        help='Quellsprache der Audio-Datei (ISO 639-1)',
                        trim=True)
file_upload.add_argument('target_language',  # type: ignore
                        type=str,
                        location='form',
                        default='de',
                        help='Zielsprache für die Transkription (ISO 639-1)',
                        trim=True)
file_upload.add_argument('template',  # type: ignore
                        type=str,
                        location='form',
                        default='',
                        help='Template für die Transformation',
                        trim=True)

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
    'page_count': fields.Integer(description='Anzahl der Seiten'),
    'text_content': fields.String(description='Extrahierter Text'),
    'metadata': fields.Raw(description='PDF Metadaten'),
    'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking')
})

image_response = api.model('ImageResponse', {
    'dimensions': fields.Raw(description='Bildabmessungen (Breite x Höhe)'),
    'format': fields.String(description='Bildformat'),
    'metadata': fields.Raw(description='Bild Metadaten'),
    'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking')
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
    'args': fields.Raw(description='Verwendete Verarbeitungsparameter')
})

# Model für Audio-Upload Parameter
upload_parser = api.parser()
upload_parser.add_argument('file',
                          type=FileStorage,
                          location='files',
                          required=True,
                          help='Audio file (MP3, WAV, or M4A)')
upload_parser.add_argument('source_language',
                          type=str,
                          location='form',
                          default='de',
                          help='Quellsprache der Audio-Datei (ISO 639-1)')
upload_parser.add_argument('target_language',
                          type=str,
                          location='form',
                          default='de',
                          help='Zielsprache für die Transkription (ISO 639-1)')
upload_parser.add_argument('template',
                          type=str,
                          location='form',
                          default='',
                          help='Template für die Transformation')

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
    @api.expect(file_upload)  # type: ignore
    @api.response(200, 'Erfolg', pdf_response)  # type: ignore
    @api.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @api.doc(description='Verarbeitet eine PDF-Datei und extrahiert Informationen')  # type: ignore
    async def post(self) -> Dict[str, Any]:
        """Verarbeitet eine PDF-Datei und extrahiert Informationen"""
        tracker = get_performance_tracker()
        process_id = str(uuid.uuid4())
        temp_file = None
        
        try:
            args = file_upload.parse_args()  # type: ignore
            uploaded_file = cast(FileStorage, args['file'])
            
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
                    result = await processor.process(temp_file.name)
                    tracker.eval_result(result)
            else:
                result = await processor.process(temp_file.name)
            
            return result.to_dict()  # type: ignore
                
        except Exception as e:
            logger.error("Fehler bei der PDF-Verarbeitung", error=e)
            logger.error(traceback.format_exc())
            raise
        finally:
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")

@api.route('/process-image')
class ImageEndpoint(Resource):
    @api.expect(file_upload)  # type: ignore
    @api.response(200, 'Erfolg', image_response)  # type: ignore
    @api.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @api.doc(description='Verarbeitet ein Bild und extrahiert Informationen')  # type: ignore
    async def post(self) -> Union[Dict[str, Any], tuple[Dict[str, str], int]]:
        """Bild verarbeiten"""
        args: reqparse.ParseResult = file_upload.parse_args()  # type: ignore
        uploaded_file: FileStorage = cast(FileStorage, args['file'])
            
        if not uploaded_file.filename:
            raise ProcessingError("Kein Dateiname angegeben")
            
        image_processor = None
        tracker: PerformanceTracker | None = get_performance_tracker()
        process_id = str(uuid.uuid4())
        temp_file: tempfile._TemporaryFileWrapper[bytes] | None = None
        
        if not any(uploaded_file.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return {'error': 'Nur PNG/JPG Dateien erlaubt'}, 400
        
        try:
            # Speichere Datei temporär
            suffix = Path(uploaded_file.filename).suffix
            temp_file: tempfile._TemporaryFileWrapper[bytes] = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            uploaded_file.save(temp_file.name)
            temp_file.close()
            
            image_processor = get_image_processor(process_id)
            
            if tracker:
                with tracker.measure_operation('image_processing', 'ImageProcessor'):
                    result = await image_processor.process(temp_file.name)
                    tracker.eval_result(result)
            else:
                result = await image_processor.process(temp_file.name)
            
            return result.to_dict()  # type: ignore
        except Exception as e:
            logger.error("Bild-Verarbeitungsfehler", error=e)
            raise
        finally:
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
            if image_processor and image_processor.logger:
                image_processor.logger.info("Bild-Verarbeitung beendet")

@api.route('/process-youtube')
class YoutubeEndpoint(Resource):
    @api.expect(youtube_input)
    @api.response(200, 'Erfolg', youtube_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Youtube-Video')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet ein Youtube-Video"""
        youtube_processor = None
        process_id = str(uuid.uuid4())
        tracker = get_performance_tracker() or get_performance_tracker(process_id)
        
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

            youtube_processor: YoutubeProcessor = get_youtube_processor(process_id)
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
    @api.doc(description='Verarbeitet eine Audio-Datei')
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
            result = asyncio.run(process_file(audio_file, source_info, source_language, target_language, template)) 

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
    def post(self):
        """Transformiert Text mit optionalem Template."""
        try:
            data: Any = request.get_json()
            if not data:
                raise ValueError("Keine Daten erhalten")

            # Extrahiere Parameter
            source_text = data.get('text')
            source_language = data.get('source_language', 'de')
            target_language = data.get('target_language', 'de')
            template = data.get('template')
            context = data.get('context', {})

            # Validiere Eingaben
            if not source_text:
                raise ValueError("text ist erforderlich")

            # Erstelle Transformer Processor
            processor = TransformerProcessor(
                resource_calculator=resource_calculator,
                process_id=str(uuid.uuid4())
            )

            # Transformiere Text
            if template:
                result: TransformerResponse = processor.transformByTemplate(
                    source_text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    template=template,
                    context=context
                )
            else:
                result: TransformerResponse = processor.transform(
                    source_text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    context=context
                )

            # Erstelle standardisierte Response
            response = {
                'status': 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_text': _truncate_text(source_text),
                        'source_language': source_language,
                        'target_language': target_language,
                        'template': template,
                        'context': context
                    }
                },
                'process': result.process.to_dict(),  # Nutze die to_dict() Methode von ProcessInfo
                'data': {
                    'input': result.data.input.to_dict() if result.data and result.data.input else {},
                    'output': result.data.output.to_dict() if result.data and result.data.output else {}
                }
            }

            return response

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
                        'context': data.get('context', {})
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
                        'row_count': data.get('row_count')
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

@api.route('/manage-audio-cache')
class AudioCacheEndpoint(Resource):
    @api.expect(api.model('DeleteCacheInput', {
        'filename': fields.String(required=False, description='Name der Datei deren Cache gelöscht werden soll'),
        'max_age_days': fields.Integer(required=False, default=7, description='Maximales Alter in Tagen für den automatischen Cleanup'),
        'delete_transcripts': fields.Boolean(required=False, default=False, description='Wenn True, werden auch die Transkriptionen gelöscht, sonst nur die Segmente')
    }))
    def delete(self):
        """
        Löscht Cache-Verzeichnisse für Audio-Verarbeitungen.
        
        Wenn filename angegeben ist, wird nur der Cache für diese Datei gelöscht.
        Wenn max_age_days angegeben ist, werden alle Cache-Verzeichnisse gelöscht die älter sind.
        Wenn delete_transcripts True ist, werden auch die Transkriptionen gelöscht, sonst nur die Segmente.
        """
        tracker = get_performance_tracker()
        
        try:
            data = request.get_json() or {}
            filename = data.get('filename')
            max_age_days = data.get('max_age_days', 7)
            delete_transcripts = data.get('delete_transcripts', False)
            
            # Initialisiere AudioProcessor mit der Tracker process_id
            audio_processor = get_audio_processor(tracker.process_id)
            
            if filename:
                audio_processor.delete_cache(filename, delete_transcript=delete_transcripts)
                msg = 'komplett' if delete_transcripts else 'Segmente'
                logger.info("Cache für spezifische Datei gelöscht", 
                          filename=filename, 
                          delete_transcripts=delete_transcripts)
                return {'message': f'Cache für {filename} wurde {msg} gelöscht'}
            else:
                audio_processor.cleanup_cache(max_age_days, delete_transcripts=delete_transcripts)
                msg = 'komplett' if delete_transcripts else 'Segmente'
                logger.info("Alte Cache-Verzeichnisse gelöscht", 
                          max_age_days=max_age_days, 
                          delete_transcripts=delete_transcripts)
                return {'message': f'Alte Cache-Verzeichnisse (>{max_age_days} Tage) wurden {msg} gelöscht'}
                
        except Exception as e:
            logger.error("Cache-Management Fehler",
                        error=str(e),
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            return {'error': str(e)}, 500

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

async def process_file(uploaded_file: FileStorage, source_info: Dict[str, Any], source_language: str = 'de', target_language: str = 'de', template: str = '') -> Dict[str, Any]:
    """
    Verarbeitet eine hochgeladene Datei.
    
    Args:
        uploaded_file: Die hochgeladene Datei
        source_language: Die Quellsprache der Audio-Datei
        target_language: Die Zielsprache für die Verarbeitung
        template: Optional Template für die Verarbeitung
        
    Returns:
        Dict mit den Verarbeitungsergebnissen
    
    Raises:
        ProcessingError: Wenn die Verarbeitung fehlschlägt
    """
    if not uploaded_file:
        raise ProcessingError("Keine Datei hochgeladen")
        
    # Erstelle temporäre Datei
    temp_file = None
    try:
        # Speichere Upload in temporärer Datei
        temp_file: tempfile._TemporaryFileWrapper[bytes] = tempfile.NamedTemporaryFile(delete=False)
        uploaded_file.save(temp_file.name)
        
        # Verarbeite die Datei
        process_id = str(uuid.uuid4())
        processor: AudioProcessor = get_audio_processor(process_id)
        result: AudioResponse = await processor.process(
            audio_source=temp_file.name,
            source_info=source_info,
            source_language=source_language,
            target_language=target_language,
            template=template
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
                
                # Response erstellen
                response: MetadataEndpointResponse = {
                    'status': 'error' if result.error else 'success',
                    'request': {
                        'processor': 'metadata',
                        'timestamp': datetime.now().isoformat(),
                        'parameters': {
                            'has_file': uploaded_file is not None,
                            'has_content': content is not None,
                            'context': context
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
                    return cast(Dict[str, Any], response), 400
                
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