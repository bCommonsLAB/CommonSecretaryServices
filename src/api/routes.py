import os
import tempfile
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Union, cast

import werkzeug.datastructures
from flask import Blueprint, request
from flask_restx import (Api, Namespace, Resource, fields,  # type: ignore
                         reqparse)

from core.models.transformer import TransformerResponse
from src.api.models.responses import ProcessInfo
from src.core.exceptions import (FileSizeLimitExceeded, ProcessingError,
                                 RateLimitExceeded)
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.transformer import TransformerResponse
from src.core.rate_limiting import RateLimiter
from src.processors.audio_processor import (AudioProcessingResult,
                                            AudioProcessor)
from src.processors.image_processor import ImageProcessor
from src.processors.metadata_processor import (ContentMetadata,
                                               MetadataProcessor,
                                               MetadataResponse,
                                               TechnicalMetadata)
from src.processors.pdf_processor import PDFProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.utils.logger import ProcessingLogger, get_logger
from src.utils.performance_tracker import (clear_performance_tracker,
                                           get_performance_tracker)
from src.utils.resource_calculator import ResourceCalculator
from utils.performance_tracker import PerformanceTracker

# Typ-Alias für bessere Lesbarkeit
FileStorage = werkzeug.datastructures.FileStorage


class ProcessResponse(TypedDict):
    status: str
    request: Dict[str, Any]
    process: ProcessInfo
    data: Dict[str, Any]
    error: Optional[Dict[str, Any]]

# Blueprint erstellen
blueprint = Blueprint('api', __name__)

api = Api(blueprint,
    title='Processing Service API',
    version='1.0',
    description='API für verschiedene Verarbeitungsdienste',
    doc='/',
    prefix=''
)

# API Namespaces definieren
audio_ns: Namespace = api.namespace('audio', description='Audio-Verarbeitungs-Operationen')
youtube_ns: Namespace = api.namespace('youtube', description='YouTube-Verarbeitungs-Operationen')
metadata_ns: Namespace = api.namespace('metadata', description='Metadaten-Verarbeitungs-Operationen')

logger: ProcessingLogger = get_logger(process_id="api")

# Initialisierung der gemeinsam genutzten Komponenten
resource_calculator = ResourceCalculator()
rate_limiter = RateLimiter(
    requests_per_hour=100,
    max_file_size=50 * 1024 * 1024  # 50MB
)

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
def cleanup_request(response: werkzeug.wrappers.Response) -> werkzeug.wrappers.Response:
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
    tracker = get_performance_tracker()
    if tracker:
        tracker.set_error(error)
    
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
file_upload.add_argument('file', 
                        type=FileStorage, 
                        location='files', 
                        required=True,
                        help='Die zu verarbeitende Datei')
file_upload.add_argument('target_language',
                        type=str,
                        location='form',
                        default='en',
                        help='Sprache der Audio-Datei',
                        trim=True)
file_upload.add_argument('template',
                        type=str,
                        location='form',
                        default='',
                        help='Vorlage für die Verarbeitung',
                        trim=True)

