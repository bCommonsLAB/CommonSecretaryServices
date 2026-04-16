"""
@fileoverview Image Analyzer API Routes - Endpoints für template-basierte Bildanalyse

@description
API-Routen für die Analyse und Klassifizierung von Bildern anhand von Templates.
Analog zum Transformer-Template-Endpoint, aber mit Bildern statt Text als Input.

Endpoints:
- POST /api/image-analyzer/process: Bild-Upload + Template-Analyse
- POST /api/image-analyzer/process-url: Bild-URL + Template-Analyse

@module api.routes.image_analyzer_routes

@exports
- image_analyzer_ns: Namespace - Flask-RESTX Namespace

@usedIn
- src.api.routes.__init__: Registriert image_analyzer_ns

@dependencies
- Internal: src.processors.image_analyzer_processor - ImageAnalyzerProcessor
"""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import os
import uuid
import json
import hashlib
from typing import Any, Dict, Optional, Union, cast
from pathlib import Path

from flask_restx import Namespace, Resource, fields, inputs  # type: ignore
from flask_restx.reqparse import RequestParser  # type: ignore
from werkzeug.datastructures import FileStorage

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.processors.image_analyzer_processor import ImageAnalyzerProcessor

logger = get_logger(__name__)

# --- Namespace ---

image_analyzer_ns = Namespace(
    'image-analyzer',
    description='Template-basierte Bildanalyse und Klassifizierung'
)

# --- Parser für Upload ---

upload_parser: RequestParser = image_analyzer_ns.parser()
upload_parser.add_argument('file', type=FileStorage, location='files', required=True, help='Bilddatei (JPG, PNG, WebP, GIF)')  # type: ignore
upload_parser.add_argument('template', type=str, location='form', required=False, help='Name des Templates (z.B. "image_classify")')  # type: ignore
upload_parser.add_argument('template_content', type=str, location='form', required=False, help='Direkter Template-Inhalt')  # type: ignore
upload_parser.add_argument('context', type=str, location='form', required=False, help='JSON-Kontext')  # type: ignore
upload_parser.add_argument('additional_field_descriptions', type=str, location='form', required=False, help='Zusätzliche Feldbeschreibungen als JSON')  # type: ignore
upload_parser.add_argument('target_language', type=str, location='form', default='de', help='Zielsprache (ISO 639-1, default: de)')  # type: ignore
upload_parser.add_argument('model', type=str, location='form', required=False, help='Modell-Override')  # type: ignore
upload_parser.add_argument('provider', type=str, location='form', required=False, help='Provider-Override')  # type: ignore
upload_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')  # type: ignore

# --- Parser für URL ---

url_parser: RequestParser = image_analyzer_ns.parser()
url_parser.add_argument('url', type=str, location='form', required=True, help='URL zur Bilddatei')  # type: ignore
url_parser.add_argument('template', type=str, location='form', required=False, help='Name des Templates')  # type: ignore
url_parser.add_argument('template_content', type=str, location='form', required=False, help='Direkter Template-Inhalt')  # type: ignore
url_parser.add_argument('context', type=str, location='form', required=False, help='JSON-Kontext')  # type: ignore
url_parser.add_argument('additional_field_descriptions', type=str, location='form', required=False, help='Zusätzliche Feldbeschreibungen als JSON')  # type: ignore
url_parser.add_argument('target_language', type=str, location='form', default='de', help='Zielsprache (ISO 639-1, default: de)')  # type: ignore
url_parser.add_argument('model', type=str, location='form', required=False, help='Modell-Override')  # type: ignore
url_parser.add_argument('provider', type=str, location='form', required=False, help='Provider-Override')  # type: ignore
url_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')  # type: ignore

# --- Response-Modell (gleiche Struktur wie TransformerResponse) ---

analyzer_response = image_analyzer_ns.model('ImageAnalyzerResponse', {  # type: ignore
    'status': fields.String(description='Status (success/error)'),
    'request': fields.Raw(description='Request-Informationen'),
    'process': fields.Raw(description='Prozess-Informationen inkl. LLM-Info'),
    'data': fields.Nested(image_analyzer_ns.model('ImageAnalyzerData', {  # type: ignore
        'text': fields.String(description='Gefülltes Template mit extrahierten Daten'),
        'language': fields.String(description='Zielsprache'),
        'format': fields.String(description='Ausgabeformat'),
        'structured_data': fields.Raw(description='Strukturierte Daten als JSON')
    })),
    'error': fields.Raw(description='Fehlerinformationen')
})

error_model = image_analyzer_ns.model('ImageAnalyzerError', {  # type: ignore
    'error': fields.String(description='Fehlermeldung')
})


def _get_processor(process_id: Optional[str] = None) -> ImageAnalyzerProcessor:
    """Erstellt eine neue ImageAnalyzerProcessor-Instanz."""
    from src.core.resource_tracking import ResourceCalculator
    return ImageAnalyzerProcessor(ResourceCalculator(), process_id)


