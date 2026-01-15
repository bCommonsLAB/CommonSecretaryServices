"""
@fileoverview Audio API Routes - Flask-RESTX endpoints for audio processing

@description
Audio Processor API routes. Contains all endpoints for processing audio files.
This file defines REST API endpoints for audio processing with Flask-RESTX,
including upload, transcription, transformation, and caching.

Main endpoints:
- POST /api/audio/upload: Audio file upload and processing
- POST /api/audio/process: Audio processing with various options
- GET /api/audio/health: Health check for audio service

Features:
- Multipart form upload for audio files
- Support for various audio formats (MP3, WAV, M4A)
- Transcription with OpenAI Whisper
- Template-based transformation
- Caching support
- Swagger UI documentation

@module api.routes.audio_routes

@exports
- audio_ns: Namespace - Flask-RESTX namespace for audio endpoints
- upload_parser: RequestParser - Parser for upload parameters

@usedIn
- src.api.routes.__init__: Registers audio_ns namespace

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- External: werkzeug - FileStorage for file uploads
- Internal: src.processors.audio_processor - AudioProcessor
- Internal: src.core.models.audio - AudioResponse
- Internal: src.core.exceptions - ProcessingError
- Internal: src.utils.logger - Logging system
"""
# pyright: reportMissingTypeStubs=false
# type: ignore
from flask_restx import Model, Namespace, OrderedModel, Resource, fields, inputs
from typing import Dict, Any, Union, Optional, IO, cast
import asyncio
import uuid
import os
import time
from pathlib import Path
from werkzeug.datastructures import FileStorage

from src.processors.audio_processor import AudioProcessor
from src.core.models.audio import AudioResponse
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.logger import ProcessingLogger
from src.core.mongodb import SecretaryJobRepository

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="audio-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
audio_ns = Namespace('audio', description='Audio-Verarbeitungs-Operationen')

# Model für Audio-Upload Parameter
upload_parser = audio_ns.parser()
upload_parser.add_argument('file', location='files', type=FileStorage, required=True, help='Audio-Datei (multipart/form-data)')
upload_parser.add_argument('source_language', location='form', type=str, default='de', help='Quellsprache (ISO 639-1 code, z.B. "en", "de")')
upload_parser.add_argument('target_language', location='form', type=str, default='de', help='Zielsprache (ISO 639-1 code, z.B. "en", "de")')
upload_parser.add_argument('template', location='form', type=str, default='', help='Optional Template für die Verarbeitung')
upload_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')
# Async/Webhook (analog zu PDF)
upload_parser.add_argument('callback_url', location='form', type=str, required=False, help='Optional: Webhook-URL für asynchrone Verarbeitung')
upload_parser.add_argument('callback_token', location='form', type=str, required=False, help='Optional: Token für Webhook-Auth')
upload_parser.add_argument('jobId', location='form', type=str, required=False, help='Optional: Externe Job-ID (vom Client) für Callback-Kontext')

