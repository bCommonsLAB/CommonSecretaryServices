"""
API-Route für die OCR-Verarbeitung von Bildern.
"""
# pyright: reportUnknownMemberType=warning, reportUnknownParameterType=warning, reportUnknownVariableType=warning
import os
import uuid
import json
import asyncio
import hashlib
from typing import Dict, Any, Union, Optional, cast
from pathlib import Path

from flask_restx import Namespace, Resource, fields, inputs  # type: ignore
from flask_restx.reqparse import RequestParser  # type: ignore
from werkzeug.datastructures import FileStorage

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker, PerformanceTracker
from src.processors.imageocr_processor import (
    ImageOCRProcessor, 
    ImageOCRResponse, 
    EXTRACTION_OCR  # Nur diese Konstante wird verwendet
)

# Logger initialisieren
logger = get_logger(__name__)

# Namespace für ImageOCR-bezogene API-Routen
imageocr_ns = Namespace('imageocr', description='Bild-OCR-Verarbeitungs-Endpunkte')

# ImageOCR Upload Parser
imageocr_upload_parser: RequestParser = imageocr_ns.parser()
imageocr_upload_parser.add_argument('file', type=FileStorage, location='files', required=True, help='Bilddatei')  # type: ignore
imageocr_upload_parser.add_argument('template', type=str, location='form', required=False, help='Template für die Transformation')  # type: ignore
imageocr_upload_parser.add_argument('context', type=str, location='form', required=False, help='JSON-Kontext für die Verarbeitung')  # type: ignore
imageocr_upload_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')  # type: ignore
imageocr_upload_parser.add_argument('extraction_method', type=str, location='form', default=EXTRACTION_OCR, 
                                   choices=['ocr', 'native', 'both', 'preview', 'preview_and_native', 'llm', 'llm_and_ocr'],
                                   help='Extraktionsmethode: ocr=Tesseract OCR, native=Native Analyse, both=OCR+Native, preview=Vorschaubilder, preview_and_native=Vorschaubilder+Native, llm=LLM-basierte OCR, llm_and_ocr=LLM+OCR')  # type: ignore

# ImageOCR URL Parser
imageocr_url_parser: RequestParser = imageocr_ns.parser()
imageocr_url_parser.add_argument('url', type=str, location='form', required=True, help='URL zur Bilddatei')  # type: ignore
imageocr_url_parser.add_argument('template', type=str, location='form', required=False, help='Template für die Transformation')  # type: ignore
imageocr_url_parser.add_argument('context', type=str, location='form', required=False, help='JSON-Kontext für die Verarbeitung')  # type: ignore
imageocr_url_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')  # type: ignore
imageocr_url_parser.add_argument('extraction_method', type=str, location='form', default=EXTRACTION_OCR,
                                choices=['ocr', 'native', 'both', 'preview', 'preview_and_native', 'llm', 'llm_and_ocr'],
                                help='Extraktionsmethode: ocr=Tesseract OCR, native=Native Analyse, both=OCR+Native, preview=Vorschaubilder, preview_and_native=Vorschaubilder+Native, llm=LLM-basierte OCR, llm_and_ocr=LLM+OCR')  # type: ignore