# Model für Youtube-URLs und Parameter
youtube_input = api.model('YoutubeInput', {
    'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
    'extract_audio': fields.Boolean(required=False, default=True, description='Audio extrahieren'),
    'target_language': fields.String(required=False, default='de', description='Sprache des Videos (ISO 639-1 code)'),
    'template': fields.String(required=False, default='Youtube', description='Vorlage für die Verarbeitung')
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
    'title': fields.String(description='Video Titel'),
    'duration': fields.Integer(description='Video Länge in Sekunden'),
    'audio_extracted': fields.Boolean(description='Audio wurde extrahiert'),
    'transcript': fields.String(description='Transkribierter Text (wenn verfügbar)'),
    'summary': fields.String(description='Zusammenfassung (wenn angefordert)'),
    'metadata': fields.Raw(description='Video Metadaten'),
    'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking')
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
upload_parser.add_argument('target_language',
                          type=str,
                          location='form',
                          default='en',
                          help='Target language (e.g., "en", "de")')
upload_parser.add_argument('template',
                          type=str,
                          location='form',
                          default='',
                          help='Vorlage für die Verarbeitung')

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
    async def post(self) -> ProcessResponse:
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
    async def post(self) -> Union[ProcessResponse, tuple[Dict[str, str], int]]:
        """Bild verarbeiten"""
        args = file_upload.parse_args()  # type: ignore
        uploaded_file = cast(FileStorage, args['file'])
            
        if not uploaded_file.filename:
            raise ProcessingError("Kein Dateiname angegeben")
            
        image_processor = None
        tracker = get_performance_tracker()
        process_id = str(uuid.uuid4())
        temp_file = None
        
        if not any(uploaded_file.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return {'error': 'Nur PNG/JPG Dateien erlaubt'}, 400
        
        try:
            # Speichere Datei temporär
            suffix = Path(uploaded_file.filename).suffix
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
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
    youtube_request = api.model('YoutubeRequest', {  # type: ignore
        'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
        'target_language': fields.String(required=True, default='de', description='Zielsprache (ISO 639-1 code)'),
        'template': fields.String(required=False, default='Youtube', description='Template-Name (ohne .md Endung)')
    })

    @api.expect(youtube_request)  # type: ignore
    async def post(self) -> Dict[str, Any]:
        """Verarbeitet ein Youtube-Video"""
        youtube_processor = None
        process_id = str(uuid.uuid4())
        tracker = get_performance_tracker() or get_performance_tracker(process_id)
        
        try:
            data = request.get_json()
            if not data:
                raise ProcessingError("Keine Daten erhalten")
                
            url = data.get('url')
            target_language = data.get('target_language', 'de')
            template = data.get('template')

            if not url:
                raise ProcessingError("Youtube-URL ist erforderlich")

            youtube_processor = get_youtube_processor(process_id)
            result = await youtube_processor.process(
                file_path=url,
                target_language=target_language,
                template=template
            )
            
            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker and hasattr(tracker, 'eval_result'):
                result_dict = result.to_dict()
                result_dict['eval_result'] = tracker.eval_result
                return result_dict
            
            return result.to_dict()
            
        except ValueError as ve:
            logger.error("Validierungsfehler",
                        error=ve,
                        error_type="ValidationError",
                        process_id=process_id)
            return {'error': str(ve)}, 400
        except Exception as e:
            logger.error("Youtube-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        process_id=process_id)
            return {'error': str(e)}, 400
        finally:
            if youtube_processor and youtube_processor.logger:
                youtube_processor.logger.info("Youtube-Verarbeitung beendet")

@api.route('/process-audio')
class AudioEndpoint(Resource):
    def _safe_delete(self, file_path: Union[str, Path]) -> None:
        """Löscht eine Datei sicher und ignoriert Fehler wenn die Datei nicht gelöscht werden kann."""
        try:
            if file_path and os.path.exists(str(file_path)):
                os.unlink(str(file_path))
        except Exception as e:
            logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")

    @api.expect(upload_parser)
    @api.response(200, 'Erfolg', audio_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet eine Audio-Datei')
    async def post(self) -> Dict[str, Any]:
        """
        Verarbeitet eine Audio-Datei.
        """
        args = upload_parser.parse_args()
        uploaded_file = args.get('file')
        target_language = args.get('target_language', 'de')
        template = args.get('template', '')
        
        # Erstelle einen neuen Tracker wenn keiner existiert
        process_id = str(uuid.uuid4())
        tracker = get_performance_tracker() or get_performance_tracker(process_id)
            
        try:
            result = await process_file(uploaded_file, target_language, template)
            if tracker and hasattr(tracker, 'process_id'):
                result['process_id'] = tracker.process_id
            return result
            
        except Exception as e:
            logger.error("Fehler bei der Audio-Verarbeitung",
                        error=e,
                        error_type=type(e).__name__,
                        target_language=target_language)
            raise ProcessingError(f"Fehler bei der Audio-Verarbeitung: {str(e)}")

def _truncate_text(text: str, max_length: int = 50) -> str:
    """Kürzt einen Text auf die angegebene Länge und fügt '...' hinzu wenn gekürzt wurde."""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."

def _convert_llms_to_requests(requests: List[LLMRequest]) -> List[Dict[str, Any]]:
    """Konvertiert LLM-Requests in das API-Response-Format."""
    if not requests:
        return []
    return [{
        'model': req.model,
        'purpose': req.purpose,
        'tokens': req.tokens,
        'duration': req.duration,
        'timestamp': datetime.now().isoformat()
    } for req in requests]

@api.route('/transform-text')
class TextTransformEndpoint(Resource):
    @api.expect(api.model('TransformTextInput', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'source_language': fields.String(default='en', description='Quellsprache (ISO 639-1 code, z.B. "en", "de")'),
        'target_language': fields.String(default='en', description='Zielsprache (ISO 639-1 code, z.B. "en", "de")'),
        'summarize': fields.Boolean(default=False, description='Text zusammenfassen'),
        'target_format': fields.String(default='text', enum=['text', 'html', 'markdown'], description='Ausgabeformat des transformierten Texts')
    }))
    @api.response(200, 'Erfolg', api.model('TransformerResponse', {
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
            'llm_info': fields.Nested(api.model('LLMInfo', {
                'requests_count': fields.Integer(description='Anzahl der LLM-Anfragen'),
                'total_tokens': fields.Integer(description='Gesamtanzahl der Tokens'),
                'total_duration': fields.Float(description='Gesamtdauer in Millisekunden'),
                'requests': fields.List(fields.Nested(api.model('LLMRequest', {
                    'model': fields.String(description='Name des verwendeten Modells'),
                    'purpose': fields.String(description='Zweck der Anfrage'),
                    'tokens': fields.Integer(description='Anzahl der verwendeten Tokens'),
                    'duration': fields.Float(description='Verarbeitungsdauer in Sekunden'),
                    'timestamp': fields.String(description='Zeitstempel der LLM-Nutzung')
                })))
            }))
        })),
        'data': fields.Raw(description='Transformationsergebnis'),
        'error': fields.Nested(api.model('ErrorInfo', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    def post(self):
        """Text transformieren"""
        data: Any = request.get_json()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            # Zeitmessung für Gesamtprozess starten
            process_start: float = time.time()
            
            transformer_processor: TransformerProcessor = get_transformer_processor(tracker.process_id if tracker else None)
            result: TransformerResponse = transformer_processor.transform(
                source_text=data['text'],
                source_language=data.get('source_language', 'en'),
                target_language=data.get('target_language', 'en'),
                summarize=data.get('summarize', False),
                target_format=data.get('target_format', 'text')
            )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker:
                tracker.eval_result(result)
            
            # Erstelle TransformerResponse
            response = {
                'status': 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_text': _truncate_text(data['text']),
                        'source_language': data.get('source_language', 'en'),
                        'target_language': data.get('target_language', 'en'),
                        'summarize': data.get('summarize', False),
                        'target_format': data.get('target_format', 'text')
                    }
                },
                'process': {
                    'id': tracker.process_id if tracker else None,
                    'main_processor': 'transformer',
                    'sub_processors': ['openai'] if hasattr(result, 'llm_info') and result.llm_info else [],
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': process_duration,
                    'llm_info': {
                        'requests_count': len(result.llm_info.requests) if hasattr(result, 'llm_info') and result.llm_info else 0,
                        'total_tokens': sum(req.tokens for req in result.llm_info.requests) if hasattr(result, 'llm_info') and result.llm_info else 0,
                        'total_duration': sum(req.duration for req in result.llm_info.requests) if hasattr(result, 'llm_info') and result.llm_info else 0,
                        'requests': _convert_llms_to_requests(result.llm_info.requests if hasattr(result, 'llm_info') and result.llm_info else [])
                    }
                },
                'data': {
                    'input': {
                        'text': result.data.input.text,
                        'language': result.data.input.language
                    },
                    'output': {
                        'text': result.data.output.text,
                        'language': result.data.output.language
                    }
                }
            }
            
            return response

        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            return {
                "status": "error",
                "error": {
                    "code": error.__class__.__name__,
                    "message": str(error)
                }
            }, 400
        except Exception as error:
            logger.error(
                "Fehler bei der Text-Transformation",
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError", 
                    "message": f"Fehler bei der Text-Transformation: {error}"
                }
            }, 400

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
            'llm_info': fields.Nested(api.model('LLMInfo', {
                'requests_count': fields.Integer(description='Anzahl der LLM-Anfragen'),
                'total_tokens': fields.Integer(description='Gesamtanzahl der Tokens'),
                'total_duration': fields.Float(description='Gesamtdauer in Millisekunden'),
                'requests': fields.List(fields.Nested(api.model('LLMRequest', {
                    'model': fields.String(description='Name des verwendeten Modells'),
                    'purpose': fields.String(description='Zweck der Anfrage'),
                    'tokens': fields.Integer(description='Anzahl der verwendeten Tokens'),
                    'duration': fields.Float(description='Verarbeitungsdauer in Sekunden'),
                    'timestamp': fields.String(description='Zeitstempel der LLM-Nutzung')
                })))
            }))
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

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker:
                tracker.eval_result(result)
            
            # Erstelle TransformerResponse
            response: Dict[str, Any] = {
                'status': 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_text': _truncate_text(data['text']),
                        'source_language': data.get('source_language', ''),
                        'target_language': data.get('target_language', 'de'),
                        'template': data['template'],
                        'context': data.get('context', {})
                    }
                },
                'process': {
                    'id': tracker.process_id if tracker else None,
                    'main_processor': 'transformer',
                    'sub_processors': ['openai'] if hasattr(result, 'llm_info') and result.llm_info else [],
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': process_duration,
                    'llm_info': {
                        'requests_count': len(result.llm_info.requests) if hasattr(result, 'llm_info') and result.llm_info else 0,
                        'total_tokens': sum(req.tokens for req in result.llm_info.requests) if hasattr(result, 'llm_info') and result.llm_info else 0,
                        'total_duration': sum(req.duration for req in result.llm_info.requests) if hasattr(result, 'llm_info') and result.llm_info else 0,
                        'requests': _convert_llms_to_requests(result.llm_info.requests if hasattr(result, 'llm_info') and result.llm_info else [])
                    }
                },
                'data': {
                    'input': {
                        'text': data['text'],
                        'language': data.get('source_language', ''),
                        'template': data['template'],
                        'context': data.get('context', {})
                    },
                    'output': {
                        'text': result.data.output.text,
                        'language': result.data.output.language,
                        'structured_data': result.data.output.structured_data if hasattr(result.data.output, 'structured_data') else {}
                    }
                }
            }
            
            return response
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            return {
                "status": "error",
                "error": {
                    "code": error.__class__.__name__,
                    "message": str(error),
                    "details": {}
                }
            }, 400
        except Exception as error:
            logger.error(
                "Fehler bei der Template-Transformation",
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError", 
                    "message": f"Fehler bei der Template-Transformation: {error}",
                    "details": {}
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

async def process_file(uploaded_file: FileStorage, target_language: str = 'de', template: str = '') -> Dict[str, Any]:
    """
    Verarbeitet eine hochgeladene Datei.
    
    Args:
        uploaded_file: Die hochgeladene Datei
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
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        uploaded_file.save(temp_file.name)
        
        # Verarbeite die Datei
        process_id = str(uuid.uuid4())
        processor = get_audio_processor(process_id)
        result: AudioProcessingResult = await processor.process(
            file_path=temp_file.name,
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
    @api.doc(description='Extrahiert Metadaten aus einer Datei')
    async def post(self) -> Dict[str, Any]:
        """
        Extrahiert Metadaten aus einer Datei.
        """
        args = metadata_upload_parser.parse_args()
        uploaded_file = args.get('file')
        
        # Erstelle einen neuen Tracker wenn keiner existiert
        process_id = str(uuid.uuid4())
        tracker = get_performance_tracker() or get_performance_tracker(process_id)
            
        try:
            processor: MetadataProcessor = get_metadata_processor(process_id)
            result: MetadataResponse = await processor.process(uploaded_file)
            
            result_dict = result.to_dict()
            if tracker and hasattr(tracker, 'eval_result'):
                result_dict['eval_result'] = tracker.eval_result
            return result_dict
            
        except Exception as e:
            logger.error("Fehler bei der Metadaten-Extraktion",
                        error=e,
                        error_type=type(e).__name__)
            raise ProcessingError(f"Fehler bei der Metadaten-Extraktion: {str(e)}")