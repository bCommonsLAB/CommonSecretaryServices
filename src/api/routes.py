from flask import Blueprint, request, jsonify, current_app, send_from_directory, redirect, url_for
from flask_restx import Api, Resource, fields, reqparse
import tempfile
import os
from pathlib import Path
import traceback
import asyncio
import werkzeug.datastructures
from typing import Union
import uuid
import json
from datetime import datetime
import time

from src.core.rate_limiting import RateLimiter
from src.core.resource_tracking import ResourceCalculator
from src.processors.pdf_processor import PDFProcessor
from src.processors.image_processor import ImageProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.processors.audio_processor import AudioProcessor
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.utils.logger import get_logger
from src.processors.transformer_processor import TransformerProcessor
from src.utils.performance_tracker import get_performance_tracker, clear_performance_tracker
from src.processors.metadata_processor import MetadataProcessor

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
audio_ns = api.namespace('audio', description='Audio-Verarbeitungs-Operationen')
youtube_ns = api.namespace('youtube', description='YouTube-Verarbeitungs-Operationen')
metadata_ns = api.namespace('metadata', description='Metadaten-Verarbeitungs-Operationen')

logger = get_logger(process_id="api")

# Initialisierung der gemeinsam genutzten Komponenten
resource_calculator = ResourceCalculator()
rate_limiter = RateLimiter(
    requests_per_hour=100,
    max_file_size=50 * 1024 * 1024  # 50MB
)

@blueprint.before_request
def setup_request():
    """
    Bereitet die Request-Verarbeitung vor.
    Initialisiert den Performance-Tracker für den Request.
    """
    process_id = str(uuid.uuid4())
    tracker = get_performance_tracker(process_id)
    
    # Setze Endpoint-Informationen
    endpoint = request.endpoint or 'unknown'
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'unknown')
    tracker.set_endpoint_info(endpoint, ip, user_agent)