# ImageOCR Antwortmodell
imageocr_response = imageocr_ns.model('ImageOCRResponse', {  # type: ignore
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(imageocr_ns.model('ImageOCRRequestInfo', {  # type: ignore
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(imageocr_ns.model('ImageOCRProcessInfo', {  # type: ignore
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'sub_processors': fields.List(fields.String, description='Verwendete Sub-Prozessoren'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
    })),
    'data': fields.Nested(imageocr_ns.model('ImageOCRData', {  # type: ignore
        'metadata': fields.Nested(imageocr_ns.model('ImageOCRMetadata', {  # type: ignore
            'file_name': fields.String(description='Dateiname'),
            'file_size': fields.Integer(description='Dateigröße in Bytes'),
            'dimensions': fields.String(description='Bildabmessungen'),
            'format': fields.String(description='Bildformat'),
            'process_dir': fields.String(description='Verarbeitungsverzeichnis')
        })),
        'extracted_text': fields.String(description='Via OCR extrahierter Text'),
        'formatted_text': fields.String(description='Formatierter Text (falls Template verwendet)'),
        'process_id': fields.String(description='Prozess-ID'),
        'model': fields.String(description='Verwendetes OCR-Modell')
    })),
    'error': fields.Nested(imageocr_ns.model('ImageOCRError', {  # type: ignore
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Error-Modell
error_model = imageocr_ns.model('Error', {  # type: ignore
    'error': fields.String(description='Fehlermeldung')
})

def get_imageocr_processor(process_id: Optional[str] = None) -> ImageOCRProcessor:
    """Erstellt eine neue ImageOCRProcessor-Instanz mit dem angegebenen Prozess-ID."""
    from src.core.resource_tracking import ResourceCalculator
    return ImageOCRProcessor(ResourceCalculator(), process_id)

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

@imageocr_ns.route('/process')  # type: ignore
class ImageOCREndpoint(Resource):
    @imageocr_ns.expect(imageocr_upload_parser)  # type: ignore
    @imageocr_ns.response(200, 'Erfolg', imageocr_response)  # type: ignore
    @imageocr_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @imageocr_ns.doc(description='Verarbeitet ein Bild und extrahiert Text mittels OCR. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Bild mit OCR verarbeiten"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            args: ParseResult = imageocr_upload_parser.parse_args()  # type: ignore
            uploaded_file: FileStorage = cast(FileStorage, args.get('file'))  # type: ignore
            template = str(args.get('template', '')) if args.get('template') else None  # type: ignore
            context_str = str(args.get('context', '')) if args.get('context') else None  # type: ignore
            context = json.loads(context_str) if context_str else None
            use_cache = bool(args.get('useCache', True))  # type: ignore
            process_id = str(uuid.uuid4())
            temp_file_path: str = ""  # Initialisierung für Linter
            
            try:
                # Prüfe, ob eine Datei hochgeladen wurde
                if not uploaded_file.filename:
                    raise ProcessingError("Keine Datei hochgeladen")
                
                # Initialisiere Processor und Tracker
                imageocr_processor: ImageOCRProcessor = get_imageocr_processor(process_id)
                tracker: Optional[PerformanceTracker] = get_performance_tracker()
                
                # Speichere die Datei temporär
                temp_file_path = os.path.join(os.path.dirname(__file__), f"temp_{uuid.uuid4()}{Path(uploaded_file.filename).suffix}")
                uploaded_file.save(temp_file_path)
                
                # Berechne den Hash der Datei für Cache-Key
                file_hash = calculate_file_hash(temp_file_path)
                
                # Verarbeite die Datei
                processing_result: ImageOCRResponse
                if tracker:
                    with tracker.measure_operation('imageocr_processing', 'ImageOCRProcessor'):
                        processing_result = await imageocr_processor.process(
                            temp_file_path,
                            template=template,  # type: ignore
                            context=context,
                            use_cache=use_cache,
                            file_hash=file_hash,
                            extraction_method=args.get('extraction_method', EXTRACTION_OCR)  # type: ignore
                        )
                        tracker.eval_result(processing_result)
                else:
                    processing_result = await imageocr_processor.process(
                        temp_file_path,
                        template=template,  # type: ignore
                        context=context,
                        use_cache=use_cache,
                        file_hash=file_hash,
                        extraction_method=args.get('extraction_method', EXTRACTION_OCR)  # type: ignore
                    )
                
                result: ImageOCRResponse = processing_result
                
                return result.to_dict()
                
            except Exception as e:
                logger.error("Fehler bei der Bild-OCR-Verarbeitung", error=e)
                return {
                    'status': 'error',
                    'error': {
                        'code': type(e).__name__,
                        'message': str(e),
                        'details': {
                            'error_type': type(e).__name__,
                            'traceback': str(e)
                        }
                    }
                }, 400
            finally:
                # Lösche die temporäre Datei
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception as e:
                        logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")
        
        # Führe die asynchrone Verarbeitung aus
        return asyncio.run(process_request())

@imageocr_ns.route('/process-url')  # type: ignore
class ImageOCRUrlEndpoint(Resource):
    @imageocr_ns.expect(imageocr_url_parser)  # type: ignore
    @imageocr_ns.response(200, 'Erfolg', imageocr_response)  # type: ignore
    @imageocr_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @imageocr_ns.doc(description='Verarbeitet ein Bild von einer URL und extrahiert Text mittels OCR. Unterstützt HTTP/HTTPS URLs, die auf Bilddateien (.png, .jpg, .jpeg) verweisen. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Bild von URL (HTTP/HTTPS) mit OCR verarbeiten"""
        async def process_request() -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
            args: ParseResult = imageocr_url_parser.parse_args()  # type: ignore
            url = str(args.get('url', ''))  # type: ignore
            template = str(args.get('template', '')) if args.get('template') else None  # type: ignore
            context_str = str(args.get('context', '')) if args.get('context') else None  # type: ignore
            context = json.loads(context_str) if context_str else None
            use_cache = bool(args.get('useCache', True))  # type: ignore
                
            if not url:
                raise ProcessingError("Keine URL angegeben")
            
            process_id = str(uuid.uuid4())
            
            try:
                # Berechne einen Hash aus der URL für den Cache
                url_hash = hashlib.md5(url.encode()).hexdigest()  # type: ignore
                
                # Initialisiere Processor und Tracker
                imageocr_processor: ImageOCRProcessor = get_imageocr_processor(process_id)
                tracker: Optional[PerformanceTracker] = get_performance_tracker()
                
                # Verarbeite das Bild direkt von der URL
                url_processing_result: ImageOCRResponse
                if tracker:
                    with tracker.measure_operation('imageocr_processing', 'ImageOCRProcessor'):
                        url_processing_result = await imageocr_processor.process(
                            url,  # type: ignore
                            template=template,  # type: ignore
                            context=context,
                            use_cache=use_cache,
                            file_hash=url_hash,
                            extraction_method=args.get('extraction_method', EXTRACTION_OCR)  # type: ignore
                        )
                        tracker.eval_result(url_processing_result)
                else:
                    url_processing_result = await imageocr_processor.process(
                        url,  # type: ignore
                        template=template,  # type: ignore
                        context=context,
                        use_cache=use_cache,
                        file_hash=url_hash,
                        extraction_method=args.get('extraction_method', EXTRACTION_OCR)  # type: ignore
                    )
                
                result: ImageOCRResponse = url_processing_result
                
                return result.to_dict()
                
            except Exception as e:
                logger.error("Fehler bei der Bild-OCR-Verarbeitung von URL", error=e)
                return {
                    'status': 'error',
                    'error': {
                        'code': type(e).__name__,
                        'message': str(e),
                        'details': {
                            'error_type': type(e).__name__,
                            'traceback': str(e)
                        }
                    }
                }, 400
        
        # Führe die asynchrone Verarbeitung aus
        return asyncio.run(process_request()) 