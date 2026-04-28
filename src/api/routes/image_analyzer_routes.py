"""
@fileoverview Image Analyzer API Routes - Endpoints für template-basierte Bildanalyse

@description
API-Routen für die Analyse und Klassifizierung von Bildern anhand von Templates.
Analog zum Transformer-Template-Endpoint, aber mit Bildern statt Text als Input.

Wichtig (siehe docs/multi_image_analyzer.md):
- /process unterstützt EIN Bild (Param `file`) ODER mehrere Bilder (Param `files`,
  beliebig oft wiederholbar). Beide Wege sind erlaubt; der Server normalisiert
  alle hochgeladenen Bilder zu einer Liste von Bytes.
- ALLE Bilder werden komplett in-memory verarbeitet. Es wird nichts vom eigenen
  Code auf Disk geschrieben. Werkzeug spillt nur sehr große Uploads in einen
  SpooledTemporaryFile, das ist ok.
- Maximal `ImageAnalyzerProcessor.MAX_IMAGES_PER_REQUEST` Bilder pro Request.

Endpoints:
- POST /api/image-analyzer/process: Bild-Upload (1..N) + Template-Analyse
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
import uuid
import json
import hashlib
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import requests
from flask import request  # für Zugriff auf eingehende HTTP-Header
from flask_restx import Namespace, Resource, fields, inputs  # type: ignore
from flask_restx.reqparse import RequestParser  # type: ignore
from werkzeug.datastructures import FileStorage

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.processors.image_analyzer_processor import ImageAnalyzerProcessor

logger = get_logger(__name__)

# --- Korrelations-Header ---
# Optionale Header, die der Client setzen darf, um Aufrufe einem Job
# zuzuordnen. Server-seitig sind sie rein informativ (Logging + Echo
# in der Response). Werden sie nicht gesendet, steht im Log `null`
# – das ist absichtlich backwards-kompatibel.
#
# - X-Job-Id:           ID eines fachlichen Jobs (z.B. CKS-Job)
# - X-Source-Item-Id:   ID des Items, für das der Aufruf passiert
# - X-Worker-Id:        ID des Workers/Prozesses, der den Aufruf startet
# - X-Start-Request-Id: ID des ursprünglichen Start-Requests
#                       (siehe CKS external-jobs-worker.ts)
_CORRELATION_HEADERS: tuple[str, ...] = (
    "X-Job-Id",
    "X-Source-Item-Id",
    "X-Worker-Id",
    "X-Start-Request-Id",
)


def _correlation_from_request() -> Dict[str, Optional[str]]:
    """
    Liest die optionalen Korrelations-Header aus dem aktuellen Request.

    Returns:
        Dict mit Header-Namen -> Wert (oder None, wenn nicht gesendet).
        Header-Lookup ist case-insensitiv (Werkzeug-Default).
    """
    return {h: request.headers.get(h) for h in _CORRELATION_HEADERS}


def _correlation_response_headers(
    correlation: Dict[str, Optional[str]],
    process_id: str
) -> Dict[str, str]:
    """
    Baut die HTTP-Response-Header für die Korrelation.

    - X-Process-Id wird IMMER gesetzt (server-seitige UUID des Aufrufs).
    - Vom Client gesendete Korrelations-Header werden 1:1 zurückgespiegelt,
      damit der Client einen Vision-Response eindeutig dem Job zuordnen kann.
    """
    headers: Dict[str, str] = {"X-Process-Id": process_id}
    for name, value in correlation.items():
        if value:
            headers[name] = value
    return headers

# --- Namespace ---

image_analyzer_ns = Namespace(
    'image-analyzer',
    description='Template-basierte Bildanalyse und Klassifizierung'
)

# --- Parser für Upload ---
# Hinweis zum Multi-Upload:
# `files` mit action='append' erlaubt, dass mehrere Form-Felder mit dem
# gleichen Namen `files` gesendet werden. Im Swagger-UI ist nur ein einzelner
# File-Picker sichtbar — das ist eine bekannte Limitation. Multi-Upload-Tests
# am besten via curl/Postman, siehe docs/multi_image_analyzer.md.
upload_parser: RequestParser = image_analyzer_ns.parser()
upload_parser.add_argument(  # type: ignore
    'file',
    type=FileStorage,
    location='files',
    required=False,
    help='Bilddatei (JPG, PNG, WebP, GIF). Backwards-kompatibel; alternativ `files` benutzen.'
)
upload_parser.add_argument(  # type: ignore
    'files',
    type=FileStorage,
    location='files',
    action='append',
    required=False,
    help='Mehrere Bilddateien (Param mehrfach senden). Wird zusammen mit `file` gemerged.'
)
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


def _read_uploads_to_bytes(
    uploads: List[FileStorage]
) -> Tuple[List[bytes], List[str], List[str]]:
    """
    Liest eine Liste von FileStorage-Objekten in-memory zu Bytes.

    Liefert parallele Listen (Reihenfolge erhalten):
    - bytes-Liste der Dateiinhalte
    - Liste der Dateinamen (für Logging/Tracing)
    - Liste der MD5-Hashes (für Cache-Key + Logging)

    Achtung: stream.read() lädt die komplette Datei in den RAM. Das ist
    bewusst so gewählt, weil wir keinen Server-Storage nutzen wollen.
    """
    bytes_list: List[bytes] = []
    names: List[str] = []
    hashes: List[str] = []
    for f in uploads:
        # Stream zurücksetzen, falls Werkzeug schon hineingelesen hat,
        # dann komplett in den RAM ziehen.
        try:
            f.stream.seek(0)
        except Exception:
            pass
        data = f.stream.read()
        if not data:
            raise ProcessingError(f"Hochgeladene Datei ist leer: {f.filename or '<ohne Namen>'}")
        bytes_list.append(data)
        names.append(f.filename or "")
        hashes.append(hashlib.md5(data).hexdigest())
    return bytes_list, names, hashes


@image_analyzer_ns.route('/process')  # type: ignore
class ImageAnalyzerUploadEndpoint(Resource):
    @image_analyzer_ns.expect(upload_parser)  # type: ignore
    @image_analyzer_ns.response(200, 'Erfolg', analyzer_response)  # type: ignore
    @image_analyzer_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @image_analyzer_ns.doc(description=(  # type: ignore
        'Analysiert ein oder mehrere hochgeladene Bilder anhand eines Templates und '
        'extrahiert strukturierte Daten (Klassifizierungen, Merkmale, etc.). '
        'Mehrere Bilder werden in einem einzigen LLM-Call ausgewertet '
        '(siehe docs/multi_image_analyzer.md).'
    ))
    def post(self) -> Union[
        Dict[str, Any],
        tuple[Dict[str, Any], int],
        # Flask-RESTX akzeptiert auch (body, status, headers) als 3-Tupel –
        # das nutzen wir, um Korrelations-Header zurückzugeben.
        tuple[Dict[str, Any], int, Dict[str, str]],
    ]:
        """Bild(er) mit Template analysieren"""
        args = upload_parser.parse_args()

        # Beide Upload-Pfade einsammeln und zu einer Liste mergen.
        # `file` ist Backward-Compat-Single, `files` ist die Multi-Variante.
        single_file = cast(Optional[FileStorage], args.get('file'))
        multi_files_arg = args.get('files') or []
        if not isinstance(multi_files_arg, list):
            # Defensive: action='append' liefert i.d.R. eine Liste, aber
            # falls nur ein Eintrag vorliegt, kann es ein Einzel-Objekt sein.
            multi_files_arg = [multi_files_arg]
        uploaded_files: List[FileStorage] = []
        if single_file is not None:
            uploaded_files.append(single_file)
        uploaded_files.extend(cast(List[FileStorage], multi_files_arg))

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

        # Korrelations-Header lesen (alle optional, alle dürfen None sein).
        # Werden sowohl ins Log geschrieben als auch in der Response zurück
        # gespiegelt, damit der Client jeden Vision-Aufruf einem Job
        # zuordnen kann.
        correlation = _correlation_from_request()
        response_headers = _correlation_response_headers(correlation, process_id)

        # Eingehende Request-Parameter strukturiert loggen.
        # Hash/Längen statt Volltext, um keine sensiblen Inhalte ins Log zu schreiben.
        logger.info(
            "ImageAnalyzer-Route: /process aufgerufen",
            process_id=process_id,
            correlation=correlation,
            file_count=len(uploaded_files),
            file_names=[f.filename for f in uploaded_files],
            file_mimetypes=[f.mimetype for f in uploaded_files],
            template=template,
            template_content_length=len(template_content_arg) if template_content_arg else 0,
            context=context,
            additional_field_descriptions=additional,
            target_language=target_language,
            model_override=model_override,
            provider_override=provider_override,
            use_cache=use_cache,
        )

        try:
            # Validierung: mindestens eine Datei erforderlich.
            if not uploaded_files:
                raise ProcessingError("Keine Datei hochgeladen (weder 'file' noch 'files')")
            if any((not f.filename) for f in uploaded_files):
                raise ProcessingError("Mindestens eine hochgeladene Datei hat keinen Namen")

            # Limit gegen das Processor-Limit prüfen (frühe, klare Meldung).
            if len(uploaded_files) > ImageAnalyzerProcessor.MAX_IMAGES_PER_REQUEST:
                raise ProcessingError(
                    f"Zu viele Bilder: {len(uploaded_files)} "
                    f"(Maximum: {ImageAnalyzerProcessor.MAX_IMAGES_PER_REQUEST})"
                )

            if not template and not template_content_arg:
                raise ProcessingError("Entweder template oder template_content muss angegeben werden")
            if template and template_content_arg:
                raise ProcessingError("Nur template ODER template_content, nicht beides")

            # Alle Uploads in-memory zu Bytes lesen (kein Disk-IO im eigenen Code).
            image_bytes_list, file_names, file_hashes = _read_uploads_to_bytes(uploaded_files)

            processor = _get_processor(process_id)
            tracker = get_performance_tracker()

            if tracker:
                with tracker.measure_operation('image_analyzer', 'ImageAnalyzerProcessor'):
                    result = processor.analyze_by_template(
                        image_data_list=image_bytes_list,
                        template=template,
                        template_content=template_content_arg,
                        context=context,
                        additional_field_descriptions=additional,
                        target_language=target_language,
                        use_cache=use_cache,
                        file_hashes=file_hashes,
                        file_names=file_names,
                        model=model_override,
                        provider=provider_override,
                        # Korrelations-Header an den Processor durchreichen,
                        # damit sie im funktionierenden Processor-Logger
                        # landen (der Routes-Logger schreibt info-Einträge
                        # aktuell nicht ins File – siehe Doku).
                        correlation=correlation,
                    )
                    tracker.eval_result(result)
            else:
                result = processor.analyze_by_template(
                    image_data_list=image_bytes_list,
                    template=template,
                    template_content=template_content_arg,
                    context=context,
                    additional_field_descriptions=additional,
                    target_language=target_language,
                    use_cache=use_cache,
                    file_hashes=file_hashes,
                    file_names=file_names,
                    model=model_override,
                    provider=provider_override,
                    correlation=correlation,
                )

            # Response als (body, status, headers)-Tuple, damit Flask-RESTX
            # die Korrelations-Header mit zurückschickt.
            return result.to_dict(), 200, response_headers

        except Exception as e:
            logger.error("Fehler bei der Bildanalyse", error=e)
            error_body = {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {'error_type': type(e).__name__}
                }
            }
            # Auch im Fehlerfall die Korrelations-Header zurückgeben –
            # sonst kann der Client den 400er nicht eindeutig zuordnen.
            return error_body, 400, response_headers


@image_analyzer_ns.route('/process-url')  # type: ignore
class ImageAnalyzerUrlEndpoint(Resource):
    @image_analyzer_ns.expect(url_parser)  # type: ignore
    @image_analyzer_ns.response(200, 'Erfolg', analyzer_response)  # type: ignore
    @image_analyzer_ns.response(400, 'Validierungsfehler', error_model)  # type: ignore
    @image_analyzer_ns.doc(description=(  # type: ignore
        'Analysiert ein Bild von einer URL anhand eines Templates und '
        'extrahiert strukturierte Daten. Das Bild wird in-memory geladen, '
        'es wird nichts auf Disk gespeichert.'
    ))
    def post(self) -> Union[
        Dict[str, Any],
        tuple[Dict[str, Any], int],
        tuple[Dict[str, Any], int, Dict[str, str]],
    ]:
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

        # Korrelations-Header lesen (siehe /process für Details).
        correlation = _correlation_from_request()
        response_headers = _correlation_response_headers(correlation, process_id)

        logger.info(
            "ImageAnalyzer-Route: /process-url aufgerufen",
            process_id=process_id,
            correlation=correlation,
            url=url,
            template=template,
            template_content_length=len(template_content_arg) if template_content_arg else 0,
            context=context,
            additional_field_descriptions=additional,
            target_language=target_language,
            model_override=model_override,
            provider_override=provider_override,
            use_cache=use_cache,
        )

        try:
            if not url:
                raise ProcessingError("Keine URL angegeben")
            if not template and not template_content_arg:
                raise ProcessingError("Entweder template oder template_content muss angegeben werden")
            if template and template_content_arg:
                raise ProcessingError("Nur template ODER template_content, nicht beides")

            # Bild in-memory von der URL holen.
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                image_bytes = resp.content
            except Exception as e:
                raise ProcessingError(f"Fehler beim Herunterladen des Bildes: {e}") from e

            if not image_bytes:
                raise ProcessingError("Heruntergeladenes Bild ist leer")

            # Cache-Hash aus tatsächlichem Inhalt — nicht aus URL —, damit
            # zwei URLs auf gleichen Inhalt denselben Cache-Treffer ergeben.
            image_hash = hashlib.md5(image_bytes).hexdigest()

            processor = _get_processor(process_id)
            result = processor.analyze_by_template(
                image_data_list=[image_bytes],
                template=template,
                template_content=template_content_arg,
                context=context,
                additional_field_descriptions=additional,
                target_language=target_language,
                use_cache=use_cache,
                file_hashes=[image_hash],
                image_urls=[url],
                model=model_override,
                provider=provider_override,
                correlation=correlation,
            )

            return result.to_dict(), 200, response_headers

        except Exception as e:
            logger.error("Fehler bei der Bildanalyse von URL", error=e)
            error_body = {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': {'error_type': type(e).__name__}
                }
            }
            return error_body, 400, response_headers