@blueprint.after_request
def cleanup_request(response):
    """
    Räumt nach der Request-Verarbeitung auf.
    Schließt den Performance-Tracker ab und entfernt ihn.
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
def handle_error(error):
    """Globaler Fehlerhandler für alle Exceptions"""
    tracker = get_performance_tracker()
    if tracker:
        tracker.set_error(str(error))
    
    logger.error("API Fehler",
                error=str(error),
                error_type=error.__class__.__name__,
                endpoint=request.endpoint,
                ip=request.remote_addr)
    return {'error': str(error)}, 500

def get_pdf_processor(process_id: str = None):
    """Get or create PDF processor instance with process ID"""
    return PDFProcessor(resource_calculator, process_id=process_id)

def get_image_processor(process_id: str = None):
    """Get or create image processor instance with process ID"""
    return ImageProcessor(resource_calculator, process_id=process_id)

def get_youtube_processor(process_id: str = None):
    """Get or create Youtube processor instance with process ID"""
    return YoutubeProcessor(resource_calculator, process_id=process_id)

def get_audio_processor(process_id: str = None):
    """Get or create audio processor instance with process ID"""
    return AudioProcessor(resource_calculator, process_id=process_id)

def get_transformer_processor(process_id: str = None):
    """Get or create transformer processor instance with process ID"""
    return TransformerProcessor(resource_calculator, process_id=process_id)

def get_metadata_processor(process_id: str = None):
    """Get or create metadata processor instance with process ID"""
    return MetadataProcessor(resource_calculator, process_id=process_id)

# Parser für File-Uploads
file_upload = reqparse.RequestParser()
file_upload.add_argument('file', 
                        type='FileStorage', 
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
                          type=werkzeug.datastructures.FileStorage,
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

@blueprint.before_request
def check_rate_limit():
    """Prüft das Rate Limit vor jeder Anfrage"""
    ip = request.remote_addr
    endpoint = request.endpoint
    
    if not rate_limiter.is_allowed(ip):
        logger.warning("Rate Limit überschritten", ip=ip, endpoint=endpoint)
        raise RateLimitExceeded("Rate Limit überschritten")

@api.errorhandler(ProcessingError)
@api.errorhandler(FileSizeLimitExceeded)
@api.errorhandler(RateLimitExceeded)
def handle_processing_error(error):
    """Globaler Fehlerhandler für Verarbeitungsfehler"""
    logger.error("API Fehler",
                error=str(error),
                error_type=error.__class__.__name__,
                endpoint=request.endpoint,
                ip=request.remote_addr)
    return {'error': str(error)}, 400

@api.route('/process-pdf')
class PDFEndpoint(Resource):
    @api.expect(file_upload)
    @api.response(200, 'Erfolg', pdf_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet eine PDF-Datei und extrahiert Informationen')
    async def post(self):
        tracker = get_performance_tracker()
        try:
            with tracker.measure_operation('pdf_processing', 'PDFProcessor'):
                args = file_upload.parse_args()
                uploaded_file = args['file']
                
                # Verarbeitung der PDF-Datei
                processor = get_pdf_processor(tracker.process_id)
                result = await processor.process(uploaded_file)
                
                # Füge Ressourcenverbrauch zum Tracker hinzu
                tracker.eval_result(result)
                
                return result.to_dict()
                
        except Exception as e:
            logger.error("Fehler bei der PDF-Verarbeitung", error=str(e))
            logger.error(traceback.format_exc())
            raise

@api.route('/process-image')
class ImageEndpoint(Resource):
    @api.expect(file_upload)
    @api.response(200, 'Erfolg', image_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Bild und extrahiert Informationen')
    async def post(self):
        """Bild verarbeiten"""
        args = file_upload.parse_args()
        file = args['file']
        image_processor = None
        tracker = get_performance_tracker()
        
        if not any(file.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return {'error': 'Nur PNG/JPG Dateien erlaubt'}, 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
            file.save(temp_file.name)
            try:
                image_processor = get_image_processor(tracker.process_id)
                result = await image_processor.process(temp_file.name)
                
                # Füge Ressourcenverbrauch zum Tracker hinzu
                tracker.eval_result(result)
                
                return result.to_dict()
            except Exception as e:
                logger.error("Bild-Verarbeitungsfehler", error=str(e))
                raise
            finally:
                os.unlink(temp_file.name)
                if image_processor:
                    image_processor.logger.info("Bild-Verarbeitung beendet")

@api.route('/process-youtube')
class YoutubeEndpoint(Resource):
    # Definiere das Request-Model für Swagger
    youtube_request = api.model('YoutubeRequest', {
        'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='Youtube Video URL'),
        'target_language': fields.String(required=True, default='de', description='Zielsprache (ISO 639-1 code)'),
        'template': fields.String(required=False, default='Youtube', description='Template-Name (ohne .md Endung)')
    })

    @api.expect(youtube_request)
    def post(self):
        """Verarbeitet ein Youtube-Video"""
        youtube_processor = None
        tracker = get_performance_tracker()
        
        try:
            data = request.get_json()
            url = data.get('url')
            target_language = data.get('target_language', 'de')
            template = data.get('template')

            if not url:
                raise ValueError("Youtube-URL ist erforderlich")

            youtube_processor = get_youtube_processor(tracker.process_id)
            result = asyncio.run(youtube_processor.process(
                file_path=url,
                target_language=target_language,
                template=template
            ))
            # Füge Ressourcenverbrauch zum Tracker hinzu
            tracker.eval_result(result)
            
            # Konvertiere das Pydantic Model in ein Dictionary für die API-Antwort
            return result.to_dict()
            
        except ValueError as ve:
            logger.error("Validierungsfehler",
                        error=str(ve),
                        error_type="ValidationError",
                        process_id=tracker.process_id if tracker else None)
            raise
        except Exception as e:
            logger.error("Youtube-Verarbeitungsfehler",
                        error=str(e),
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        process_id=tracker.process_id if tracker else None)
            raise
        finally:
            if youtube_processor:
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
    def post(self):
        """Audio-Datei verarbeiten"""
        temp_file = None
        audio_processor = None
        tracker = get_performance_tracker()
        
        try:
            args = upload_parser.parse_args()
            file = args['file']
            target_language = args['target_language']
            template = args['template']
            
            if not any(file.filename.lower().endswith(ext) for ext in ['.mp3', '.wav', '.m4a']):
                return {'error': 'Nur MP3/WAV/M4A Dateien erlaubt'}, 400
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
            file.save(temp_file.name)
            temp_file.close()
            
            source_info = {
                'original_filename': file.filename
            }
            audio_processor = get_audio_processor(tracker.process_id)
            result = asyncio.run(audio_processor.process(
                temp_file.name,
                source_info=source_info,
                target_language=target_language,
                template=template
            ))
            
            # Füge Ressourcenverbrauch zum Tracker hinzu
            tracker.eval_result(result)
            
            # Konvertiere das Pydantic Model in ein Dictionary für die API-Antwort
            return result.to_dict()
            
        except Exception as e:
            logger.error("Audio-Verarbeitungsfehler",
                        error=str(e),
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        process_id=tracker.process_id if tracker else None)
            raise
        finally:
            if temp_file:
                self._safe_delete(temp_file.name)
            if audio_processor:
                audio_processor.logger.info("Audio-Verarbeitung beendet")

def _truncate_text(text: str, max_length: int = 50) -> str:
    """Kürzt einen Text auf die angegebene Länge und fügt '...' hinzu wenn gekürzt wurde."""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip() + "..."

def _convert_llms_to_requests(llms: list) -> list:
    """Konvertiert LLM-Modelle in das API-Response-Format."""
    if not llms:
        return []
    return [{
        'model': llm.model,
        'purpose': 'transformation',
        'tokens': llm.tokens,
        'duration': llm.duration,
        'timestamp': datetime.now().isoformat()
    } for llm in llms]

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
        data = request.get_json()
        tracker = get_performance_tracker()
        
        try:
            # Zeitmessung für Gesamtprozess starten
            process_start = time.time()
            
            transformer_processor = get_transformer_processor(tracker.process_id)
            result = transformer_processor.transform(
                source_text=data['text'],
                source_language=data.get('source_language', 'en'),
                target_language=data.get('target_language', 'en'),
                summarize=data.get('summarize', False),
                target_format=data.get('target_format', 'text')
            )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
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
                    'id': tracker.process_id,
                    'main_processor': 'transformer',
                    'sub_processors': ['openai'] if hasattr(result, 'llms') and result.llms else [],
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': process_duration,
                    'llm_info': {
                        'requests_count': len(result.llms) if hasattr(result, 'llms') else 0,
                        'total_tokens': sum(llm.tokens for llm in result.llms) if hasattr(result, 'llms') else 0,
                        'total_duration': sum(llm.duration for llm in result.llms) if hasattr(result, 'llms') else 0,
                        'requests': [{
                            'model': llm.model,
                            'purpose': 'transformation',
                            'tokens': llm.tokens,
                            'duration': llm.duration,
                            'timestamp': datetime.now().isoformat()
                        } for llm in (result.llms if hasattr(result, 'llms') else [])]
                    }
                },
                'data': {
                    'input': {
                        'text': data['text'],
                        'language': data.get('source_language', 'en')
                    },
                    'output': {
                        'text': result.text,
                        'language': result.target_language
                    }
                }
            }
            
            return response

        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            return {
                "status": "error",
                "error": {
                    "code": e.__class__.__name__,
                    "message": str(e)
                }
            }, 400
        except Exception as e:
            logger.error("Fehler bei der Text-Transformation",
                        error=str(e),
                        traceback=traceback.format_exc())
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError",
                    "message": f"Fehler bei der Text-Transformation: {str(e)}"
                }
            }, 400

@api.route('/transform-template')
class TemplateTransformEndpoint(Resource):
    @api.expect(api.model('TransformTemplateInput', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
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
    def post(self):
        """Text mit Template transformieren"""
        data = request.get_json()
        tracker = get_performance_tracker()
        
        try:
            # Zeitmessung für Gesamtprozess starten
            process_start = time.time()
            
            transformer_processor = get_transformer_processor(tracker.process_id)
            result = transformer_processor.transformByTemplate(
                source_text=data['text'],
                source_language=data.get('source_language', ''),
                target_language=data.get('target_language', 'de'),
                template=data['template'],
                context=data.get('context', {})
            )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            tracker.eval_result(result)
            
            # Erstelle TransformerResponse
            response = {
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
                    'id': tracker.process_id,
                    'main_processor': 'transformer',
                    'sub_processors': ['openai'] if hasattr(result, 'llms') and result.llms else [],
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': process_duration,
                    'llm_info': {
                        'requests_count': len(result.llms) if hasattr(result, 'llms') else 0,
                        'total_tokens': sum(llm.tokens for llm in result.llms) if hasattr(result, 'llms') else 0,
                        'total_duration': sum(llm.duration for llm in result.llms) if hasattr(result, 'llms') else 0,
                        'requests': [{
                            'model': llm.model,
                            'purpose': 'template_transformation',
                            'tokens': llm.tokens,
                            'duration': llm.duration,
                            'timestamp': datetime.now().isoformat()
                        } for llm in (result.llms if hasattr(result, 'llms') else [])]
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
                        'text': result.text,
                        'language': result.target_language,
                        'structured_data': result.structured_data if hasattr(result, 'structured_data') else {}
                    }
                }
            }
            
            return response
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            return {
                "status": "error",
                "error": {
                    "code": e.__class__.__name__,
                    "message": str(e)
                }
            }, 400
        except Exception as e:
            logger.error("Fehler bei der Template-Transformation",
                        error=str(e),
                        traceback=traceback.format_exc())
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError",
                    "message": f"Fehler bei der Template-Transformation: {str(e)}"
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
    type=werkzeug.datastructures.FileStorage, 
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

@api.route('/extract-metadata')
class MetadataEndpoint(Resource):
    @api.expect(metadata_upload_parser)
    @api.response(200, 'Erfolg', metadata_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Extrahiert Metadaten aus einer Datei')
    def post(self):
        """Extrahiert Metadaten aus einer Datei."""
        temp_file = None
        try:
            # Performance Tracking
            process_id = str(uuid.uuid4())
            tracker = get_performance_tracker(process_id)
            
            args = metadata_upload_parser.parse_args()
            file = args['file']
            
            # Rate Limiting und Validierung
            if not rate_limiter.check_file_size(file.content_length):
                raise FileSizeLimitExceeded(f"Datei zu groß: {file.content_length} Bytes")
            
            # Parse optionalen Kontext
            context = {}
            if args.get('context'):
                try:
                    context = json.loads(args['context'])
                except json.JSONDecodeError:
                    raise ProcessingError("Ungültiger JSON-Kontext")
            
            # Speichere Datei temporär
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
            file.save(temp_file.name)
            temp_file.close()
            
            # Verarbeite Datei
            processor = get_metadata_processor(process_id)
            result = asyncio.run(processor.extract_metadata(
                binary_data=Path(temp_file.name),
                content=args.get('content'),
                context=context
            ))
            
            # Füge Ressourcenverbrauch zum Tracker hinzu
            tracker.eval_result(result)
            
            # Konvertiere das Pydantic Model in ein Dictionary für die API-Antwort
            response_data = result.to_dict()
            
            # Füge Transformer als Sub-Processor hinzu wenn Content-Metadaten vorhanden sind
            if response_data.get("data", {}).get("content_available"):
                if "sub_processors" not in response_data["process"]:
                    response_data["process"]["sub_processors"] = []
                response_data["process"]["sub_processors"].append("transformer")
            
            # Prüfe auf Fehler im Result
            if response_data.get("status") == "error":
                return response_data, 400
                
            return response_data
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            return {
                "status": "error",
                "error": {
                    "code": e.__class__.__name__,
                    "message": str(e)
                }
            }, 400
        except Exception as e:
            logger.error("Fehler bei der Metadaten-Extraktion",
                        error=str(e),
                        traceback=traceback.format_exc())
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError",
                    "message": f"Fehler bei der Metadaten-Extraktion: {str(e)}"
                }
            }, 400
        finally:
            # Räume temporäre Datei auf
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception as e:
                    logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")