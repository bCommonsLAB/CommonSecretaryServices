# type: ignore
"""
Audio-Prozessor API-Routen.
Enthält alle Endpoints zur Verarbeitung von Audio-Dateien.
"""

from flask_restx import Model, Namespace, OrderedModel, Resource, fields, inputs
from typing import Dict, Any, Union, Optional, IO, cast, Tuple
import asyncio
import uuid
import tempfile
import os
from pathlib import Path
from werkzeug.datastructures import FileStorage

from src.processors.audio_processor import AudioProcessor
from src.core.models.audio import AudioResponse
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from utils.logger import ProcessingLogger

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="audio-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
audio_ns = Namespace('audio', description='Audio-Verarbeitungs-Operationen')

# Model für Audio-Upload Parameter
upload_parser = audio_ns.parser()
upload_parser.add_argument('file', location='files', type=FileStorage, required=True, help='Audio-Datei')
upload_parser.add_argument('source_language', location='form', type=str, default='de', help='Quellsprache (ISO 639-1 code, z.B. "en", "de")')
upload_parser.add_argument('target_language', location='form', type=str, default='de', help='Zielsprache (ISO 639-1 code, z.B. "en", "de")')
upload_parser.add_argument('template', location='form', type=str, default='', help='Optional Template für die Verarbeitung')
upload_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')

# Definiere Error-Modell, identisch zum alten Format
error_model: Model | OrderedModel = audio_ns.model('Error', {
    'error': fields.String(description='Fehlermeldung')
})

# Definiere Modelle für die API-Dokumentation - FLACHES Format wie in der alten Version
audio_response: Model | OrderedModel = audio_ns.model('AudioResponse', {
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

# Helper-Funktion zum Abrufen des Audio-Processors
def get_audio_processor(process_id: Optional[str] = None) -> AudioProcessor:
    """Get or create audio processor instance with process ID"""
    return AudioProcessor(
        resource_calculator,
        process_id=process_id or str(uuid.uuid4())
    )

# Audio-Verarbeitungs-Funktion
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
        
    temp_file: IO[bytes] | None = None
    temp_file_path: str | None = None
    try:
        # Initialisiere Processor, damit wir die konfigurierten Temp-Verzeichnisse nutzen können
        process_id = str(uuid.uuid4())
        processor: AudioProcessor = get_audio_processor(process_id)
        
        # Speichere Upload in konfiguriertem temporären Verzeichnis
        temp_file, temp_file_path = processor.get_upload_temp_file(
            suffix=Path(uploaded_file.filename).suffix if uploaded_file.filename else ".audio"
        )
        uploaded_file.save(temp_file_path)
        temp_file.close()
        
        # Verarbeite die Datei
        result: AudioResponse = await processor.process(
            audio_source=temp_file_path,
            source_info=source_info,
            source_language=source_language,
            target_language=target_language,
            template=template,
            use_cache=use_cache
        )
        
        # Direkte Konvertierung in das flache Format wie in der alten routes.py
        # Wir verwenden einfach die to_dict() Methode und extrahieren dann die Daten
        return result.to_dict()
        
    finally:
        # Räume auf
        if temp_file:
            temp_file.close()
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass

# Audio-Verarbeitungs-Endpunkt
@audio_ns.route('/process')
class AudioProcessEndpoint(Resource):
    """Audio-Verarbeitungs-Endpunkt."""
    
    def _safe_delete(self, file_path: Union[str, Path]) -> None:
        """Löscht eine Datei sicher."""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning("Konnte temporäre Datei nicht löschen", error=e)

    @audio_ns.expect(upload_parser)
    @audio_ns.response(200, 'Erfolg', audio_response)
    @audio_ns.response(400, 'Validierungsfehler', error_model)
    @audio_ns.doc(description='Verarbeitet eine Audio-Datei. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine Audio-Datei"""
        source_language: str = 'de'  # Default-Wert
        target_language: str = 'de'  # Default-Wert
        try:
            # DEBUG: Request-Headers protokollieren
            from flask import request
            logger.info(f"Request-URL: {request.url}")
            logger.info(f"Request-Headers: {dict(request.headers)}")
            logger.info(f"Request-Content-Length: {request.content_length}")
            
            # Parse request
            args = upload_parser.parse_args()
            audio_file = args.get('file')
            
            # DEBUG: Dateigröße-Informationen protokollieren
            if audio_file:
                try:
                    # Position sichern und Größe durch Lesen ermitteln
                    current_pos = audio_file.tell()
                    audio_file.seek(0, os.SEEK_END)
                    actual_file_size = audio_file.tell()
                    audio_file.seek(current_pos)  # Position wiederherstellen
                    
                    # Protokolliere beide Größen
                    logger.info(f"Audiodatei: {audio_file.filename}, gemeldete Größe: {audio_file.content_length}, tatsächliche Größe: {actual_file_size}")
                except Exception as e:
                    logger.warning(f"Fehler beim Ermitteln der tatsächlichen Dateigröße: {e}")
            
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