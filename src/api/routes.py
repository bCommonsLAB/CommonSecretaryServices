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
    return TransformerProcessor(process_id=process_id)

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

@api.route('/transform-text')
class TextTransformEndpoint(Resource):
    @api.expect(api.model('TransformTextInput', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'source_language': fields.String(default='en', description='Quellsprache (ISO 639-1 code, z.B. "en", "de")'),
        'target_language': fields.String(default='en', description='Zielsprache (ISO 639-1 code, z.B. "en", "de")'),
        'summarize': fields.Boolean(default=False, description='Text zusammenfassen'),
        'target_format': fields.String(default='text', enum=['text', 'html', 'markdown'], description='Ausgabeformat des transformierten Texts')
    }))
    @api.response(200, 'Erfolg', api.model('TransformTextResponse', {
        'text': fields.String(description='Transformierter Text'),
        'source_text': fields.String(description='Ursprünglicher Text'),
        'translation_model': fields.String(description='Verwendetes Übersetzungsmodell'),
        'token_count': fields.Integer(description='Anzahl der verwendeten Tokens'),
        'format': fields.String(description='Verwendetes Ausgabeformat'),
        'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking')
    }))
    def post(self):
        """Text transformieren"""
        data = request.get_json()
        tracker = get_performance_tracker()
        
        try:
            transformer_processor = get_transformer_processor(tracker.process_id)
            result = transformer_processor.transform(
                source_text=data['text'],
                source_language=data.get('source_language', 'en'),
                target_language=data.get('target_language', 'en'),
                summarize=data.get('summarize', False),
                target_format=data.get('target_format', 'text')
            )

            # Füge Ressourcenverbrauch zum Tracker hinzu
            tracker.eval_result(result)
            return result.to_dict()
            
        except Exception as e:
            logger.error("Text-Transformationsfehler", 
                        error=str(e))
            raise

@api.route('/transform-template')
class TemplateTransformEndpoint(Resource):
    @api.expect(api.model('TransformTemplateInput', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'target_language': fields.String(default='de', description='Zielsprache (ISO 639-1 code, z.B. "en", "de")'),
        'template': fields.String(required=True, description='Name des Templates (ohne .md Endung)'),
        'context': fields.String(required=False, description='Kontextinformationen für die Template-Verarbeitung')
    }))
    @api.response(200, 'Erfolg', api.model('TransformTemplateResponse', {
        'text': fields.String(description='Transformierter Template-Text'),
        'source_text': fields.String(description='Ursprünglicher Text'),
        'template_used': fields.String(description='Verwendetes Template'),
        'translation_model': fields.String(description='Verwendetes Übersetzungsmodell'),
        'token_count': fields.Integer(description='Anzahl der verwendeten Tokens'),
        'structured_data': fields.Raw(description='Strukturierte Daten aus der Template-Verarbeitung'),
        'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking')
    }))
    def post(self):
        """Text mit Template transformieren"""
        data = request.get_json()
        tracker = get_performance_tracker()
        
        try:
            transformer_processor = get_transformer_processor(tracker.process_id)
            result = transformer_processor.transformByTemplate(
                source_text=data['text'],
                source_language=data.get('source_language', ''),
                target_language=data.get('target_language', 'de'),
                template=data['template'],
                context=data['context']
            )
            # Füge Ressourcenverbrauch zum Tracker hinzu
            tracker.eval_result(result)
            return result.to_dict()
            
        except Exception as e:
            logger.error("Template-Transformationsfehler", 
                        error=str(e))
            raise

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
    'created': fields.DateTime(description='Erstellungszeitpunkt'),
    'modified': fields.DateTime(description='Letzter Änderungszeitpunkt'),
    'title': fields.String(description='Titel des Werks'),
    'subtitle': fields.String(description='Untertitel des Werks', required=False),
    'authors': fields.List(fields.String, description='Liste der Autoren'),
    'language': fields.String(description='Sprache (ISO 639-1)'),
    'keywords': fields.List(fields.String, description='Schlüsselwörter', required=False),
    'abstract': fields.String(description='Kurzzusammenfassung', required=False)
})

metadata_response = api.model('MetadataResponse', {
    'technical': fields.Nested(metadata_technical, description='Technische Metadaten'),
    'content': fields.Nested(metadata_content, description='Inhaltliche Metadaten'),
    'process_id': fields.String(description='Eindeutige Prozess-ID für Tracking')
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
    async def post(self):
        """Extrahiert Metadaten aus einer Datei."""
        try:
            # Performance Tracking
            process_id = str(uuid.uuid4())
            tracker = get_performance_tracker(process_id)
            
            args = metadata_upload_parser.parse_args()
            file = args['file']
            
            # Rate Limiting und Validierung
            await rate_limiter.check_rate_limit(request)
            rate_limiter.check_file_size(file)
            
            # Parse optionalen Kontext
            context = {}
            if args.get('context'):
                try:
                    context = json.loads(args['context'])
                except json.JSONDecodeError:
                    raise ProcessingError("Ungültiger JSON-Kontext")
            
            # Verarbeite Datei
            processor = get_metadata_processor(process_id)
            result = await processor.extract_metadata(
                binary_data=file,
                content=args.get('content'),
                context=context
            )
            
            return result.to_dict()
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            raise e
        except Exception as e:
            logger.error("Fehler bei der Metadaten-Extraktion",
                        error=str(e),
                        traceback=traceback.format_exc())
            raise ProcessingError(f"Fehler bei der Metadaten-Extraktion: {str(e)}")