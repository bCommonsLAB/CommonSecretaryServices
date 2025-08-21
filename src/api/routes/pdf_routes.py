"""
API-Route für die PDF-Verarbeitung.
"""
import os
import traceback
import uuid
import json
import asyncio
import hashlib
from typing import Dict, Any, Union, Optional, cast
from pathlib import Path

from flask_restx import Namespace, Resource, fields, inputs  # type: ignore
from flask import request  # type: ignore
from werkzeug.datastructures import FileStorage
import threading
import time
import requests  # type: ignore

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.processors.pdf_processor import PDFProcessor

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
                          choices=['native', 'ocr', 'both', 'preview', 'preview_and_native', 'llm', 'llm_and_native', 'llm_and_ocr'],
                          help='Extraktionsmethode (native=nur Text, ocr=nur OCR, both=beides, preview=Vorschaubilder, preview_and_native=Vorschaubilder und Text, llm=LLM-basierte OCR, llm_and_native=LLM+Native, llm_and_ocr=LLM+Tesseract)')
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
                          help='Base64-kodiertes ZIP-Archiv mit Bildern erstellen (default: False)')
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
                          choices=['native', 'ocr', 'both', 'preview', 'preview_and_native', 'llm', 'llm_and_native', 'llm_and_ocr'],
                          help='Extraktionsmethode (native=nur Text, ocr=nur OCR, both=beides, preview=Vorschaubilder, preview_and_native=Vorschaubilder und Text, llm=LLM-basierte OCR, llm_and_native=LLM+Native, llm_and_ocr=LLM+Tesseract)')
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
                          help='Base64-kodiertes ZIP-Archiv mit Bildern erstellen (default: False)')
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
        'images_archive_data': fields.String(description='Base64-kodiertes ZIP-Archiv mit allen generierten Bildern'),
        'images_archive_filename': fields.String(description='Dateiname des Bilder-Archives')
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
            tracker = get_performance_tracker()
            process_id = str(uuid.uuid4())
            # Initialisiere Variablen, die später innerhalb von try-except verwendet werden
            temp_file_path: str = ""  # Initialisierung für Linter
            callback_url: Optional[str] = None  # Für finally: entscheidet über Cleanup
            
            try:
                # Eingehende Form-/Header-Daten für Debugging loggen (Token maskiert)
                try:
                    headers_data = _collect_headers_subset()
                    form_data = _raw_form_with_redaction()
                    print(f"[PDF-ROUTE] Eingehende PDF-Anfrage:")
                    print(f"[PDF-ROUTE] Headers: {headers_data}")
                    print(f"[PDF-ROUTE] Form: {form_data}")
                    logger.info(
                        "Eingehende PDF-Anfrage (multipart)",
                        headers=headers_data,
                        form=form_data
                    )
                except Exception as e:
                    print(f"[PDF-ROUTE] Logger-Fehler: {e}")
                    pass

                # Lese jobId frühzeitig direkt aus dem Request, um Parser-Eigenheiten zu umgehen
                job_id_form_early = None
                try:
                    job_id_form_early = request.form.get('jobId')  # type: ignore
                except Exception:
                    job_id_form_early = None
                args = pdf_upload_parser.parse_args()  # type: ignore
                uploaded_file = cast(FileStorage, args['file'])
                extraction_method = str(args.get('extraction_method', 'native'))  # type: ignore
                template = str(args.get('template', '')) if args.get('template') else None  # type: ignore
                context_str = str(args.get('context', '')) if args.get('context') else None  # type: ignore
                context = json.loads(context_str) if context_str else None
                use_cache = bool(args.get('useCache', True))  # type: ignore
                include_images = bool(args.get('includeImages', False))  # type: ignore
                target_language = str(args.get('target_language', '')) if args.get('target_language') else None  # type: ignore
                callback_url = str(args.get('callback_url', '')) if args.get('callback_url') else None  # type: ignore
                callback_token = str(args.get('callback_token', '')) if args.get('callback_token') else None  # type: ignore
                # Bevorzuge früh gelesene jobId; fallback auf Parser-Wert
                job_id_form = None
                if job_id_form_early and str(job_id_form_early).strip():
                    job_id_form = str(job_id_form_early).strip()
                elif args.get('jobId'):
                    job_id_form = str(args.get('jobId')).strip()  # type: ignore
                force_refresh = bool(args.get('force_refresh', False))  # type: ignore
                
                if not uploaded_file.filename:
                    raise ProcessingError("Kein Dateiname angegeben")
                
                # Initialisiere Processor, damit wir die konfigurierten Temp-Verzeichnisse nutzen können
                processor = get_pdf_processor(process_id)
                
                # Speichere Datei im Upload-Unterordner des Prozessors
                _ = Path(uploaded_file.filename).suffix
                upload_dir = Path(processor.temp_dir) / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                temp_file_path = str(upload_dir / f"upload_{uuid.uuid4()}.pdf")
                uploaded_file.save(temp_file_path)
                
                # Berechne den Hash der Datei für Cache-Key
                file_hash = calculate_file_hash(temp_file_path)
                
                # Wenn ein Callback angegeben ist, führen wir die Verarbeitung im Hintergrund aus
                if callback_url:
                    # Leite Job-ID ab (Form jobId bevorzugen)
                    job_id: str = job_id_form or f"job-{uuid.uuid4()}"
                    print(f"[PDF-ROUTE] jobId gewählt: {job_id} (form={job_id_form}, early={job_id_form_early})")

                    def _background_task() -> None:
                        async def _run() -> None:
                            local_tracker = get_performance_tracker()
                            try:
                                if local_tracker:
                                    with processor.measure_operation('pdf_processing'):
                                        result = await processor.process(
                                            temp_file_path,
                                            template=template,  # type: ignore
                                            context=context,
                                            extraction_method=extraction_method,  # type: ignore
                                            use_cache=use_cache,
                                            file_hash=file_hash,
                                            force_overwrite=bool(force_refresh),
                                            include_images=include_images
                                        )
                                        local_tracker.eval_result(result)
                                else:
                                    result = await processor.process(
                                        temp_file_path,
                                        template=template,  # type: ignore
                                        context=context,
                                        extraction_method=extraction_method,  # type: ignore
                                        use_cache=use_cache,
                                        file_hash=file_hash,
                                        force_overwrite=bool(force_refresh),
                                        include_images=include_images
                                    )

                                result_dict = result.to_dict()
                                # Baue Webhook-Payload
                                payload: Dict[str, Any] = {
                                    'status': 'completed',
                                    'worker': 'secretary',
                                    'jobId': job_id,
                                    'process': result_dict.get('process', {}),
                                    'data': result_dict.get('data'),
                                    'error': None
                                }
                                if callback_token:
                                    # Kompatibilität: Token zusätzlich im Body mitsenden
                                    payload['callback_token'] = callback_token
                                headers: Dict[str, str] = {
                                    'Content-Type': 'application/json'
                                }
                                try:
                                    print(f"[PDF-ROUTE] Sende Webhook-Callback an {callback_url}")
                                    print(f"[PDF-ROUTE] Job-ID: {job_id}, Hat Token: {bool(callback_token)}")
                                    print(f"[PDF-ROUTE] Payload-Übersicht:")
                                    print(f"[PDF-ROUTE]   - jobId: {payload.get('jobId')}")
                                    print(f"[PDF-ROUTE]   - status: {payload.get('status')}")
                                    print(f"[PDF-ROUTE]   - worker: {payload.get('worker')}")
                                    # correlation wurde entfernt
                                    print(f"[PDF-ROUTE]   - data keys: {list(payload.get('data', {}).keys()) if payload.get('data') else 'None'}")
                                    print(f"[PDF-ROUTE] Headers: {headers}")
                                    
                                    # Vollständige Payload für Debug (gekürzt)
                                    logger.info(
                                        "Sende Webhook-Callback",
                                        process_id=process_id,
                                        job_id=job_id,
                                        callback_url=callback_url,
                                        has_token=bool(callback_token)
                                    )
                                    response = requests.post(url=callback_url, json=payload, headers=headers, timeout=30)
                                    print(f"[PDF-ROUTE] Webhook-Antwort: Status {response.status_code}, OK: {response.ok}")
                                    if response.text:
                                        print(f"[PDF-ROUTE] Response Body: {response.text[:500]}...")
                                    logger.info(
                                        "Webhook-Callback Antwort",
                                        status_code=getattr(response, 'status_code', None),
                                        ok=getattr(response, 'ok', None)
                                    )
                                except Exception as post_err:
                                    print(f"[PDF-ROUTE] Webhook-POST fehlgeschlagen: {str(post_err)}")
                                    logger.error(f"Webhook-POST fehlgeschlagen: {str(post_err)}")
                            except Exception as proc_err:
                                # Fehler-Callback senden
                                error_payload: Dict[str, Any] = {
                                    'status': 'error',
                                    'worker': 'secretary',
                                    'jobId': job_id,
                                    'process': {
                                        'id': process_id,
                                        'main_processor': 'pdf',
                                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                                    },
                                    'data': None,
                                    'error': {
                                        'code': type(proc_err).__name__,
                                        'message': str(proc_err)
                                    }
                                }
                                if callback_token:
                                    error_payload['callback_token'] = callback_token
                                headers_err: Dict[str, str] = {'Content-Type': 'application/json'}
                                try:
                                    print(f"[PDF-ROUTE] Sende Webhook-Error-Callback an {callback_url}")
                                    print(f"[PDF-ROUTE] Job-ID: {job_id}")
                                    logger.info(
                                        "Sende Webhook-Error-Callback",
                                        process_id=process_id,
                                        job_id=job_id,
                                        callback_url=callback_url
                                    )
                                    response_err = requests.post(url=callback_url, json=error_payload, headers=headers_err, timeout=30)
                                    print(f"[PDF-ROUTE] Webhook-Error-Antwort: Status {response_err.status_code}, OK: {response_err.ok}")
                                    logger.info(
                                        "Webhook-Error-Callback Antwort",
                                        status_code=getattr(response_err, 'status_code', None),
                                        ok=getattr(response_err, 'ok', None)
                                    )
                                except Exception as post_err2:
                                    logger.error(f"Webhook-Fehler-POST fehlgeschlagen: {str(post_err2)}")
                            finally:
                                # Aufräumen
                                try:
                                    if temp_file_path and os.path.exists(temp_file_path):
                                        os.unlink(temp_file_path)
                                except Exception as cleanup_err:
                                    logger.warning(f"Cleanup-Fehler: {str(cleanup_err)}")

                        asyncio.run(_run())

                    threading.Thread(target=_background_task, daemon=True).start()

                    # Sofortiges ACK zurückgeben
                    ack: Dict[str, Any] = {
                        'status': 'accepted',
                        'worker': 'secretary',
                        'process': {
                            'id': process_id,
                            'main_processor': 'pdf',
                            'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'is_from_cache': False
                        },
                        'job': {'id': job_id},
                        'webhook': {'delivered_to': callback_url},
                        'error': None
                    }
                    try:
                        print(f"[PDF-ROUTE] Webhook-ACK gesendet:")
                        print(f"[PDF-ROUTE] Process-ID: {process_id}")
                        print(f"[PDF-ROUTE] Job-ID: {job_id}")
                        print(f"[PDF-ROUTE] Callback-URL: {callback_url}")
                        print(f"[PDF-ROUTE] Args: extraction_method={extraction_method}, use_cache={use_cache}")
                        logger.info(
                            "Webhook-ACK gesendet",
                            process_id=process_id,
                            job_id=job_id,
                            callback_url=callback_url,
                            endpoint="/api/pdf/process",
                            parsed_args={
                                'extraction_method': extraction_method,
                                'template': template,
                                'use_cache': use_cache,
                                'include_images': include_images,
                                'target_language': target_language,
                                'force_refresh': force_refresh,
                                # deprecated: correlation entfernt
                            }
                        )
                    except Exception as e:
                        print(f"[PDF-ROUTE] Webhook-ACK Logger-Fehler: {e}")
                        pass
                    return ack, 202

                # Kein Callback -> synchron wie bisher
                if tracker:
                    with processor.measure_operation('pdf_processing'):
                        result = await processor.process(
                            temp_file_path,
                            template=template,  # type: ignore
                            context=context,
                            extraction_method=extraction_method,  # type: ignore
                            use_cache=use_cache,
                            file_hash=file_hash,
                            force_overwrite=bool(force_refresh),
                            include_images=include_images
                        )
                        tracker.eval_result(result)
                else:
                    result = await processor.process(
                        temp_file_path,
                        template=template,  # type: ignore
                        context=context,
                        extraction_method=extraction_method,  # type: ignore
                        use_cache=use_cache,
                        file_hash=file_hash,
                        force_overwrite=bool(force_refresh),
                        include_images=include_images
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
                # Nur synchron bereinigen. Bei asynchroner Verarbeitung übernimmt der Hintergrund-Task das Cleanup.
                if not callback_url:
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.unlink(temp_file_path)
                        except Exception as e:
                            logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
        
        # Führe die asynchrone Verarbeitung aus
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
            tracker = get_performance_tracker()
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
                url = str(args.get('url', ''))  # type: ignore
                extraction_method = str(args.get('extraction_method', 'native'))  # type: ignore
                template = str(args.get('template', '')) if args.get('template') else None  # type: ignore
                context_str = str(args.get('context', '')) if args.get('context') else None  # type: ignore
                context = json.loads(context_str) if context_str else None
                use_cache = bool(args.get('useCache', True))  # type: ignore
                include_images = bool(args.get('includeImages', False))  # type: ignore
                target_language = str(args.get('target_language', '')) if args.get('target_language') else None  # type: ignore
                callback_url = str(args.get('callback_url', '')) if args.get('callback_url') else None  # type: ignore
                callback_token = str(args.get('callback_token', '')) if args.get('callback_token') else None  # type: ignore
                job_id_form = str(args.get('jobId', '')) if args.get('jobId') else None  # type: ignore
                force_refresh = bool(args.get('force_refresh', False))  # type: ignore
                
                if not url:
                    raise ProcessingError("Keine URL angegeben")
                
                # Berechne einen Hash aus der URL als Cache-Key-Komponente
                # (Bei URLs ist das besser als nichts, obwohl der Dateiinhalt sich ändern könnte)
                url_hash = hashlib.md5(url.encode()).hexdigest()
                
                # Verarbeitung der PDF-Datei direkt von URL
                processor: PDFProcessor = get_pdf_processor(process_id)
                
                if callback_url:
                    job_id: str = job_id_form or f"job-{uuid.uuid4()}"

                    def _background_task_url() -> None:
                        async def _run() -> None:
                            local_tracker = get_performance_tracker()
                            try:
                                if local_tracker:
                                    with processor.measure_operation('pdf_processing'):
                                        result = await processor.process(
                                            file_path=url,  # type: ignore
                                            template=template,  # type: ignore
                                            context=context,
                                            extraction_method=extraction_method,  # type: ignore
                                            use_cache=use_cache,
                                            file_hash=url_hash,
                                            force_overwrite=bool(force_refresh),
                                            include_images=include_images
                                        )
                                        local_tracker.eval_result(result)
                                else:
                                    result = await processor.process(
                                        file_path=url,  # type: ignore
                                        template=template,  # type: ignore
                                        context=context,
                                        extraction_method=extraction_method,  # type: ignore
                                        use_cache=use_cache,
                                        file_hash=url_hash,
                                        force_overwrite=bool(force_refresh),
                                        include_images=include_images
                                    )

                                result_dict = result.to_dict()
                                payload: Dict[str, Any] = {
                                    'status': 'completed',
                                    'worker': 'secretary',
                                    'jobId': job_id,
                                    'process': result_dict.get('process', {}),
                                    'data': result_dict.get('data'),
                                    'error': None
                                }
                                headers: Dict[str, str] = {'Content-Type': 'application/json'}
                                if callback_token:
                                    headers['Authorization'] = f"Bearer {callback_token}"
                                    headers['X-Callback-Token'] = callback_token
                                try:
                                    print(f"[PDF-ROUTE] Sende Webhook-Callback an {callback_url}")
                                    print(f"[PDF-ROUTE] Job-ID: {job_id}, Hat Token: {bool(callback_token)}")
                                    print(f"[PDF-ROUTE] Payload-Übersicht:")
                                    print(f"[PDF-ROUTE]   - jobId: {payload.get('jobId')}")
                                    print(f"[PDF-ROUTE]   - status: {payload.get('status')}")
                                    print(f"[PDF-ROUTE]   - worker: {payload.get('worker')}")
                                    # correlation wurde entfernt
                                    print(f"[PDF-ROUTE]   - data keys: {list(payload.get('data', {}).keys()) if payload.get('data') else 'None'}")
                                    print(f"[PDF-ROUTE] Headers: {headers}")
                                    
                                    # Vollständige Payload für Debug (gekürzt)
                                    import json as json_module
                                    payload_str = json_module.dumps(payload, indent=2, ensure_ascii=False)
                                    if len(payload_str) > 2000:
                                        payload_preview = payload_str[:2000] + "...[GEKÜRZT]"
                                    else:
                                        payload_preview = payload_str
                                    print(f"[PDF-ROUTE] Vollständige Payload:\n{payload_preview}")
                                    
                                    logger.info(
                                        "Sende Webhook-Callback",
                                        process_id=process_id,
                                        job_id=job_id,
                                        callback_url=callback_url,
                                        has_token=bool(callback_token)
                                    )
                                    response = requests.post(url=callback_url, json=payload, headers=headers, timeout=30)
                                    print(f"[PDF-ROUTE] Webhook-Antwort: Status {response.status_code}, OK: {response.ok}")
                                    if response.text:
                                        print(f"[PDF-ROUTE] Response Body: {response.text[:500]}...")
                                    logger.info(
                                        "Webhook-Callback Antwort",
                                        status_code=getattr(response, 'status_code', None),
                                        ok=getattr(response, 'ok', None)
                                    )
                                except Exception as post_err:
                                    print(f"[PDF-ROUTE] Webhook-POST fehlgeschlagen: {str(post_err)}")
                                    logger.error(f"Webhook-POST fehlgeschlagen: {str(post_err)}")
                            except Exception as proc_err:
                                error_payload: Dict[str, Any] = {
                                    'status': 'error',
                                    'worker': 'secretary',
                                    'jobId': job_id,
                                    'process': {
                                        'id': process_id,
                                        'main_processor': 'pdf',
                                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                                    },
                                    'data': None,
                                    'error': {
                                        'code': type(proc_err).__name__,
                                        'message': str(proc_err)
                                    }
                                }
                                headers_err: Dict[str, str] = {'Content-Type': 'application/json'}
                                if callback_token:
                                    headers_err['Authorization'] = f"Bearer {callback_token}"
                                    headers_err['X-Callback-Token'] = callback_token
                                try:
                                    logger.info(
                                        "Sende Webhook-Error-Callback",
                                        process_id=process_id,
                                        job_id=job_id,
                                        callback_url=callback_url
                                    )
                                    response_err = requests.post(url=callback_url, json=error_payload, headers=headers_err, timeout=30)
                                    logger.info(
                                        "Webhook-Error-Callback Antwort",
                                        status_code=getattr(response_err, 'status_code', None),
                                        ok=getattr(response_err, 'ok', None)
                                    )
                                except Exception as post_err2:
                                    logger.error(f"Webhook-Fehler-POST fehlgeschlagen: {str(post_err2)}")

                        asyncio.run(_run())

                    threading.Thread(target=_background_task_url, daemon=True).start()

                    ack: Dict[str, Any] = {
                        'status': 'accepted',
                        'worker': 'secretary',
                        'process': {
                            'id': process_id,
                            'main_processor': 'pdf',
                            'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'is_from_cache': False
                        },
                        'job': {'id': job_id},
                        'webhook': {'delivered_to': callback_url},
                        'error': None
                    }
                    try:
                        logger.info(
                            "Webhook-ACK gesendet",
                            process_id=process_id,
                            job_id=job_id,
                            callback_url=callback_url,
                            endpoint="/api/pdf/process-url",
                            parsed_args={
                                'extraction_method': extraction_method,
                                'template': template,
                                'use_cache': use_cache,
                                'include_images': include_images,
                                'target_language': target_language,
                                'force_refresh': force_refresh,
                                # deprecated: correlation entfernt,
                                'url': url
                            }
                        )
                    except Exception:
                        pass
                    return ack, 202

                if tracker:
                    with processor.measure_operation('pdf_processing'):
                        result = await processor.process(
                            file_path=url,  # type: ignore
                            template=template,  # type: ignore
                            context=context,
                            extraction_method=extraction_method,  # type: ignore
                            use_cache=use_cache,
                            file_hash=url_hash,
                            force_overwrite=bool(force_refresh),
                            include_images=include_images
                        )
                        tracker.eval_result(result)
                else:
                    result = await processor.process(
                        file_path=url,  # type: ignore
                        template=template,  # type: ignore
                        context=context,
                        extraction_method=extraction_method,  # type: ignore
                        use_cache=use_cache,
                        file_hash=url_hash,
                        force_overwrite=bool(force_refresh),
                        include_images=include_images
                    )
                
                return result.to_dict()
                
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