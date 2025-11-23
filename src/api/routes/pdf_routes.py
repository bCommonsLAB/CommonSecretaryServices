"""
@fileoverview PDF API Routes - Flask-RESTX endpoints for PDF processing

@description
API route for PDF processing. This file defines REST API endpoints for PDF processing
with Flask-RESTX, including upload, text extraction, OCR, and preview image generation.

Main endpoints:
- POST /api/pdf/upload: PDF file upload and processing
- POST /api/pdf/process: PDF processing with various extraction methods
- POST /api/pdf/job: Asynchronous PDF processing as job
- GET /api/pdf/health: Health check for PDF service

Features:
- Multipart form upload for PDF files
- Various extraction methods (native, OCR, LLM-based)
- Preview image generation for PDF pages
- Asynchronous job processing
- Caching support
- Swagger UI documentation

@module api.routes.pdf_routes

@exports
- pdf_ns: Namespace - Flask-RESTX namespace for PDF endpoints

@usedIn
- src.api.routes.__init__: Registers pdf_ns namespace

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- External: werkzeug - FileStorage for file uploads
- Internal: src.processors.pdf_processor - PDFProcessor
- Internal: src.core.mongodb.secretary_repository - SecretaryJobRepository for asynchronous jobs
- Internal: src.core.models.job_models - JobStatus
- Internal: src.utils.logger - Logging system
"""
import os
import traceback
import uuid
import json
import asyncio
import hashlib
from typing import Dict, Any, Union, Optional, cast, Tuple
from pathlib import Path

from flask_restx import Namespace, Resource, fields, inputs  # type: ignore
from flask import request, Response  # type: ignore
from werkzeug.datastructures import FileStorage
import time

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
# Performance-Tracker wird in diesem Flow nicht benötigt
from src.processors.pdf_processor import PDFProcessor
from src.core.mongodb.secretary_repository import SecretaryJobRepository
from src.core.models.job_models import JobStatus

# Logger initialisieren
logger = get_logger(process_id="pdf_routes", processor_name="pdf_routes")

# Namespace für PDF-Routen
pdf_ns = Namespace('pdf', description='PDF-Verarbeitungsrouten')


def _mask_token(token: Optional[str]) -> Optional[str]:
    """Maskiert sensible Token für Logging-Zwecke."""
    if not token:
        return token
    try:
        t = str(token)
        if len(t) <= 6:
            return "***"
        return f"{t[:4]}...{t[-4:]}"
    except Exception:
        return "***"


def _collect_headers_subset() -> Dict[str, Any]:
    """Liest eine kleine, relevante Header-Auswahl für Logs."""
    try:
        headers = request.headers  # type: ignore
        return {
            'Content-Type': headers.get('Content-Type'),
            'Content-Length': headers.get('Content-Length'),
            'User-Agent': headers.get('User-Agent'),
            'X-Forwarded-For': headers.get('X-Forwarded-For'),
        }
    except Exception:
        return {}


def _raw_form_with_redaction() -> Dict[str, Any]:
    """Gibt request.form als Dict zurück und maskiert sensible Felder."""
    try:
        form_dict: Dict[str, Any] = dict(request.form)  # type: ignore
    except Exception:
        form_dict = {}
    if 'callback_token' in form_dict:
        form_dict['callback_token'] = _mask_token(form_dict.get('callback_token'))
    return form_dict



# PDF Upload Parser
pdf_upload_parser = pdf_ns.parser()
pdf_upload_parser.add_argument('file',  # type: ignore
                          type=FileStorage,
                          location='files',
                          required=True,
                          help='PDF-Datei')
pdf_upload_parser.add_argument('extraction_method',  # type: ignore
                          type=str,
                          location='form',
                          default='native',
                          choices=['native', 'tesseract_ocr', 'both', 'preview', 'preview_and_native', 'llm', 'llm_and_native', 'llm_and_ocr'],
                          help='Extraktionsmethode (native=nur Text, tesseract_ocr=nur Tesseract OCR, both=beides, preview=Vorschaubilder, preview_and_native=Vorschaubilder und Text, llm=LLM-basierte OCR, llm_and_native=LLM+Native, llm_and_ocr=LLM+Tesseract)')
pdf_upload_parser.add_argument('page_start',  # type: ignore
                          type=int,
                          location='form',
                          required=False,
                          help='Startseite (1-basiert) für OCR')
pdf_upload_parser.add_argument('page_end',  # type: ignore
                          type=int,
                          location='form',
                          required=False,
                          help='Endseite (1-basiert, inkl.) für OCR')
