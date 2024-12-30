from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_restx import Api, Resource, fields, reqparse
import tempfile
import os
from pathlib import Path
import traceback
import asyncio

from src.core.rate_limiting import RateLimiter
from src.core.resource_tracking import ResourceCalculator
from src.processors.pdf_processor import PDFProcessor
from src.processors.image_processor import ImageProcessor
from src.processors.youtube_processor import YoutubeProcessor
from src.processors.audio_processor import AudioProcessor
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.utils.logger import ProcessingLogger

# Blueprint erstellen
blueprint = Blueprint('api', __name__)
api = Api(blueprint,
    title='Processing Service API',
    version='1.0',
    description='API für verschiedene Verarbeitungsdienste',
    doc='/',
    prefix=''
)

logger = ProcessingLogger(process_id="api")

# Initialisierung der gemeinsam genutzten Komponenten
resource_calculator = ResourceCalculator()
rate_limiter = RateLimiter(
    requests_per_hour=100,
    max_file_size=50 * 1024 * 1024  # 50MB
)

# Prozessor-Instanzen
pdf_processor = PDFProcessor(resource_calculator, max_file_size=100 * 1024 * 1024)
image_processor = ImageProcessor(resource_calculator, max_file_size=50 * 1024 * 1024)
youtube_processor = YoutubeProcessor(resource_calculator, max_file_size=100 * 1024 * 1024)
audio_processor = AudioProcessor(resource_calculator, max_file_size=50 * 1024 * 1024)

# Parser für File-Uploads
file_upload = reqparse.RequestParser()
file_upload.add_argument('file', 
                        type='FileStorage', 
                        location='files', 
                        required=True,
                        help='Die zu verarbeitende Datei')

# Model für YouTube-URLs und Parameter
youtube_input = api.model('YouTubeInput', {
    'url': fields.String(required=True, description='YouTube Video URL'),
    'extract_audio': fields.Boolean(required=False, default=True, description='Audio extrahieren'),
    'language': fields.String(required=False, default='en', description='Sprache des Videos (ISO 639-1 code)'),
    'summarize': fields.Boolean(required=False, default=False, description='Zusammenfassung generieren')
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
        """
        PDF-Datei verarbeiten
        
        Lädt eine PDF-Datei hoch und extrahiert relevante Informationen wie Seitenanzahl,
        Text und Metadaten.
        """
        args = file_upload.parse_args()
        file = args['file']
        
        if not file.filename.lower().endswith('.pdf'):
            return {'error': 'Nur PDF-Dateien erlaubt'}, 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            file.save(temp_file.name)
            try:
                result = await pdf_processor.process(temp_file.name)
                return result
            finally:
                os.unlink(temp_file.name)

@api.route('/process-image')
class ImageEndpoint(Resource):
    @api.expect(file_upload)
    @api.response(200, 'Erfolg', image_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein Bild und extrahiert Informationen')
    async def post(self):
        """
        Bild verarbeiten
        
        Lädt ein Bild hoch und extrahiert relevante Informationen wie Dimensionen,
        Format und Metadaten.
        """
        args = file_upload.parse_args()
        file = args['file']
        
        if not any(file.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg']):
            return {'error': 'Nur PNG/JPG Dateien erlaubt'}, 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
            file.save(temp_file.name)
            try:
                result = await image_processor.process(temp_file.name)
                return result
            finally:
                os.unlink(temp_file.name)

@api.route('/process-youtube')
class YouTubeEndpoint(Resource):
    @api.expect(youtube_input)
    @api.response(200, 'Erfolg', youtube_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description="""
    Verarbeitet ein YouTube-Video und extrahiert Informationen.
    """)
    def post(self):
        """
        YouTube-Video verarbeiten

        Dieser Endpunkt kann:
        - Audio aus dem Video extrahieren
        - Sprache in Text umwandeln
        - Eine Zusammenfassung des Inhalts generieren
        - Mehrere Sprachen verarbeiten
        - Video-Metadaten extrahieren

        Alle Parameter außer der URL sind optional.
        """
        data = request.get_json()
        if 'url' not in data:
            return {'error': 'YouTube-URL erforderlich'}, 400
            
        try:
            # Extrahiere alle Parameter
            url = data['url']
            extract_audio = data.get('extract_audio', True)
            language = data.get('language', 'en')
            summarize = data.get('summarize', False)
            
            result = asyncio.run(youtube_processor.process(
                url=url,
                language=language,
                extract_audio=extract_audio,
                summarize=summarize
            ))
            return result
        except Exception as e:
            logger.error("YouTube-Verarbeitungsfehler",
                        error=str(e),
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc())
            raise

@api.route('/process-audio')
class AudioEndpoint(Resource):
    @api.expect(file_upload)
    @api.response(200, 'Erfolg', audio_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet eine Audio-Datei')
    async def post(self):
        """
        Audio-Datei verarbeiten
        
        Lädt eine Audio-Datei hoch und extrahiert relevante Informationen wie Länge,
        Format und Metadaten.
        """
        args = file_upload.parse_args()
        file = args['file']
        
        if not any(file.filename.lower().endswith(ext) for ext in ['.mp3', '.wav', '.m4a']):
            return {'error': 'Nur Audio-Dateien erlaubt'}, 400
        
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            file.save(temp_file.name)
            try:
                audio_data = Path(temp_file.name).read_bytes()
                source_info = {"title": file.filename}
                result = await audio_processor.process(audio_data, source_info)
                return result
            finally:
                os.unlink(temp_file.name)

@api.route('/')
class Home(Resource):
    @api.doc(description='API Willkommensseite')
    def get(self):
        """API Willkommensseite"""
        return {'message': 'Welcome to the Processing Service API!'}