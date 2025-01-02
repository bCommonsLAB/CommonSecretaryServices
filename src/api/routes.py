from flask import Blueprint, request, jsonify, current_app, send_from_directory, redirect, url_for
from flask_restx import Api, Resource, fields, reqparse
import tempfile
import os
from pathlib import Path
import traceback
import asyncio
import werkzeug.datastructures
from typing import Union

from src.core.rate_limiting import RateLimiter
from src.core.resource_tracking import ResourceCalculator
from src.processors.pdf_processor import PDFProcessor
from src.processors.image_processor import ImageProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.processors.audio_processor import AudioProcessor
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.utils.logger import get_logger
from src.processors.transformer_processor import TransformerProcessor

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

def get_pdf_processor():
    """Get or create PDF processor instance with unique process ID"""
    return PDFProcessor(resource_calculator)

def get_image_processor():
    """Get or create image processor instance with unique process ID"""
    return ImageProcessor(resource_calculator)

def get_youtube_processor():
    """Get or create YouTube processor instance with unique process ID"""
    return YoutubeProcessor(resource_calculator)

def get_audio_processor():
    """Get or create audio processor instance with unique process ID"""
    return AudioProcessor(resource_calculator)

def get_transformer_processor():
    """Get or create transformer processor instance with unique process ID"""
    return TransformerProcessor()

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

# Model für YouTube-URLs und Parameter
youtube_input = api.model('YouTubeInput', {
    'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='YouTube Video URL'),
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
    'metadata': fields.Raw(description='PDF Metadaten')
})

image_response = api.model('ImageResponse', {
    'dimensions': fields.Raw(description='Bildabmessungen (Breite x Höhe)'),
    'format': fields.String(description='Bildformat'),
    'metadata': fields.Raw(description='Bild Metadaten')
})

youtube_response = api.model('YouTubeResponse', {
    'title': fields.String(description='Video Titel'),
    'duration': fields.Integer(description='Video Länge in Sekunden'),
    'audio_extracted': fields.Boolean(description='Audio wurde extrahiert'),
    'transcript': fields.String(description='Transkribierter Text (wenn verfügbar)'),
    'summary': fields.String(description='Zusammenfassung (wenn angefordert)'),
    'metadata': fields.Raw(description='Video Metadaten')
})

audio_response = api.model('AudioResponse', {
    'duration': fields.Float(description='Audio Länge in Sekunden'),
    'format': fields.String(description='Audio Format'),
    'metadata': fields.Raw(description='Audio Metadaten')
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
        """PDF-Datei verarbeiten"""
        args = file_upload.parse_args()
        file = args['file']
        pdf_processor = None
        
        if not file.filename.lower().endswith('.pdf'):
            return {'error': 'Nur PDF-Dateien erlaubt'}, 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            file.save(temp_file.name)
            try:
                pdf_processor = get_pdf_processor()
                result = await pdf_processor.process(temp_file.name)
                return result
            finally:
                os.unlink(temp_file.name)
                if pdf_processor:
                    pdf_processor.logger.info("PDF-Verarbeitung beendet")

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
        
        if not any(file.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return {'error': 'Nur PNG/JPG Dateien erlaubt'}, 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
            file.save(temp_file.name)
            try:
                image_processor = get_image_processor()
                result = await image_processor.process(temp_file.name)
                return result
            finally:
                os.unlink(temp_file.name)
                if image_processor:
                    image_processor.logger.info("Bild-Verarbeitung beendet")

@api.route('/process-youtube')
class YouTubeProcessor(Resource):
    # Definiere das Request-Model für Swagger
    youtube_request = api.model('YouTubeRequest', {
        'url': fields.String(required=True, default='https://www.youtube.com/watch?v=jNQXAC9IVRw', description='YouTube Video URL'),
        'target_language': fields.String(required=True, default='de', description='Zielsprache (ISO 639-1 code)'),
        'template': fields.String(required=False, default='Youtube', description='Template-Name (ohne .md Endung)')
    })

    @api.expect(youtube_request)
    def post(self):
        """Verarbeitet ein YouTube-Video"""
        youtube_processor = None
        try:
            data = request.get_json()
            url = data.get('url')
            target_language = data.get('target_language', 'de')
            template = data.get('template')

            if not url:
                raise ValueError("YouTube-URL ist erforderlich")

            youtube_processor = get_youtube_processor()
            result = asyncio.run(youtube_processor.process(
                url=url,
                target_language=target_language,
                template=template
            ))
            return result
        except ValueError as ve:
            logger.error("Validierungsfehler",
                        error=str(ve),
                        error_type="ValidationError")
            return {'error': str(ve)}, 400
        except Exception as e:
            logger.error("YouTube-Verarbeitungsfehler",
                        error=str(e),
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            raise
        finally:
            if youtube_processor:
                youtube_processor.logger.info("YouTube-Verarbeitung beendet")

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
            audio_processor = get_audio_processor()
            result = asyncio.run(audio_processor.process(
                temp_file.name,
                source_info=source_info,
                target_language=target_language,
                template=template
            ))
            return result
        except Exception as e:
            logger.error("Audio-Verarbeitungsfehler",
                        error=str(e),
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
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
        'format': fields.String(description='Verwendetes Ausgabeformat')
    }))
    def post(self):
        """Text transformieren"""
        data = request.get_json()
        
        transformer_processor = get_transformer_processor()
        result = transformer_processor.transform(
            source_text=data['text'],
            source_language=data.get('source_language', 'en'),
            target_language=data.get('target_language', 'en'),
            summarize=data.get('summarize', False),
            target_format=data.get('target_format', 'text')
        )
        
        return result

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
        'structured_data': fields.Raw(description='Strukturierte Daten aus der Template-Verarbeitung')
    }))
    def post(self):
        """Text mit Template transformieren"""
        data = request.get_json()
        
        transformer_processor = get_transformer_processor()
        result = transformer_processor.transformByTemplate(
            source_text=data['text'],
            source_language=data.get('source_language', ''),
            target_language=data.get('target_language', 'de'),
            template=data['template'],
            context=data['context']
        )
        
        return result

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
        try:
            data = request.get_json() or {}
            filename = data.get('filename')
            max_age_days = data.get('max_age_days', 7)
            delete_transcripts = data.get('delete_transcripts', False)
            
            if filename:
                audio_processor = get_audio_processor()
                audio_processor.delete_cache(filename, delete_transcript=delete_transcripts)
                msg = 'komplett' if delete_transcripts else 'Segmente'
                return {'message': f'Cache für {filename} wurde {msg} gelöscht'}
            else:
                audio_processor = get_audio_processor()
                audio_processor.cleanup_cache(max_age_days, delete_transcripts=delete_transcripts)
                msg = 'komplett' if delete_transcripts else 'Segmente'
                return {'message': f'Alte Cache-Verzeichnisse (>{max_age_days} Tage) wurden {msg} gelöscht'}
                
        except Exception as e:
            logger.error("Cache-Verwaltungsfehler",
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