pdf_upload_parser.add_argument('template',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Template für die Transformation')
pdf_upload_parser.add_argument('context',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='JSON-Kontext für die Verarbeitung')
pdf_upload_parser.add_argument('useCache',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=True, 
                          help='Cache verwenden (default: True)')
pdf_upload_parser.add_argument('includeImages',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=False, 
                          help='Base64-kodiertes ZIP-Archiv mit generierten Bildern erstellen (default: False)')
pdf_upload_parser.add_argument('target_language',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Zielsprache, z. B. de')
pdf_upload_parser.add_argument('callback_url',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Absolute HTTPS-URL für den Webhook-Callback')
pdf_upload_parser.add_argument('callback_token',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Per-Job-Secret für den Webhook-Callback')
pdf_upload_parser.add_argument('jobId',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Eindeutige Job-ID für den Callback')
pdf_upload_parser.add_argument('force_refresh',  # type: ignore
                          location='form',
                          type=inputs.boolean,  # type: ignore
                          required=False,
                          help='Erzwinge Neuberechnung/kein Cache')
pdf_upload_parser.add_argument('wait_ms',  # type: ignore
                          location='form',
                          type=int,  # type: ignore
                          required=False,
                          default=0,
                          help='Optional: Wartezeit in Millisekunden auf Abschluss (nur ohne callback_url)')

# PDF URL Parser
pdf_url_parser = pdf_ns.parser()
pdf_url_parser.add_argument('url',  # type: ignore
                          type=str,
                          location='form',
                          required=True,
                          help='URL zur PDF-Datei')
pdf_url_parser.add_argument('extraction_method',  # type: ignore
                          type=str,
                          location='form',
                          default='native',
                          choices=['native', 'tesseract_ocr', 'both', 'preview', 'preview_and_native', 'llm', 'llm_and_native', 'llm_and_ocr'],
                          help='Extraktionsmethode (native=nur Text, tesseract_ocr=nur Tesseract OCR, both=beides, preview=Vorschaubilder, preview_and_native=Vorschaubilder und Text, llm=LLM-basierte OCR, llm_and_native=LLM+Native, llm_and_ocr=LLM+Tesseract)')
pdf_url_parser.add_argument('page_start',  # type: ignore
                          type=int,
                          location='form',
                          required=False,
                          help='Startseite (1-basiert) für OCR')
pdf_url_parser.add_argument('page_end',  # type: ignore
                          type=int,
                          location='form',
                          required=False,
                          help='Endseite (1-basiert, inkl.) für OCR')
pdf_url_parser.add_argument('template',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Template für die Transformation')
pdf_url_parser.add_argument('context',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='JSON-Kontext für die Verarbeitung')
pdf_url_parser.add_argument('useCache',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=True, 
                          help='Cache verwenden (default: True)')
pdf_url_parser.add_argument('includeImages',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=False, 
                          help='Base64-kodiertes ZIP-Archiv mit generierten Bildern erstellen (default: False)')
pdf_url_parser.add_argument('target_language',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Zielsprache, z. B. de')
pdf_url_parser.add_argument('callback_url',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Absolute HTTPS-URL für den Webhook-Callback')
pdf_url_parser.add_argument('callback_token',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Per-Job-Secret für den Webhook-Callback')
pdf_url_parser.add_argument('jobId',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Eindeutige Job-ID für den Callback')
pdf_url_parser.add_argument('force_refresh',  # type: ignore
                          location='form',
                          type=inputs.boolean,  # type: ignore
                          required=False,
                          help='Erzwinge Neuberechnung/kein Cache')
pdf_url_parser.add_argument('wait_ms',  # type: ignore
                          location='form',
                          type=int,  # type: ignore
                          required=False,
                          default=0,
                          help='Optional: Wartezeit in Millisekunden auf Abschluss (nur ohne callback_url)')

# PDF Mistral OCR Parser
pdf_mistral_ocr_parser = pdf_ns.parser()
pdf_mistral_ocr_parser.add_argument('file',  # type: ignore
                          type=FileStorage,
                          location='files',
                          required=True,
                          help='PDF-Datei')
pdf_mistral_ocr_parser.add_argument('page_start',  # type: ignore
                          type=int,
                          location='form',
                          required=False,
                          help='Startseite (1-basiert) für OCR')
pdf_mistral_ocr_parser.add_argument('page_end',  # type: ignore
                          type=int,
                          location='form',
                          required=False,
                          help='Endseite (1-basiert, inkl.) für OCR')
pdf_mistral_ocr_parser.add_argument('includeOCRImages',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=True, 
                          help='Mistral OCR Bilder als Base64 in Response anfordern (default: True). Bilder liegen dann in data.mistral_ocr_raw.pages[*].images[*].image_base64.')
pdf_mistral_ocr_parser.add_argument('includePageImages',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=True, 
                          help='PDF-Seiten als Bilder extrahieren und als ZIP zurückgeben (default: True). Läuft parallel zur Mistral OCR Transformation.')
pdf_mistral_ocr_parser.add_argument('useCache',  # type: ignore
                          location='form', 
                          type=inputs.boolean,  # type: ignore
                          default=True, 
                          help='Cache verwenden (default: True)')
pdf_mistral_ocr_parser.add_argument('callback_url',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Absolute HTTPS-URL für den Webhook-Callback')
pdf_mistral_ocr_parser.add_argument('callback_token',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Per-Job-Secret für den Webhook-Callback')
pdf_mistral_ocr_parser.add_argument('jobId',  # type: ignore
                          type=str,
                          location='form',
                          required=False,
                          help='Eindeutige Job-ID für den Callback')
pdf_mistral_ocr_parser.add_argument('wait_ms',  # type: ignore
                          location='form',
                          type=int,  # type: ignore
                          required=False,
                          default=0,
                          help='Optional: Wartezeit in Millisekunden auf Abschluss (nur ohne callback_url)')

# PDF Antwortmodell
pdf_response = pdf_ns.model('PDFResponse', {  # type: ignore
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(pdf_ns.model('PDFRequestInfo', {  # type: ignore
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(pdf_ns.model('PDFProcessInfo', {  # type: ignore
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'sub_processors': fields.List(fields.String, description='Verwendete Sub-Prozessoren'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(pdf_ns.model('PDFData', {  # type: ignore
        'metadata': fields.Nested(pdf_ns.model('PDFMetadata', {  # type: ignore
            'file_name': fields.String(description='Dateiname'),
            'file_size': fields.Integer(description='Dateigröße in Bytes'),
            'page_count': fields.Integer(description='Anzahl der Seiten'),
            'format': fields.String(description='Dateiformat'),
            'process_dir': fields.String(description='Verarbeitungsverzeichnis'),
            'image_paths': fields.List(fields.String, description='Pfade zu extrahierten Bildern'),
            'preview_paths': fields.List(fields.String, description='Pfade zu Vorschaubildern'),
            'preview_zip': fields.String(description='Pfad zur ZIP-Datei mit Vorschaubildern'),
            'text_paths': fields.List(fields.String, description='Pfade zu extrahierten Textdateien'),
            'text_contents': fields.List(fields.Nested(pdf_ns.model('PDFTextContent', {  # type: ignore
                'page': fields.Integer(description='Seitennummer'),
                'content': fields.String(description='Textinhalt der Seite')
            })), description='Extrahierte Textinhalte mit Seitennummern'),
            'extraction_method': fields.String(description='Verwendete Extraktionsmethode')
        })),
        'extracted_text': fields.String(description='Extrahierter Text'),
        'ocr_text': fields.String(description='OCR-Text'),
        'process_id': fields.String(description='Prozess-ID'),
        'images_archive_data': fields.String(description='Base64-kodiertes ZIP-Archiv mit allen generierten Bildern (nur wenn includeImages=true)'),
        'images_archive_filename': fields.String(description='Dateiname des Bilder-Archives (nur wenn includeImages=true)'),
        'pages_archive_data': fields.String(description='Base64-kodiertes ZIP-Archiv mit PDF-Seiten als Bilder (nur bei process-mistral-ocr Endpoint)'),
        'pages_archive_filename': fields.String(description='Dateiname des Seiten-Archives (nur bei process-mistral-ocr Endpoint)')
    })),
    'error': fields.Nested(pdf_ns.model('PDFError', {  # type: ignore
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Error-Modell
error_model = pdf_ns.model('Error', {  # type: ignore
    'error': fields.String(description='Fehlermeldung')
})

def get_pdf_processor(process_id: Optional[str] = None) -> PDFProcessor:
    """Erstellt eine neue PDFProcessor-Instanz mit dem angegebenen Prozess-ID."""
    from src.core.resource_tracking import ResourceCalculator
    return PDFProcessor(ResourceCalculator(), process_id)

def calculate_file_hash(file_path: str) -> str:
    """Berechnet einen MD5-Hash für die angegebene Datei.
    
    Args:
        file_path: Pfad zur Datei
        
    Returns:
        str: MD5-Hash der Datei
    """
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

@pdf_ns.route('/process')  # type: ignore
class PDFEndpoint(Resource):
    @pdf_ns.expect(pdf_upload_parser)  # type: ignore
    @pdf_ns.response(200, 'Erfolg', pdf_response)  # type: ignore
    @pdf_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @pdf_ns.doc(description='Verarbeitet eine PDF-Datei und extrahiert Informationen. Unterstützt verschiedene Extraktionsmethoden: native (Text), ocr (OCR), both (beides), preview (Vorschaubilder) oder preview_and_native (Vorschaubilder und Text). Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden. Mit includeImages=true wird ein Base64-kodiertes ZIP-Archiv mit allen generierten Bildern erstellt.')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine PDF-Datei"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            # Worker-basierter Modus: kein lokaler Tracker erforderlich
            process_id = str(uuid.uuid4())
            # Initialisiere Variablen, die später innerhalb von try-except verwendet werden
            temp_file_path: str = ""  # Initialisierung für Linter
            callback_url: Optional[str] = None  # Für finally: entscheidet über Cleanup
            job_enqueued: bool = False  # Cleanup nur, wenn kein Job angelegt wurde
            
            try:
                # Reduzierte Logs: keine Header/Form-Dumps
                try:
                    logger.info("Eingehende PDF-Anfrage (multipart)")
                except Exception:
                    pass

                # Lese jobId frühzeitig direkt aus dem Request, um Parser-Eigenheiten zu umgehen
                job_id_form_early = None
                try:
                    job_id_form_early = request.form.get('jobId')  # type: ignore
                except Exception:
                    job_id_form_early = None
                args = pdf_upload_parser.parse_args()  # type: ignore
                args = cast(Dict[str, Any], args)
                uploaded_file = cast(FileStorage, args['file'])
                extraction_method = str(args.get('extraction_method', 'native'))
                template = str(args.get('template', '')) if args.get('template') else None
                context_str = str(args.get('context', '')) if args.get('context') else None
                context = json.loads(context_str) if context_str else None
                use_cache = bool(args.get('useCache', True))
                include_images = bool(args.get('includeImages', False))
                target_language = str(args.get('target_language', '')) if args.get('target_language') else None
                callback_url = str(args.get('callback_url', '')) if args.get('callback_url') else None
                callback_token = str(args.get('callback_token', '')) if args.get('callback_token') else None
                # Bevorzuge früh gelesene jobId; fallback auf Parser-Wert
                job_id_form = None
                if job_id_form_early and str(job_id_form_early).strip():
                    job_id_form = str(job_id_form_early).strip()
                elif args.get('jobId'):
                    job_id_form = str(args.get('jobId')).strip()
                force_refresh = bool(args.get('force_refresh', False))
                
                if not uploaded_file.filename:
                    raise ProcessingError("Kein Dateiname angegeben")
                
                # Speichere Datei in persistentes Upload-Verzeichnis
                _ = Path(uploaded_file.filename).suffix
                upload_dir = Path("cache") / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                temp_file_path = str(upload_dir / f"upload_{uuid.uuid4()}.pdf")
                uploaded_file.save(temp_file_path)
                # Reduzierte Logs: keine Pfad-/FS-Dumps
                # WICHTIG: Absoluten Pfad als POSIX-Form persistieren (forward slashes)
                temp_file_path = os.path.abspath(temp_file_path)
                try:
                    temp_file_path = Path(temp_file_path).as_posix()
                except Exception:
                    # Fallback: einfache Backslash-Ersetzung
                    temp_file_path = temp_file_path.replace('\\', '/')
                
                # Berechne optionalen Hash (nur für Logging/Cache-Key in Prozessdaten)
                file_hash = calculate_file_hash(temp_file_path)
                
                # Wartezeit optional aus Request
                wait_ms: int = 0
                try:
                    wait_ms = int(args.get('wait_ms', 0))  # type: ignore
                except Exception:
                    wait_ms = 0

                # Job anlegen
                job_repo = SecretaryJobRepository()
                job_webhook: Optional[Dict[str, Any]] = None
                if callback_url:
                    job_webhook = {
                        "url": callback_url,
                        "token": callback_token,
                        "jobId": job_id_form or job_id_form_early or None,
                    }

                # WICHTIG: Keine verschachtelte "extra"-Struktur setzen.
                # Unbekannte Felder auf Top-Level von parameters platzieren,
                # damit sie in JobParameters.extra landen und der Handler sie findet.
                params_flat: Dict[str, Any] = {
                    "filename": temp_file_path,  # absoluter Pfad
                    "use_cache": use_cache,
                    "target_language": target_language,
                    "extraction_method": extraction_method,
                    "template": template,
                    "context": context,
                    "include_images": include_images,
                    "force_refresh": bool(force_refresh),
                    "file_hash": file_hash,
                }
                # Seitenbereich, falls übergeben
                try:
                    ps = args.get('page_start')
                    pe = args.get('page_end')
                    if ps is not None:
                        params_flat["page_start"] = int(ps)
                    if pe is not None:
                        params_flat["page_end"] = int(pe)
                except Exception:
                    pass
                if job_webhook:
                    params_flat["webhook"] = job_webhook
                job_data: Dict[str, Any] = {
                    "job_type": "pdf",
                    "parameters": params_flat,
                }

                created_job_id: str = job_repo.create_job(job_data)
                job_enqueued = True
                try:
                    # Diagnose: Direkt nach Enqueue prüfen
                    enq_job = job_repo.get_job(created_job_id)
                    pending_after = len(job_repo.get_jobs(status=JobStatus.PENDING))
                    print(f"[PDF-ROUTE] SecretaryJob erstellt: {created_job_id}, status={getattr(enq_job,'status',None)}")
                    print(f"[PDF-ROUTE] Pending nach Enqueue: {pending_after}")
                except Exception as _diag_err:
                    print(f"[PDF-ROUTE] Diagnosefehler nach Enqueue: {_diag_err}")

                # Mit Callback → sofortiges ACK, Worker sendet anschließend Webhook
                if callback_url:
                    ack: Dict[str, Any] = {
                        'status': 'accepted',
                        'worker': 'secretary',
                        'process': {
                            'id': process_id,
                            'main_processor': 'pdf',
                            'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'is_from_cache': False
                        },
                        # Für den Client die externe jobId (falls gesetzt) zurückgeben
                        'job': {'id': job_id_form or job_id_form_early or created_job_id},
                        'webhook': {'delivered_to': callback_url},
                        'error': None
                    }
                    logger.info(
                        "Webhook-ACK gesendet (Job enqueued)",
                        process_id=process_id,
                        job_id_external=(job_id_form or job_id_form_early),
                        job_id_internal=created_job_id,
                        callback_url=callback_url,
                    )
                    return ack, 202

                # Ohne Callback → optional auf Abschluss warten, sonst 202 mit job_id
                if wait_ms > 0:
                    deadline = time.time() + (wait_ms / 1000.0)
                    while time.time() < deadline:
                        job = job_repo.get_job(created_job_id)
                        if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                            break
                        time.sleep(0.25)
                    job = job_repo.get_job(created_job_id)
                    if job and job.status == JobStatus.COMPLETED and job.results and job.results.structured_data:
                        # Ergebnisstruktur direkt zurückgeben
                        return job.results.structured_data  # type: ignore[return-value]
                    if job and job.status == JobStatus.FAILED and job.error:
                        return {
                            'status': 'error',
                            'error': {
                                'code': job.error.code,
                                'message': job.error.message,
                                'details': job.error.details or {}
                            }
                        }, 400

                # Fallback/Timeout → 202 mit job_id
                return {
                    'status': 'accepted',
                    'worker': 'secretary',
                    'process': {
                        'id': process_id,
                        'main_processor': 'pdf',
                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'is_from_cache': False
                    },
                    'job': {'id': created_job_id},
                    'webhook': None,
                    'error': None
                }, 202
                
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
                # Nur synchron bereinigen. Wenn ein Job angelegt wurde, Datei bestehen lassen.
                if not job_enqueued and not callback_url:
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception as e:
                            logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
        
        # Führe die asynchrone Verarbeitung aus
        return asyncio.run(process_request())

@pdf_ns.route('/process-mistral-ocr')  # type: ignore
class PDFMistralOCREndpoint(Resource):
    @pdf_ns.expect(pdf_mistral_ocr_parser)  # type: ignore
    @pdf_ns.response(200, 'Erfolg', pdf_response)  # type: ignore
    @pdf_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @pdf_ns.doc(description='Verarbeitet eine PDF-Datei mit Mistral OCR Transformation und extrahiert parallel PDF-Seiten als Bilder. Dieser Endpoint führt beide Prozesse parallel aus: Mistral OCR Transformation (mit eingebetteten Bildern im Markdown) und Bildextraktion der PDF-Seiten (als ZIP-Archiv).')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine PDF-Datei mit Mistral OCR und Seiten-Bildextraktion"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            process_id = str(uuid.uuid4())
            temp_file_path: str = ""
            callback_url: Optional[str] = None
            job_enqueued: bool = False
            
            try:
                logger.info("Eingehende PDF Mistral OCR Anfrage (multipart)")
                
                job_id_form_early = None
                try:
                    job_id_form_early = request.form.get('jobId')  # type: ignore
                except Exception:
                    job_id_form_early = None
                
                args = pdf_mistral_ocr_parser.parse_args()  # type: ignore
                args = cast(Dict[str, Any], args)
                uploaded_file = cast(FileStorage, args['file'])
                include_ocr_images = bool(args.get('includeOCRImages', True))
                include_page_images = bool(args.get('includePageImages', True))
                use_cache = bool(args.get('useCache', True))
                callback_url = str(args.get('callback_url', '')) if args.get('callback_url') else None
                callback_token = str(args.get('callback_token', '')) if args.get('callback_token') else None
                job_id_form = None
                if job_id_form_early and str(job_id_form_early).strip():
                    job_id_form = str(job_id_form_early).strip()
                elif args.get('jobId'):
                    job_id_form = str(args.get('jobId')).strip()
                
                if not uploaded_file.filename:
                    raise ProcessingError("Kein Dateiname angegeben")
                
                # Speichere Datei
                upload_dir = Path("cache") / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                temp_file_path = str(upload_dir / f"upload_{uuid.uuid4()}.pdf")
                uploaded_file.save(temp_file_path)
                temp_file_path = os.path.abspath(temp_file_path)
                try:
                    temp_file_path = Path(temp_file_path).as_posix()
                except Exception:
                    temp_file_path = temp_file_path.replace('\\', '/')
                
                file_hash = calculate_file_hash(temp_file_path)
                
                wait_ms: int = 0
                try:
                    wait_ms = int(args.get('wait_ms', 0))  # type: ignore
                except Exception:
                    wait_ms = 0
                
                # Seitenbereich
                page_start: Optional[int] = None
                page_end: Optional[int] = None
                try:
                    ps = args.get('page_start')
                    pe = args.get('page_end')
                    if ps is not None:
                        page_start = int(ps)
                    if pe is not None:
                        page_end = int(pe)
                except Exception:
                    pass
                
                # Job anlegen
                job_repo = SecretaryJobRepository()
                job_webhook: Optional[Dict[str, Any]] = None
                if callback_url:
                    job_webhook = {
                        "url": callback_url,
                        "token": callback_token,
                        "jobId": job_id_form or job_id_form_early or None,
                    }
                
                params_flat: Dict[str, Any] = {
                    "filename": temp_file_path,
                    "use_cache": use_cache,
                    "extraction_method": "mistral_ocr_with_pages",
                    "include_ocr_images": include_ocr_images,
                    "include_page_images": include_page_images,
                    "file_hash": file_hash,
                }
                if page_start is not None:
                    params_flat["page_start"] = page_start
                if page_end is not None:
                    params_flat["page_end"] = page_end
                if job_webhook:
                    params_flat["webhook"] = job_webhook
                
                job_data: Dict[str, Any] = {
                    "job_type": "pdf",
                    "parameters": params_flat,
                }
                
                created_job_id: str = job_repo.create_job(job_data)
                job_enqueued = True
                
                if callback_url:
                    ack: Dict[str, Any] = {
                        'status': 'accepted',
                        'worker': 'secretary',
                        'process': {
                            'id': process_id,
                            'main_processor': 'pdf',
                            'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'is_from_cache': False
                        },
                        'job': {'id': job_id_form or job_id_form_early or created_job_id},
                        'webhook': {'delivered_to': callback_url},
                        'error': None
                    }
                    logger.info(
                        "Webhook-ACK gesendet (Mistral OCR Job enqueued)",
                        process_id=process_id,
                        job_id_external=(job_id_form or job_id_form_early),
                        job_id_internal=created_job_id,
                        callback_url=callback_url,
                    )
                    return ack, 202
                
                if wait_ms > 0:
                    deadline = time.time() + (wait_ms / 1000.0)
                    while time.time() < deadline:
                        job = job_repo.get_job(created_job_id)
                        if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                            break
                        time.sleep(0.25)
                    job = job_repo.get_job(created_job_id)
                    if job and job.status == JobStatus.COMPLETED and job.results and job.results.structured_data:
                        return job.results.structured_data  # type: ignore[return-value]
                    if job and job.status == JobStatus.FAILED and job.error:
                        return {
                            'status': 'error',
                            'error': {
                                'code': job.error.code,
                                'message': job.error.message,
                                'details': job.error.details or {}
                            }
                        }, 400
                
                return {
                    'status': 'accepted',
                    'worker': 'secretary',
                    'process': {
                        'id': process_id,
                        'main_processor': 'pdf',
                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'is_from_cache': False
                    },
                    'job': {'id': created_job_id},
                    'webhook': None,
                    'error': None
                }, 202
                
            except Exception as e:
                logger.error("Fehler bei der PDF Mistral OCR Verarbeitung", error=e)
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
                if not job_enqueued and not callback_url:
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception as e:
                            logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
        
        return asyncio.run(process_request())

@pdf_ns.route('/process-url')  # type: ignore
class PDFUrlEndpoint(Resource):
    @pdf_ns.expect(pdf_url_parser)  # type: ignore
    @pdf_ns.response(200, 'Erfolg', pdf_response)  # type: ignore
    @pdf_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @pdf_ns.doc(description='Verarbeitet eine PDF-Datei von einer URL und extrahiert Informationen. Unterstützt HTTP/HTTPS URLs, die auf PDF- oder PowerPoint-Dateien (.pdf, .ppt, .pptx) verweisen. PowerPoint-Dateien werden automatisch zu PDF konvertiert. Unterstützt verschiedene Extraktionsmethoden: native (Text), ocr (OCR), both (beides), preview (Vorschaubilder) oder preview_and_native (Vorschaubilder und Text). Die Antwort enthält text_contents mit dem tatsächlichen Textinhalt jeder Seite. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden. Mit includeImages=true wird ein Base64-kodiertes ZIP-Archiv mit allen generierten Bildern erstellt.')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Verarbeitet eine PDF-Datei von einer URL (HTTP/HTTPS)"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            # Worker-basierter Modus: kein lokaler Tracker erforderlich
            process_id = str(uuid.uuid4())
            
            try:
                # Eingehende Form-/Header-Daten für Debugging loggen (Token maskiert)
                try:
                    logger.info(
                        "Eingehende PDF-URL-Anfrage (multipart)",
                        headers=_collect_headers_subset(),
                        form=_raw_form_with_redaction()
                    )
                except Exception:
                    pass

                args = pdf_url_parser.parse_args()  # type: ignore
                args = cast(Dict[str, Any], args)
                url = str(args.get('url', ''))
                extraction_method = str(args.get('extraction_method', 'native'))
                template = str(args.get('template', '')) if args.get('template') else None
                context_str = str(args.get('context', '')) if args.get('context') else None
                context = json.loads(context_str) if context_str else None
                use_cache = bool(args.get('useCache', True))
                include_images = bool(args.get('includeImages', False))
                target_language = str(args.get('target_language', '')) if args.get('target_language') else None
                callback_url = str(args.get('callback_url', '')) if args.get('callback_url') else None
                callback_token = str(args.get('callback_token', '')) if args.get('callback_token') else None
                job_id_form = str(args.get('jobId', '')) if args.get('jobId') else None
                force_refresh = bool(args.get('force_refresh', False))
                
                if not url:
                    raise ProcessingError("Keine URL angegeben")
                
                # Berechne einen Hash aus der URL als Cache-Key-Komponente
                # (Bei URLs ist das besser als nichts, obwohl der Dateiinhalt sich ändern könnte)
                url_hash = hashlib.md5(url.encode()).hexdigest()
                
                # Wartezeit optional
                wait_ms: int = 0
                try:
                    wait_ms = int(args.get('wait_ms', 0))  # type: ignore
                except Exception:
                    wait_ms = 0

                # Job anlegen
                job_repo = SecretaryJobRepository()
                job_webhook: Optional[Dict[str, Any]] = None
                if callback_url:
                    job_webhook = {
                        "url": callback_url,
                        "token": callback_token,
                        "jobId": job_id_form or None,
                    }
                params_flat_url: Dict[str, Any] = {
                    "url": url,
                    "use_cache": use_cache,
                    "target_language": target_language,
                    "extraction_method": extraction_method,
                    "template": template,
                    "context": context,
                    "include_images": include_images,
                    "force_refresh": bool(force_refresh),
                    "file_hash": url_hash,
                }
                # Seitenbereich, falls übergeben
                try:
                    ps = args.get('page_start')
                    pe = args.get('page_end')
                    if ps is not None:
                        params_flat_url["page_start"] = int(ps)
                    if pe is not None:
                        params_flat_url["page_end"] = int(pe)
                except Exception:
                    pass
                if job_webhook:
                    params_flat_url["webhook"] = job_webhook
                job_data: Dict[str, Any] = {
                    "job_type": "pdf",
                    "parameters": params_flat_url,
                }

                created_job_id: str = job_repo.create_job(job_data)
                try:
                    enq_job = job_repo.get_job(created_job_id)
                    pending_after = len(job_repo.get_jobs(status=JobStatus.PENDING))
                    print(f"[PDF-ROUTE] SecretaryJob(URL) erstellt: {created_job_id}, status={getattr(enq_job,'status',None)}")
                    print(f"[PDF-ROUTE] Pending nach Enqueue (URL): {pending_after}")
                except Exception as _diag_err:
                    print(f"[PDF-ROUTE] Diagnosefehler nach Enqueue(URL): {_diag_err}")

                if callback_url:
                    ack: Dict[str, Any] = {
                        'status': 'accepted',
                        'worker': 'secretary',
                        'process': {
                            'id': process_id,
                            'main_processor': 'pdf',
                            'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'is_from_cache': False
                        },
                        'job': {'id': created_job_id},
                        'webhook': {'delivered_to': callback_url},
                        'error': None
                    }
                    logger.info("Webhook-ACK gesendet (Job enqueued)", process_id=process_id, job_id=created_job_id, callback_url=callback_url)
                    return ack, 202

                if wait_ms > 0:
                    deadline = time.time() + (wait_ms / 1000.0)
                    while time.time() < deadline:
                        job = job_repo.get_job(created_job_id)
                        if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                            break
                        time.sleep(0.25)
                    job = job_repo.get_job(created_job_id)
                    if job and job.status == JobStatus.COMPLETED and job.results and job.results.structured_data:
                        return job.results.structured_data  # type: ignore[return-value]
                    if job and job.status == JobStatus.FAILED and job.error:
                        return {
                            'status': 'error',
                            'error': {
                                'code': job.error.code,
                                'message': job.error.message,
                                'details': job.error.details or {}
                            }
                        }, 400

                return {
                    'status': 'accepted',
                    'worker': 'secretary',
                    'process': {
                        'id': process_id,
                        'main_processor': 'pdf',
                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'is_from_cache': False
                    },
                    'job': {'id': created_job_id},
                    'webhook': None,
                    'error': None
                }, 202
                
            except Exception as e:
                logger.error("Fehler bei der PDF-Verarbeitung von URL", error=e)
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
        
        # Führe die asynchrone Verarbeitung aus
        return asyncio.run(process_request())

@pdf_ns.route('/text-content/<path:file_path>')  # type: ignore
class PDFTextContentEndpoint(Resource):
    @pdf_ns.doc(description='Ruft den Inhalt einer Textdatei ab, die durch den PDF-Prozessor erstellt wurde.')  # type: ignore
    def get(self, file_path: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Ruft den Inhalt einer Textdatei ab"""
        try:
            # Sicherheitsüberprüfung: Stelle sicher, dass nur auf Dateien im Cache-Verzeichnis zugegriffen wird
            # Normalisiere den Pfad, indem Backslashes durch Vorwärtsschrägstriche ersetzt werden
            normalized_path = file_path.replace('\\', '/')
            
            # Überprüfe, ob der Pfad im Cache-Verzeichnis beginnt
            if not normalized_path.startswith('cache/'):
                return {'error': 'Zugriff verweigert: Ungültiger Pfad'}, 403
            
            # Konstruiere den vollständigen Pfad
            full_path = Path(normalized_path)
            
            # Überprüfe, ob die Datei existiert
            if not full_path.exists():
                return {'error': f'Datei nicht gefunden: {file_path}'}, 404
            
            # Überprüfe, ob es sich um eine Textdatei handelt
            if not full_path.is_file() or full_path.suffix.lower() != '.txt':
                return {'error': 'Ungültiger Dateityp: Nur Textdateien sind erlaubt'}, 400
            
            # Lese den Inhalt der Datei
            content = full_path.read_text(encoding='utf-8')
            
            # Gib den Inhalt zurück
            return {
                'file_path': str(file_path),
                'content': content
            }
            
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Textinhalts: {str(e)}")
            return {
                'error': str(e)
            }, 500

@pdf_ns.route('/jobs/<string:job_id>/download-pages-archive')  # type: ignore
class PDFJobPagesArchiveDownloadEndpoint(Resource):
    @pdf_ns.doc(description='Lädt das ZIP-Archiv mit PDF-Seiten als Bilder herunter (nur für Mistral OCR Jobs mit includePageImages=true)')  # type: ignore
    @pdf_ns.response(200, 'ZIP-Datei als Download')  # type: ignore
    @pdf_ns.response(404, 'Job nicht gefunden', error_model)  # type: ignore
    @pdf_ns.response(400, 'Kein Seiten-Archiv verfügbar', error_model)  # type: ignore
    def get(self, job_id: str) -> Union[Response, Tuple[Dict[str, Any], int]]:
        """Lädt das ZIP-Archiv mit PDF-Seiten als Bilder herunter"""
        try:
            job_repo = SecretaryJobRepository()
            job = job_repo.get_job(job_id)
            
            if not job:
                return {'error': 'Job nicht gefunden'}, 404
            
            if not job.results:
                status_any: Any = getattr(job, 'status', 'processing')
                try:
                    status_str: str = str(status_any.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str = str(status_any)
                if status_str in ("pending", "processing"):
                    return {'status': 'processing', 'message': 'Seiten-Archiv noch nicht bereit, bitte später erneut versuchen'}, 202
                return {'error': 'Job hat keine Ergebnisse'}, 400
            
            # ZIP-Datei aus dem Filesystem lesen (wird im Handler gespeichert)
            target_dir: Optional[str] = getattr(job.results, 'target_dir', None)
            if not target_dir:
                logger.warning(f"Download pages archive: Kein target_dir für Job {job_id}")
                return {'error': 'Kein Verarbeitungsverzeichnis verfügbar'}, 400
            
            # Dateiname aus structured_data holen (falls vorhanden)
            structured_data: Optional[Dict[str, Any]] = getattr(job.results, 'structured_data', None)
            pages_archive_filename: Optional[str] = None
            if structured_data:
                data_dict: Dict[str, Any] = structured_data.get('data', {})
                pages_archive_filename = data_dict.get('pages_archive_filename')
            
            # Standard-Dateiname falls nicht in structured_data
            filename = pages_archive_filename or f"pages-{job_id}.zip"
            pages_zip_path = os.path.join(target_dir, filename)
            
            # Prüfe ob Datei existiert
            if not os.path.exists(pages_zip_path):
                # Fallback: Suche nach pages.zip im Verzeichnis
                fallback_path = os.path.join(target_dir, "pages.zip")
                if os.path.exists(fallback_path):
                    pages_zip_path = fallback_path
                    filename = "pages.zip"
                else:
                    # Prüfe ob Verzeichnis existiert und liste Dateien auf (für Debugging)
                    if os.path.exists(target_dir):
                        try:
                            files_in_dir = os.listdir(target_dir)
                            logger.warning(f"Download pages archive: Datei nicht gefunden. Erwartet: {filename} oder pages.zip. Gefunden in {target_dir}: {files_in_dir[:10]}")
                        except Exception:
                            pass
                    job_status_any: Any = getattr(job, 'status', 'processing')
                    try:
                        status_str: str = str(job_status_any.value)  # type: ignore[attr-defined]
                    except Exception:
                        status_str = str(job_status_any)
                    if status_str in ("pending", "processing"):
                        return {'status': 'processing', 'message': 'Seiten-Archiv noch nicht bereit, bitte später erneut versuchen'}, 202
                    logger.error(f"Download pages archive: Kein Seiten-Archiv für Job {job_id} verfügbar. target_dir={target_dir}, filename={filename}")
                    return {'error': 'Kein Seiten-Archiv für diesen Job verfügbar. Stellen Sie sicher, dass includePageImages=true gesetzt war.'}, 400
            
            # Datei aus dem Filesystem lesen
            try:
                with open(pages_zip_path, 'rb') as f:
                    archive_bytes = f.read()
            except Exception as e:
                logger.error(f"Fehler beim Lesen der Seiten-Archive-Datei für Job {job_id}: {str(e)}")
                return {'error': 'Fehler beim Lesen der Archive-Datei'}, 500
            
            # ZIP als Response zurückgeben
            return Response(
                archive_bytes,
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Length': str(len(archive_bytes))
                }
            )
            
        except Exception as e:
            logger.error(f"Fehler beim Download des Seiten-Archives für Job {job_id}: {str(e)}", exc_info=True)
            return {'error': f'Fehler beim Download: {str(e)}'}, 500


@pdf_ns.route('/jobs/<string:job_id>/mistral-ocr-raw')  # type: ignore
class PDFJobMistralOCRRawEndpoint(Resource):
    @pdf_ns.doc(description='Lädt die vollständigen Mistral OCR Rohdaten (JSON) herunter (nur für Mistral OCR Jobs)')  # type: ignore
    @pdf_ns.response(200, 'JSON-Datei als Download')  # type: ignore
    @pdf_ns.response(404, 'Job nicht gefunden', error_model)  # type: ignore
    @pdf_ns.response(400, 'Keine Mistral OCR Daten verfügbar', error_model)  # type: ignore
    def get(self, job_id: str) -> Union[Response, Tuple[Dict[str, Any], int]]:
        """Lädt die vollständigen Mistral OCR Rohdaten (JSON) herunter"""
        try:
            job_repo = SecretaryJobRepository()
            job = job_repo.get_job(job_id)
            
            if not job:
                return {'error': 'Job nicht gefunden'}, 404
            
            if not job.results:
                status_any: Any = getattr(job, 'status', 'processing')
                try:
                    status_str: str = str(status_any.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str = str(status_any)
                if status_str in ("pending", "processing"):
                    return {'status': 'processing', 'message': 'Mistral OCR Daten noch nicht bereit, bitte später erneut versuchen'}, 202
                return {'error': 'Job hat keine Ergebnisse'}, 400
            
            # JSON-Datei aus dem Filesystem lesen (wird im Handler gespeichert)
            target_dir: Optional[str] = getattr(job.results, 'target_dir', None)
            if not target_dir:
                logger.warning(f"Download mistral_ocr_raw: Kein target_dir für Job {job_id}")
                return {'error': 'Kein Verarbeitungsverzeichnis verfügbar'}, 400
            
            # Dateiname bestimmen
            mistral_ocr_raw_filename = f"mistral_ocr_raw_{job_id}.json"
            mistral_ocr_raw_path = os.path.join(target_dir, mistral_ocr_raw_filename)
            
            # Prüfe ob Datei existiert
            if not os.path.exists(mistral_ocr_raw_path):
                job_status_any: Any = getattr(job, 'status', 'processing')
                try:
                    status_str: str = str(job_status_any.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str = str(job_status_any)
                if status_str in ("pending", "processing"):
                    return {'status': 'processing', 'message': 'Mistral OCR Daten noch nicht bereit, bitte später erneut versuchen'}, 202
                logger.error(f"Download mistral_ocr_raw: Datei nicht gefunden für Job {job_id}. Pfad: {mistral_ocr_raw_path}")
                return {'error': 'Keine Mistral OCR Daten für diesen Job verfügbar.'}, 400
            
            # Datei aus dem Filesystem lesen
            try:
                with open(mistral_ocr_raw_path, 'rb') as f:
                    file_bytes = f.read()
            except Exception as e:
                logger.error(f"Fehler beim Lesen der Mistral OCR Raw-Datei für Job {job_id}: {str(e)}")
                return {'error': 'Fehler beim Lesen der Datei'}, 500
            
            # JSON als Response zurückgeben
            return Response(
                file_bytes,
                mimetype='application/json',
                headers={
                    'Content-Disposition': f'attachment; filename="{mistral_ocr_raw_filename}"',
                    'Content-Length': str(len(file_bytes))
                }
            )
            
        except Exception as e:
            logger.error(f"Fehler beim Download der Mistral OCR Raw-Daten für Job {job_id}: {str(e)}", exc_info=True)
            return {'error': f'Fehler beim Download: {str(e)}'}, 500


@pdf_ns.route('/jobs/<string:job_id>/mistral-ocr-images')  # type: ignore
class PDFJobMistralOCRImagesEndpoint(Resource):
    @pdf_ns.doc(description='Lädt das ZIP-Archiv mit Mistral OCR extrahierten Bildern herunter (nur für Mistral OCR Jobs)')  # type: ignore
    @pdf_ns.response(200, 'ZIP-Datei als Download')  # type: ignore
    @pdf_ns.response(404, 'Job nicht gefunden', error_model)  # type: ignore
    @pdf_ns.response(400, 'Keine Mistral OCR Bilder verfügbar', error_model)  # type: ignore
    def get(self, job_id: str) -> Union[Response, Tuple[Dict[str, Any], int]]:
        """Lädt das ZIP-Archiv mit Mistral OCR extrahierten Bildern herunter"""
        try:
            job_repo = SecretaryJobRepository()
            job = job_repo.get_job(job_id)
            
            if not job:
                return {'error': 'Job nicht gefunden'}, 404
            
            if not job.results:
                status_any: Any = getattr(job, 'status', 'processing')
                try:
                    status_str: str = str(status_any.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str = str(status_any)
                if status_str in ("pending", "processing"):
                    return {'status': 'processing', 'message': 'Mistral OCR Bilder noch nicht bereit, bitte später erneut versuchen'}, 202
                return {'error': 'Job hat keine Ergebnisse'}, 400
            
            # ZIP-Datei aus dem Filesystem lesen (wird im Handler aus images_archive_data gespeichert)
            target_dir: Optional[str] = getattr(job.results, 'target_dir', None)
            if not target_dir:
                logger.warning(f"Download mistral_ocr_images: Kein target_dir für Job {job_id}")
                return {'error': 'Kein Verarbeitungsverzeichnis verfügbar'}, 400
            
            # Prüfe structured_data für Dateinamen
            structured_data: Optional[Dict[str, Any]] = getattr(job.results, 'structured_data', None)
            images_archive_filename: Optional[str] = None
            if structured_data:
                data_dict: Dict[str, Any] = structured_data.get('data', {})
                images_archive_filename = data_dict.get("images_archive_filename")
            
            # Standard-Dateiname falls nicht in structured_data
            filename = images_archive_filename or f"mistral_ocr_images_{job_id}.zip"
            images_zip_path = os.path.join(target_dir, filename)
            
            # Prüfe ob ZIP-Datei existiert (wird vom Handler aus images_archive_data erstellt)
            if not os.path.exists(images_zip_path):
                job_status_any: Any = getattr(job, 'status', 'processing')
                try:
                    status_str: str = str(job_status_any.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str = str(job_status_any)
                if status_str in ("pending", "processing"):
                    return {'status': 'processing', 'message': 'Mistral OCR Bilder noch nicht bereit, bitte später erneut versuchen'}, 202
                logger.error(f"Download mistral_ocr_images: ZIP-Datei nicht gefunden für Job {job_id}. Pfad: {images_zip_path}")
                return {'error': 'Keine Mistral OCR Bilder für diesen Job verfügbar. Die Bilder werden direkt im ZIP gespeichert.'}, 400
            
            # Datei aus dem Filesystem lesen
            try:
                with open(images_zip_path, 'rb') as f:
                    archive_bytes = f.read()
            except Exception as e:
                logger.error(f"Fehler beim Lesen der Mistral OCR Bilder-ZIP für Job {job_id}: {str(e)}")
                return {'error': 'Fehler beim Lesen der Datei'}, 500
            
            # ZIP als Response zurückgeben
            return Response(
                archive_bytes,
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Length': str(len(archive_bytes))
                }
            )
            
        except Exception as e:
            logger.error(f"Fehler beim Download der Mistral OCR Bilder für Job {job_id}: {str(e)}", exc_info=True)
            return {'error': f'Fehler beim Download: {str(e)}'}, 500