# Definiere Error-Modell, identisch zum alten Format
error_model: Model | OrderedModel = audio_ns.model('Error', {
    'status': fields.String(description='Status der Anfrage (error)'),
    'error': fields.Nested(audio_ns.model('ErrorDetails', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Zusätzliche Fehlerdetails')
    }))
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
                if temp_file_path:
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
        target_language: str = 'de'
        temp_file = None
        temp_file_path = None
        job_enqueued: bool = False
        callback_url: Optional[str] = None
        
        try:
            # DEBUG: Request-Headers protokollieren
            from flask import request
            logger.info(f"Request-URL: {request.url}")
            logger.info(f"Request-Headers: {dict(request.headers)}")
            logger.info(f"Request-Content-Type: {request.content_type}")
            logger.info(f"Request-Content-Length: {request.content_length}")
            
            # Versuche Request-Files und Form zu loggen
            try:
                logger.info(f"Request-Files: {request.files}")
                logger.info(f"Request-Form: {request.form}")
            except Exception as e:
                logger.warning(f"Fehler beim Loggen von Request-Daten: {e}")
            
            # Prüfe Content-Type
            if not request.content_type or 'multipart/form-data' not in request.content_type:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'INVALID_CONTENT_TYPE',
                        'message': 'Content-Type muss multipart/form-data sein',
                        'details': {
                            'received_content_type': request.content_type,
                            'expected_content_type': 'multipart/form-data'
                        }
                    }
                }, 400
            
            # jobId früh lesen (Parser-Eigenheiten umgehen, analog PDF)
            job_id_form_early: Optional[str] = None
            try:
                job_id_form_early = request.form.get('jobId')  # type: ignore
            except Exception:
                job_id_form_early = None

            # Parse request mit Fehlerbehandlung
            try:
                args_any = upload_parser.parse_args()
                args = cast(Dict[str, Any], args_any)
            except Exception as parse_error:
                logger.error(f"Fehler beim Parsen der Request-Argumente: {parse_error}")
                return {
                    'status': 'error',
                    'error': {
                        'code': 'PARSE_ERROR',
                        'message': 'Fehler beim Parsen der Request-Daten',
                        'details': {
                            'error_type': type(parse_error).__name__,
                            'error_message': str(parse_error)
                        }
                    }
                }, 400
            
            audio_file = cast(Optional[FileStorage], args.get('file'))
            
            if not audio_file:
                logger.error("Keine Audio-Datei gefunden in Request")
                return {
                    'status': 'error',
                    'error': {
                        'code': 'MISSING_FILE',
                        'message': 'Keine Audio-Datei gefunden',
                        'details': {
                            'error_type': 'ValidationError',
                            'request_files': list(request.files.keys()) if request.files else [],
                            'parsed_args': {k: str(v) for k, v in args.items() if k != 'file'}
                        }
                    }
                }, 400
            
            # DEBUG: Dateigröße-Informationen protokollieren
            actual_file_size: int = 0
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
                actual_file_size = audio_file.content_length
            
            source_language = str(args.get('source_language', 'de') or 'de')
            target_language = str(args.get('target_language', 'de') or 'de')
            template = str(args.get('template', '') or '')
            use_cache = bool(args.get('useCache', True))
            callback_url = str(args.get('callback_url', '') or '') or None
            callback_token = str(args.get('callback_token', '') or '') or None

            # Bevorzuge früh gelesene jobId; fallback auf Parser-Wert
            job_id_form: Optional[str] = None
            if job_id_form_early and str(job_id_form_early).strip():
                job_id_form = str(job_id_form_early).strip()
            elif args.get('jobId'):
                job_id_form = str(args.get('jobId')).strip()

            # Validiere Dateiformat
            filename = str(audio_file.filename or "").lower()
            supported_formats = {'flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'oga', 'ogg', 'wav', 'webm'}
            file_ext = Path(filename).suffix.lstrip('.')
            source_info = {
                'original_filename': audio_file.filename,
                'file_size': getattr(audio_file, "content_length", None),
                'file_type': audio_file.content_type,
                'file_ext': file_ext
            }

            if file_ext not in supported_formats:
                raise ProcessingError(
                    f"Das Format '{file_ext}' wird nicht unterstützt. Unterstützte Formate: {', '.join(supported_formats)}",
                    details={'error_type': 'INVALID_FORMAT', 'supported_formats': list(supported_formats)}
                )

            # Async Mode (wie PDF): Wenn callback_url gesetzt ist, Job enqueuen und 202 zurückgeben
            if callback_url:
                process_id = str(uuid.uuid4())

                # Upload persistieren, damit der Worker später zugreifen kann
                upload_dir = Path("cache") / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(audio_file.filename).suffix if audio_file.filename else ".audio"
                temp_file_path = str(upload_dir / f"upload_{uuid.uuid4()}{suffix}")
                audio_file.save(temp_file_path)
                temp_file_path = os.path.abspath(temp_file_path)
                try:
                    temp_file_path = Path(temp_file_path).as_posix()
                except Exception:
                    temp_file_path = temp_file_path.replace('\\', '/')

                params_flat: Dict[str, Any] = {
                    "filename": temp_file_path,
                    "use_cache": bool(use_cache),
                    "source_language": str(source_language),
                    "target_language": str(target_language),
                    "template": str(template) if template else None,
                    # Kontext/Metadaten: minimal, aber hilfreich (AudioProcessor nutzt es fürs Template)
                    "context": {
                        "original_filename": audio_file.filename,
                        "file_size_bytes": int(actual_file_size or 0),
                        "file_type": audio_file.content_type,
                        "file_ext": file_ext,
                    },
                    "webhook": {
                        "url": callback_url,
                        "token": callback_token,
                        "jobId": job_id_form or job_id_form_early or None,
                    },
                }

                job_repo = SecretaryJobRepository()
                created_job_id: str = job_repo.create_job({"job_type": "audio", "parameters": params_flat})
                job_enqueued = True

                ack: Dict[str, Any] = {
                    "status": "accepted",
                    "worker": "secretary",
                    "process": {
                        "id": process_id,
                        "main_processor": "audio",
                        "started": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        "is_from_cache": False,
                    },
                    # Für den Client die externe jobId (falls gesetzt) zurückgeben
                    "job": {"id": job_id_form or job_id_form_early or created_job_id},
                    "webhook": {"delivered_to": callback_url},
                    "error": None,
                }
                logger.info(
                    "Webhook-ACK gesendet (Audio Job enqueued)",
                    process_id=process_id,
                    job_id_external=(job_id_form or job_id_form_early),
                    job_id_internal=created_job_id,
                    callback_url=callback_url,
                )
                return ack, 202

            # Sync fallback (bestehendes Verhalten)
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
            
        finally:
            # Cleanup nur im Sync-Fall. Wenn ein Job enqueued wurde, muss die Datei bestehen bleiben.
            if not job_enqueued:
                if temp_file:
                    temp_file.close()
                    try:
                        if temp_file_path:
                            os.unlink(temp_file_path)
                    except OSError:
                        pass 