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
from werkzeug.datastructures import FileStorage

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.processors.pdf_processor import PDFProcessor

# Logger initialisieren
logger = get_logger(__name__)

# Namespace für PDF-Routen
pdf_ns = Namespace('pdf', description='PDF-Verarbeitungsrouten')

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
                          choices=['native', 'ocr', 'both', 'preview', 'preview_and_native'],
                          help='Extraktionsmethode (native=nur Text, ocr=nur OCR, both=beides, preview=Vorschaubilder, preview_and_native=Vorschaubilder und Text)')
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
                          choices=['native', 'ocr', 'both', 'preview', 'preview_and_native'],
                          help='Extraktionsmethode (native=nur Text, ocr=nur OCR, both=beides, preview=Vorschaubilder, preview_and_native=Vorschaubilder und Text)')
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
            
            try:
                args = pdf_upload_parser.parse_args()  # type: ignore
                uploaded_file = cast(FileStorage, args['file'])
                extraction_method = str(args.get('extraction_method', 'native'))  # type: ignore
                template = str(args.get('template', '')) if args.get('template') else None  # type: ignore
                context_str = str(args.get('context', '')) if args.get('context') else None  # type: ignore
                context = json.loads(context_str) if context_str else None
                use_cache = bool(args.get('useCache', True))  # type: ignore
                include_images = bool(args.get('includeImages', False))  # type: ignore
                
                if not uploaded_file.filename:
                    raise ProcessingError("Kein Dateiname angegeben")
                
                # Initialisiere Processor, damit wir die konfigurierten Temp-Verzeichnisse nutzen können
                processor = get_pdf_processor(process_id)
                
                # Speichere Datei im konfigurierten temp-Verzeichnis des Prozessors
                # Die Suffix-Variable wird im späteren Code nicht verwendet, aber wir behalten sie für Klarheit
                _ = Path(uploaded_file.filename).suffix
                temp_file_path = os.path.join(os.path.dirname(__file__), f"temp_{uuid.uuid4()}.pdf")
                uploaded_file.save(temp_file_path)
                
                # Berechne den Hash der Datei für Cache-Key
                file_hash = calculate_file_hash(temp_file_path)
                
                if tracker:
                    with tracker.measure_operation('pdf_processing', 'PDFProcessor'):
                        result = await processor.process(
                            temp_file_path,
                            template=template,  # type: ignore
                            context=context,
                            extraction_method=extraction_method,  # type: ignore
                            use_cache=use_cache,
                            file_hash=file_hash,
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
                args = pdf_url_parser.parse_args()  # type: ignore
                url = str(args.get('url', ''))  # type: ignore
                extraction_method = str(args.get('extraction_method', 'native'))  # type: ignore
                template = str(args.get('template', '')) if args.get('template') else None  # type: ignore
                context_str = str(args.get('context', '')) if args.get('context') else None  # type: ignore
                context = json.loads(context_str) if context_str else None
                use_cache = bool(args.get('useCache', True))  # type: ignore
                include_images = bool(args.get('includeImages', False))  # type: ignore
                
                if not url:
                    raise ProcessingError("Keine URL angegeben")
                
                # Berechne einen Hash aus der URL als Cache-Key-Komponente
                # (Bei URLs ist das besser als nichts, obwohl der Dateiinhalt sich ändern könnte)
                url_hash = hashlib.md5(url.encode()).hexdigest()
                
                # Verarbeitung der PDF-Datei direkt von URL
                processor: PDFProcessor = get_pdf_processor(process_id)
                
                if tracker:
                    with tracker.measure_operation('pdf_processing', 'PDFProcessor'):
                        result = await processor.process(
                            file_path=url,  # type: ignore
                            template=template,  # type: ignore
                            context=context,
                            extraction_method=extraction_method,  # type: ignore
                            use_cache=use_cache,
                            file_hash=url_hash,
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