def _parse_json_param(value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parst einen optionalen JSON-String-Parameter."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise ProcessingError(f"Ungültiger JSON-String: {value[:100]}")


def _calculate_file_hash(file_path: str) -> str:
    """Berechnet einen MD5-Hash für eine Datei."""
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


@image_analyzer_ns.route('/process')  # type: ignore
class ImageAnalyzerUploadEndpoint(Resource):
    @image_analyzer_ns.expect(upload_parser)  # type: ignore
    @image_analyzer_ns.response(200, 'Erfolg', analyzer_response)  # type: ignore
    @image_analyzer_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @image_analyzer_ns.doc(description=(  # type: ignore
        'Analysiert ein hochgeladenes Bild anhand eines Templates und '
        'extrahiert strukturierte Daten (Klassifizierungen, Merkmale, etc.).'
    ))
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Bild mit Template analysieren"""
        args = upload_parser.parse_args()
        uploaded_file: FileStorage = cast(FileStorage, args.get('file'))
        template = str(args.get('template', '')) if args.get('template') else None
        template_content_arg = str(args.get('template_content', '')) if args.get('template_content') else None
        context = _parse_json_param(str(args.get('context', '')) if args.get('context') else None)
        additional = _parse_json_param(
            str(args.get('additional_field_descriptions', '')) if args.get('additional_field_descriptions') else None
        )
        target_language = str(args.get('target_language', 'de'))
        model_override = str(args.get('model', '')) if args.get('model') else None
        provider_override = str(args.get('provider', '')) if args.get('provider') else None
        use_cache = bool(args.get('useCache', True))
        process_id = str(uuid.uuid4())
        temp_file_path = ""

        try:
            # Validierung
            if not uploaded_file.filename:
                raise ProcessingError("Keine Datei hochgeladen")
            if not template and not template_content_arg:
                raise ProcessingError("Entweder template oder template_content muss angegeben werden")
            if template and template_content_arg:
                raise ProcessingError("Nur template ODER template_content, nicht beides")

            processor = _get_processor(process_id)
            tracker = get_performance_tracker()

            # Datei temporär speichern
            suffix = Path(uploaded_file.filename).suffix
            temp_file_path = os.path.join(
                os.path.dirname(__file__), f"temp_{uuid.uuid4()}{suffix}"
            )
            uploaded_file.save(temp_file_path)
            file_hash = _calculate_file_hash(temp_file_path)

            # Analyse durchführen
            if tracker:
                with tracker.measure_operation('image_analyzer', 'ImageAnalyzerProcessor'):
                    result = processor.analyze_by_template(
                        file_path=temp_file_path,
                        template=template,
                        template_content=template_content_arg,
                        context=context,
                        additional_field_descriptions=additional,
                        target_language=target_language,
                        use_cache=use_cache,
                        file_hash=file_hash,
                        model=model_override,
                        provider=provider_override
                    )
                    tracker.eval_result(result)
            else:
                result = processor.analyze_by_template(
                    file_path=temp_file_path,
                    template=template,
                    template_content=template_content_arg,
                    context=context,
                    additional_field_descriptions=additional,
                    target_language=target_language,
                    use_cache=use_cache,
                    file_hash=file_hash,
                    model=model_override,
                    provider=provider_override
                )

            return result.to_dict()

        except Exception as e:
            logger.error("Fehler bei der Bildanalyse", error=e)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {'error_type': type(e).__name__}
                }
            }, 400
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass


@image_analyzer_ns.route('/process-url')  # type: ignore
class ImageAnalyzerUrlEndpoint(Resource):
    @image_analyzer_ns.expect(url_parser)  # type: ignore
    @image_analyzer_ns.response(200, 'Erfolg', analyzer_response)  # type: ignore
    @image_analyzer_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @image_analyzer_ns.doc(description=(  # type: ignore
        'Analysiert ein Bild von einer URL anhand eines Templates und '
        'extrahiert strukturierte Daten (Klassifizierungen, Merkmale, etc.).'
    ))
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Bild von URL mit Template analysieren"""
        args = url_parser.parse_args()
        url = str(args.get('url', ''))
        template = str(args.get('template', '')) if args.get('template') else None
        template_content_arg = str(args.get('template_content', '')) if args.get('template_content') else None
        context = _parse_json_param(str(args.get('context', '')) if args.get('context') else None)
        additional = _parse_json_param(
            str(args.get('additional_field_descriptions', '')) if args.get('additional_field_descriptions') else None
        )
        target_language = str(args.get('target_language', 'de'))
        model_override = str(args.get('model', '')) if args.get('model') else None
        provider_override = str(args.get('provider', '')) if args.get('provider') else None
        use_cache = bool(args.get('useCache', True))
        process_id = str(uuid.uuid4())

        try:
            if not url:
                raise ProcessingError("Keine URL angegeben")
            if not template and not template_content_arg:
                raise ProcessingError("Entweder template oder template_content muss angegeben werden")
            if template and template_content_arg:
                raise ProcessingError("Nur template ODER template_content, nicht beides")

            processor = _get_processor(process_id)
            url_hash = hashlib.md5(url.encode()).hexdigest()

            result = processor.analyze_by_template(
                file_path=url,
                template=template,
                template_content=template_content_arg,
                context=context,
                additional_field_descriptions=additional,
                target_language=target_language,
                use_cache=use_cache,
                file_hash=url_hash,
                model=model_override,
                provider=provider_override,
                is_url=True
            )

            return result.to_dict()

        except Exception as e:
            logger.error("Fehler bei der Bildanalyse von URL", error=e)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {'error_type': type(e).__name__}
                }
            }, 400
