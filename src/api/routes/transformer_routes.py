"""
@fileoverview Transformer API Routes - Flask-RESTX endpoints for text transformation

@description
Transformer API routes. Contains endpoints for text and template transformations.
This file defines REST API endpoints for text transformation with Flask-RESTX,
including translation, template processing, summarization, and format conversion.

Main endpoints:
- POST /api/transformer/translate: Text translation
- POST /api/transformer/transform: Template-based transformation
- POST /api/transformer/summarize: Text summarization
- POST /api/transformer/html-to-markdown: HTML to Markdown conversion
- POST /api/transformer/extract-tables: Table extraction from HTML
- GET /api/transformer/health: Health check for transformer service

Features:
- JSON-based request/response
- Template-based transformation with custom templates
- Support for various output formats (Markdown, HTML, JSON, etc.)
- Metadata extraction for files
- Caching support
- Swagger UI documentation

@module api.routes.transformer_routes

@exports
- transformer_ns: Namespace - Flask-RESTX namespace for transformer endpoints

@usedIn
- src.api.routes.__init__: Registers transformer_ns namespace

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- External: werkzeug - FileStorage for file uploads
- Internal: src.processors.transformer_processor - TransformerProcessor
- Internal: src.processors.metadata_processor - MetadataProcessor
- Internal: src.core.models.transformer - TransformerResponse
- Internal: src.core.models.enums - OutputFormat
- Internal: src.utils.performance_tracker - Performance tracking
"""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedFunction=false, reportGeneralTypeIssues=false, reportCallIssue=false, reportPossiblyUnboundVariable=false, reportUnusedVariable=false, reportUnnecessaryIsInstance=false
# Hinweis:
# Dieses Modul ist bewusst "API-glue" und verwendet flask-restx RequestParser, dynamische JSON-Payloads
# und third-party Typen ohne vollständige Stub-Pakete. Pyright würde hier sehr viele Unknown-Reports erzeugen.
# Die inhaltliche Validierung erfolgt in den Processors/Dataclasses.
# type: ignore
import time
from typing import Dict, Any, Union, Optional, List
import traceback
import uuid
import json
import asyncio
import hashlib

from flask import request
from werkzeug.datastructures import FileStorage
from flask_restx import Namespace, Resource, fields, inputs  # type: ignore

from src.core.models.transformer import TransformerResponse, TransformerData
from src.processors.transformer_processor import TransformerProcessor
from src.processors.metadata_processor import MetadataProcessor
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from werkzeug.exceptions import RequestEntityTooLarge
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.utils.logger import ProcessingLogger
from src.utils.performance_tracker import PerformanceTracker
from src.core.models.enums import OutputFormat
from src.core.models.base import ErrorInfo
from src.core.llm.config_manager import LLMConfigManager
from src.core.llm.use_cases import UseCase

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="transformer-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
transformer_ns = Namespace('transformer', description='Transformer Operationen')

# Cache für Prozessoren
_processor_cache = {
    'transformer': {},  # Speichert Transformer-Prozessoren
    'metadata': {}      # Speichert Metadata-Prozessoren
}
_max_cache_size = 10  # Maximale Anzahl der gespeicherten Prozessoren pro Typ

# Helper-Funktion zum Abrufen des Transformer-Processors
def get_transformer_processor() -> TransformerProcessor:
    """Get or create transformer processor instance"""
    # Generiere eine neue UUID für den Cache-Schlüssel
    cache_key = str(uuid.uuid4())
    
    # Prüfe, ob ein passender Prozessor im Cache ist
    if cache_key in _processor_cache['transformer']:
        logger.debug(f"Verwende gecachten Transformer-Processor für {cache_key}")
        return _processor_cache['transformer'][cache_key]
    
    # Andernfalls erstelle einen neuen Prozessor
    processor = TransformerProcessor(resource_calculator)
    
    # Cache-Management: Entferne ältesten Eintrag, wenn der Cache voll ist
    if len(_processor_cache['transformer']) >= _max_cache_size:
        # Hole den ältesten Schlüssel (first in)
        oldest_key = next(iter(_processor_cache['transformer']))
        del _processor_cache['transformer'][oldest_key]
    
    # Speichere den neuen Prozessor im Cache
    _processor_cache['transformer'][cache_key] = processor
    return processor

# Helper-Funktion zum Abrufen des Metadata-Processors
def get_metadata_processor(process_id: Optional[str] = None) -> MetadataProcessor:
    """Get or create metadata processor instance with process ID"""
    # Erstelle eine neue process_id, wenn keine angegeben wurde
    if not process_id:
        process_id = str(uuid.uuid4())
    
    # Prüfe, ob ein passender Prozessor im Cache ist
    if process_id in _processor_cache['metadata']:
        logger.debug(f"Verwende gecachten Metadata-Processor für {process_id}")
        return _processor_cache['metadata'][process_id]
    
    # Andernfalls erstelle einen neuen Prozessor
    processor = MetadataProcessor(resource_calculator, process_id=process_id)
    
    # Cache-Management: Entferne ältesten Eintrag, wenn der Cache voll ist
    if len(_processor_cache['metadata']) >= _max_cache_size:
        # Hole den ältesten Schlüssel (first in)
        oldest_key = next(iter(_processor_cache['metadata']))
        del _processor_cache['metadata'][oldest_key]
    
    # Speichere den neuen Prozessor im Cache
    _processor_cache['metadata'][process_id] = processor
    return processor

# Hilfsfunktion zum Kürzen von Text
def _truncate_text(text: str, max_length: int = 100) -> str:
    """Kürzt Text auf die angegebene Länge und fügt '...' hinzu, wenn gekürzt wurde."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

# Hilfsfunktionen für LLM-Tracking
def _track_llm_usage(model: str, tokens: int, duration: float, purpose: str = "api") -> None:
    """Standardisiertes LLM-Tracking für die API."""
    try:
        if not model:
            raise ValueError("model darf nicht leer sein")
        if tokens <= 0:
            raise ValueError("tokens muss positiv sein")
        if duration < 0:
            raise ValueError("duration muss nicht-negativ sein")
                
        resource_calculator.track_usage(
            tokens=tokens,
            model=model,
            duration=duration
        )
        
        logger.info(
            "LLM-Nutzung getrackt",
            model=model,
            tokens=tokens,
            duration=duration,
            purpose=purpose
        )
    except Exception as e:
        logger.warning(
            "LLM-Tracking fehlgeschlagen",
            error=str(e),  # Konvertiere Exception zu String für JSON-Serialisierung
            model=model,
            tokens=tokens,
            duration=duration
        )

def _determine_container_selector_from_url(url: str) -> Optional[str]:
    """
    Bestimmt automatisch den Container-Selector basierend auf der URL.
    
    Args:
        url: Die URL der Webseite
        
    Returns:
        CSS-Selector für Event-Container oder None, falls nicht bekannt
    """
    from urllib.parse import urlparse
    
    try:
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        # Bekannte Domains und ihre Container-Selectors
        domain_selectors = {
            'sfscon.it': 'li.single-element.sfscon',
            'www.sfscon.it': 'li.single-element.sfscon',
        }
        
        # Direkte Domain-Übereinstimmung
        if domain in domain_selectors:
            return domain_selectors[domain]
        
        # Teilstring-Match (z.B. für Subdomains)
        for known_domain, selector in domain_selectors.items():
            if known_domain in domain:
                return selector
        
        return None
    except Exception:
        return None

def _calculate_llm_cost(model: str, tokens: int) -> float:
    """Berechnet die Kosten für LLM-Nutzung."""
    try:
        return resource_calculator.calculate_cost(tokens=tokens, model=model)
    except Exception as e:
        logger.warning(
            "LLM-Kostenberechnung fehlgeschlagen",
            error=e,
            model=model,
            tokens=tokens
        )
        return 0.0

# Parser für den Text-Transformations-Endpunkt
text_transform_parser = transformer_ns.parser()
text_transform_parser.add_argument('text', type=str, location='form', required=True, help='Der zu transformierende Text')
text_transform_parser.add_argument('source_language', type=str, location='form', required=True, help='Die Quellsprache (ISO 639-1 Code)')
text_transform_parser.add_argument('target_language', type=str, location='form', required=True, help='Die Zielsprache (ISO 639-1 Code)')
text_transform_parser.add_argument('summarize', type=inputs.boolean, location='form', required=False, default=False, help='Ob der Text zusammengefasst werden soll (true/false)')
text_transform_parser.add_argument('target_format', type=str, location='form', required=False, help='Das Zielformat (TEXT, HTML, MARKDOWN, JSON)')
text_transform_parser.add_argument('context', type=str, location='form', required=False, help='Optionaler JSON-String Kontext für die Transformation')
text_transform_parser.add_argument('use_cache', type=inputs.boolean, location='form', required=False, default=True, help='Ob der Cache verwendet werden soll (true/false)')
text_transform_parser.add_argument('model', type=str, location='form', required=False, help='Zu verwendendes Modell (optional, verwendet Standard aus Config wenn nicht angegeben)')
text_transform_parser.add_argument('provider', type=str, location='form', required=False, help='Provider-Name (optional, verwendet Standard aus Config wenn nicht angegeben)')

# Parser für den Template-Transformations-Endpunkt
template_transform_parser = transformer_ns.parser()
template_transform_parser.add_argument('text', type=str, location='form', required=False, help='Der zu transformierende Text (optional wenn URL angegeben)')
template_transform_parser.add_argument('url', type=str, location='form', required=False, help='URL der Webseite (optional wenn Text angegeben)')
template_transform_parser.add_argument('source_language', type=str, location='form', default='de', help='Quellsprache (ISO 639-1 code, z.B. "en", "de")')
template_transform_parser.add_argument('target_language', type=str, location='form', default='de', help='Zielsprache (ISO 639-1 code, z.B. "en", "de")')
template_transform_parser.add_argument('template', type=str, location='form', required=False, help='Name des Templates (ohne .md Endung) - optional wenn template_content angegeben')
template_transform_parser.add_argument('template_content', type=str, location='form', required=False, help='Direkter Template-Inhalt (Markdown) - optional wenn template angegeben')
template_transform_parser.add_argument('context', type=str, location='form', required=False, help='Optionaler JSON-String Kontext für die Template-Verarbeitung')
template_transform_parser.add_argument('additional_field_descriptions', type=str, location='form', required=False, help='Optionaler JSON-String mit zusätzlichen Feldbeschreibungen')
template_transform_parser.add_argument('use_cache', type=inputs.boolean, location='form', required=False, default=True, help='Ob der Cache verwendet werden soll (true/false)')
template_transform_parser.add_argument('container_selector', type=str, location='form', required=False, help='CSS-Selector für Event-Container (z.B. "li.single-element"). Wird automatisch basierend auf URL bestimmt, falls nicht angegeben.')
template_transform_parser.add_argument('callback_url', type=str, location='form', required=False, help='Absolute HTTPS-URL für den Webhook-Callback')
template_transform_parser.add_argument('callback_token', type=str, location='form', required=False, help='Per-Job-Secret für den Webhook-Callback')
template_transform_parser.add_argument('jobId', type=str, location='form', required=False, help='Eindeutige Job-ID für den Callback')
template_transform_parser.add_argument('wait_ms', type=int, location='form', required=False, default=0, help='Optional: Wartezeit in Millisekunden auf Abschluss (nur ohne callback_url)')
template_transform_parser.add_argument('model', type=str, location='form', required=False, help='Zu verwendendes Modell (optional, verwendet Standard aus Config wenn nicht angegeben)')
template_transform_parser.add_argument('provider', type=str, location='form', required=False, help='Provider-Name (optional, verwendet Standard aus Config wenn nicht angegeben)')

# Parser für den HTML-Tabellen-Transformations-Endpunkt
html_table_transform_parser = transformer_ns.parser()
html_table_transform_parser.add_argument('source_url', type=str, location='form', required=True, help='Die URL der Webseite mit der HTML-Tabelle')
html_table_transform_parser.add_argument('output_format', type=str, location='form', default='json', help='Ausgabeformat (aktuell nur JSON unterstützt)')
html_table_transform_parser.add_argument('table_index', type=int, location='form', required=False, help='Optional - Index der gewünschten Tabelle (0-basiert).')
html_table_transform_parser.add_argument('start_row', type=int, location='form', required=False, help='Optional - Startzeile für das Paging (0-basiert)')
html_table_transform_parser.add_argument('row_count', type=int, location='form', required=False, help='Optional - Anzahl der zurückzugebenden Zeilen')

# Parser für den Chat-Completion-Endpunkt
chat_parser = transformer_ns.parser()
chat_parser.add_argument('messages', type=str, location='form', required=True, help='JSON-String mit Liste von Nachrichten (Chat-Historie). Format: [{"role": "system|user|assistant", "content": "..."}]. Unterstützt vollständige Chat-Historie mit mehreren Nachrichten.')
chat_parser.add_argument('model', type=str, location='form', required=False, help='Zu verwendendes Modell (optional, verwendet Standard aus Config wenn nicht angegeben)')
chat_parser.add_argument('provider', type=str, location='form', required=False, help='Provider-Name (optional, verwendet Standard aus Config wenn nicht angegeben)')
chat_parser.add_argument('temperature', type=float, location='form', required=False, default=0.7, help='Temperature für die Antwort (0.0-2.0, default: 0.7)')
chat_parser.add_argument('max_tokens', type=int, location='form', required=False, help='Maximale Anzahl Tokens (optional)')
chat_parser.add_argument('stream', type=inputs.boolean, location='form', required=False, default=False, help='Ob Streaming aktiviert werden soll (default: false)')
chat_parser.add_argument('response_format', type=str, location='form', required=False, default='text', help='Response-Format: "text" oder "json_object" (default: "text")')
chat_parser.add_argument('schema_json', type=str, location='form', required=False, help='JSON Schema als String (optional, empfohlen wenn response_format=json_object)')
chat_parser.add_argument('schema_id', type=str, location='form', required=False, help='Server-bekannte Schema-ID (optional, Alternative zu schema_json)')
chat_parser.add_argument('strict', type=inputs.boolean, location='form', required=False, help='Ob Schema-Validierung strikt sein soll (default: true wenn response_format=json_object)')
chat_parser.add_argument('use_cache', type=inputs.boolean, location='form', required=False, default=True, help='Ob der Cache verwendet werden soll (default: true)')
chat_parser.add_argument('timeout_ms', type=int, location='form', required=False, help='Request-Timeout in Millisekunden (optional, Server kann clammen)')

# Text-Transformation Endpoint
@transformer_ns.route('/text')  # type: ignore
class TransformTextEndpoint(Resource):
    # Swagger-Dokumentation für den Endpunkt
    @transformer_ns.doc(description='Transformiert Text von einer Sprache in eine andere')  # type: ignore
    @transformer_ns.expect(text_transform_parser)  # type: ignore
    @transformer_ns.response(200, 'Erfolgreiche Transformation')  # type: ignore
    @transformer_ns.response(400, 'Ungültige Anfrage')  # type: ignore
    @transformer_ns.response(500, 'Server-Fehler')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Transformiert Text von einer Sprache in eine andere, mit optionaler Zusammenfassung."""
        # Default-Werte, damit Error-Handling keine "unbound" Variablen erzeugt.
        processor: TransformerProcessor | None = None
        source_text: str = ""
        source_language: str = "de"
        target_language: str = "de"
        summarize: bool = False
        target_format_str: str = "TEXT"
        context: Dict[str, Any] = {}
        use_cache: bool = True
        try:
            # Request-Daten extrahieren mit dem Parser
            args = text_transform_parser.parse_args()
            
            # Parameter extrahieren
            source_text = str(args.get('text', '') or '')
            source_language = str(args.get('source_language', 'de') or 'de')
            target_language = str(args.get('target_language', 'de') or 'de')
            summarize = bool(args.get('summarize', False))
            target_format_str = str(args.get('target_format', 'TEXT') or 'TEXT')
            context_str = args.get('context')
            use_cache = bool(args.get('use_cache', True))
            model: Optional[str] = args.get('model')
            provider: Optional[str] = args.get('provider')

            # Kontext parsen, falls vorhanden
            context = {}
            if context_str:
                try:
                    context = json.loads(context_str)
                except json.JSONDecodeError:
                    return {
                        "status": "error",
                        "error": {
                            "code": "InvalidRequest",
                            "message": "Ungültiger JSON-String im context-Feld."
                        }
                    }, 400
            
            # Validierung
            if not source_text:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": "Text darf nicht leer sein."
                    }
                }, 400
            
            if not source_language:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": "Quellsprache darf nicht leer sein."
                    }
                }, 400
                
            if not target_language:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": "Zielsprache darf nicht leer sein."
                    }
                }, 400
            
            # Target-Format konvertieren
            try:
                target_format = OutputFormat[target_format_str] if target_format_str else None
            except KeyError:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": f"Ungültiges Zielformat: {target_format_str}. Erlaubte Werte: {', '.join([f.name for f in OutputFormat])}"
                    }
                }, 400
            
            start_time: float = time.time()

            # Processor initialisieren und Text transformieren
            processor = get_transformer_processor()
            result: TransformerResponse = processor.transform(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize,
                target_format=target_format,
                context=context,
                use_cache=use_cache,
                model=model,
                provider=provider
            )
            
            # Antwort erstellen
            end_time: float = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            response: TransformerResponse = processor.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format_str,
                    'context': context,
                    'model': model,
                    'provider': provider,
                    'duration_ms': duration_ms
                },
                response_class=TransformerResponse,
                from_cache=processor.process_info.is_from_cache,    
                cache_key=processor.process_info.cache_key or ""
            )

            return response.to_dict()
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            # Spezifische Fehlerbehandlung
            logger.error(f"Bekannter Fehler bei der Text-Transformation: {str(e)}")

            proc = processor or get_transformer_processor()
            error_response = proc.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format_str,
                    'context': context
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code=e.__class__.__name__,
                    message=str(e),
                    details={"traceback": traceback.format_exc()}
                )
            )
            return error_response.to_dict(), 400
            
        except Exception as e:
            # Allgemeine Fehlerbehandlung
            logger.error(f"Fehler bei der Text-Transformation: {str(e)}")
            logger.error(traceback.format_exc())

            proc = processor or get_transformer_processor()
            error_response = proc.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format_str,
                    'context': context
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="ProcessingError",
                    message=f"Fehler bei der Text-Transformation: {str(e)}",
                    details={"traceback": traceback.format_exc()}
                )
            )
            return error_response.to_dict(), 400

# Template Transformation Endpunkt
@transformer_ns.route('/template')  # type: ignore
class TemplateTransformEndpoint(Resource):
    @transformer_ns.expect(template_transform_parser) # type: ignore
    @transformer_ns.response(200, 'Erfolg', transformer_ns.model('TransformerTemplateResponse', {  # type: ignore
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(transformer_ns.model('TemplateRequestInfo', {  # type: ignore
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(transformer_ns.model('TemplateProcessInfo', {  # type: ignore
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'sub_processors': fields.List(fields.String, description='Unterprozessoren'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
            'llm_info': fields.Raw(description='LLM-Nutzungsinformationen')
        })),
        'data': fields.Raw(description='Transformationsergebnis'),
        'error': fields.Nested(transformer_ns.model('TemplateErrorInfo', {  # type: ignore
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Text mit Template transformieren"""
        try:
            # Unterstütze große Payloads über JSON, um multipart/form-data Limits zu umgehen
            if request.is_json:
                payload: Dict[str, Any] = request.get_json(silent=True) or {}
                logger.info(
                    "TemplateTransformEndpoint: JSON-Request erkannt, verwende JSON-Parsing statt multipart/form-data",
                    keys=list(payload.keys()),
                )
                args: Dict[str, Any] = {
                    "text": payload.get("text", ""),
                    "url": payload.get("url", ""),
                    "source_language": payload.get("source_language", "de"),
                    "target_language": payload.get("target_language", "de"),
                    "template": payload.get("template", ""),
                    "template_content": payload.get("template_content", ""),
                    # Für JSON erlauben wir sowohl String- als auch Dict-Form für context / additional_field_descriptions
                    "context": payload.get("context"),
                    "additional_field_descriptions": payload.get("additional_field_descriptions"),
                    "use_cache": payload.get("use_cache", True),
                    "container_selector": payload.get("container_selector"),
                    "callback_url": payload.get("callback_url"),
                    "callback_token": payload.get("callback_token"),
                    "jobId": payload.get("jobId"),
                    "model": payload.get("model"),
                    "provider": payload.get("provider"),
                    "wait_ms": payload.get("wait_ms", 0),
                }
            else:
                # Standardpfad: multipart/form-data über Flask-RESTX parser
                args = template_transform_parser.parse_args()
        except RequestEntityTooLarge as parse_error:
            # Fange RequestEntityTooLarge ab, bevor Flask-RESTX es weiterwirft
            max_content_length = None
            max_content_length_from_app = None
            max_content_length_from_current_app = None
            try:
                from flask import current_app
                max_content_length_from_current_app = current_app.config.get('MAX_CONTENT_LENGTH', None)
                max_content_length = max_content_length_from_current_app
            except Exception as e:
                logger.warning(f"Konnte MAX_CONTENT_LENGTH nicht aus current_app lesen: {e}")
            
            # Versuche auch direkt aus der App-Instanz zu lesen
            try:
                from src.dashboard.app import app as dashboard_app
                max_content_length_from_app = dashboard_app.config.get('MAX_CONTENT_LENGTH', None)
                if max_content_length is None:
                    max_content_length = max_content_length_from_app
            except Exception as e:
                logger.warning(f"Konnte MAX_CONTENT_LENGTH nicht aus dashboard_app lesen: {e}")
            
            max_content_length_str = f"{max_content_length} Bytes ({max_content_length / (1024 * 1024):.1f} MB)" if max_content_length else "unbekannt"
            
            # Sammle alle verfügbaren Request-Informationen für Debugging
            content_length = request.content_length if hasattr(request, 'content_length') else None
            content_type = request.content_type if hasattr(request, 'content_type') else None
            request_method = request.method if hasattr(request, 'method') else None
            
            # Prüfe, ob das Limit wirklich überschritten wurde (für Debugging)
            is_really_too_large = False
            if max_content_length and content_length:
                is_really_too_large = content_length > max_content_length
            
            # Versuche zusätzliche Informationen aus der Exception zu extrahieren
            error_description = str(parse_error)
            error_args = getattr(parse_error, 'description', None)
            
            # Prüfe, ob es ein Werkzeug-spezifisches Limit gibt
            # Werkzeug hat ein Standardlimit von 16 MB (16777216 Bytes)
            werkzeug_limit: int = 16 * 1024 * 1024
            
            # Logge die Fehlermeldung für Debugging mit allen Details
            error_message = f'Request zu groß (HTTP 413). Content-Length: {content_length} Bytes, Max-Content-Length: {max_content_length_str}'
            
            # WICHTIG: Prüfe, ob das Problem bei multipart/form-data liegt
            # Flask/Werkzeug kann bei multipart/form-data das Limit anders prüfen
            is_multipart = content_type and 'multipart/form-data' in content_type.lower() if content_type else False
            
            logger.error(
                'RequestEntityTooLarge bei Template-Transformation - UNLOGISCHES VERHALTEN ERKANNT!',
                error=parse_error,
                error_str=str(parse_error),
                error_description=error_description,
                error_args=error_args,
                content_length=content_length,
                content_length_kb=round(float(content_length) / 1024, 2) if content_length else None,
                content_length_mb=round(float(content_length) / (1024 * 1024), 2) if content_length else None,
                max_content_length=max_content_length,
                max_content_length_from_current_app=max_content_length_from_current_app,
                max_content_length_from_app=max_content_length_from_app,
                max_content_length_formatted=max_content_length_str,
                max_content_length_mb=round(float(max_content_length) / (1024 * 1024), 2) if max_content_length else None,
                is_really_too_large=is_really_too_large,
                werkzeug_default_limit=werkzeug_limit,
                werkzeug_limit_mb=round(float(werkzeug_limit) / (1024 * 1024), 2) if werkzeug_limit else None,
                content_type=content_type,
                is_multipart=is_multipart,
                request_method=request_method,
                error_message=error_message,
                warning='⚠️ Request ist NICHT wirklich zu groß, aber Flask wirft trotzdem RequestEntityTooLarge!'
            )
            
            return {
                'status': 'error',
                'error': {
                    'code': 'RequestEntityTooLarge',
                    'message': error_message,
                    'details': {
                        'content_length': content_length,
                        'max_content_length': max_content_length,
                        'max_content_length_formatted': max_content_length_str,
                        'http_status': 413
                    }
                }
            }, 413
        
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            # Parameter extrahieren
            text = args.get('text', '')
            url = args.get('url', '')
            source_language = args.get('source_language', 'de')
            target_language = args.get('target_language', 'de')
            template = args.get('template', '')
            template_content = args.get('template_content', '')
            context_str = args.get('context')
            additional_field_descriptions_str = args.get('additional_field_descriptions')
            use_cache = args.get('use_cache', True)
            container_selector = args.get('container_selector')
            
            # Modell- und Provider-Überschreibung (optional)
            model: Optional[str] = args.get('model')
            provider_override: Optional[str] = args.get('provider')

            # Validierung: Entweder Text oder URL muss angegeben werden
            if not text and not url:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidRequest',
                        'message': 'Entweder text oder url muss angegeben werden.'
                    }
                }, 400

            if text and url:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidRequest',
                        'message': 'Nur entweder text oder url darf angegeben werden, nicht beide.'
                    }
                }, 400

            # Validierung: Entweder Template-Name oder Template-Inhalt muss angegeben werden
            if not template and not template_content:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidRequest',
                        'message': 'Entweder template oder template_content muss angegeben werden.'
                    }
                }, 400

            if template and template_content:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidRequest',
                        'message': 'Nur entweder template oder template_content darf angegeben werden, nicht beide.'
                    }
                }, 400

            # Kontext parsen, falls vorhanden
            context: Dict[str, Any] = {}
            if context_str:
                # Bei multipart/form-data erwarten wir einen JSON-String,
                # bei JSON-Requests kann direkt ein Dict kommen.
                if isinstance(context_str, str):
                    try:
                        context = json.loads(context_str)
                    except json.JSONDecodeError:
                        return {
                            'status': 'error',
                            'error': {
                                'code': 'InvalidRequest',
                                'message': 'Ungültiger JSON-String im context-Feld.'
                            }
                        }, 400
                elif isinstance(context_str, dict):
                    context = context_str

            # Additional field descriptions parsen, falls vorhanden
            additional_field_descriptions: Dict[str, Any] = {}
            if additional_field_descriptions_str:
                if isinstance(additional_field_descriptions_str, str):
                    try:
                        additional_field_descriptions = json.loads(additional_field_descriptions_str)
                    except json.JSONDecodeError:
                        return {
                            'status': 'error',
                            'error': {
                                'code': 'InvalidRequest',
                                'message': 'Ungültiger JSON-String im additional_field_descriptions-Feld.'
                            }
                        }, 400
                elif isinstance(additional_field_descriptions_str, dict):
                    additional_field_descriptions = additional_field_descriptions_str

            start_time: float = time.time()
            transformer_processor: TransformerProcessor = get_transformer_processor()
            
            # Optionaler Async-Modus: Wenn callback_url gesetzt ist → Job enqueuen wie bei PDF
            callback_url = args.get('callback_url')
            callback_token = args.get('callback_token')
            job_id_form = args.get('jobId')
            wait_ms: int = int(args.get('wait_ms') or 0)

            if callback_url:
                # Secretary-Job anlegen
                from src.core.mongodb.secretary_repository import SecretaryJobRepository
                job_repo = SecretaryJobRepository()
                job_webhook: Optional[Dict[str, Any]] = {
                    "url": callback_url,
                    "token": callback_token,
                    "jobId": job_id_form or None,
                }
                params_flat: Dict[str, Any] = {
                    "text": text if text else None,
                    "url": url if url else None,
                    "source_language": source_language,
                    "target_language": target_language,
                    "template": template,
                    "template_content": template_content,
                    "context": context,
                    "additional_field_descriptions": additional_field_descriptions,
                    "use_cache": use_cache,
                    "container_selector": container_selector,
                    "webhook": job_webhook,
                }
                job_data: Dict[str, Any] = {
                    "job_type": "transformer_template",
                    "parameters": params_flat,
                }
                created_job_id: str = job_repo.create_job(job_data)

                # Sofortiges ACK analog PDF
                ack: Dict[str, Any] = {
                    'status': 'accepted',
                    'worker': 'secretary',
                    'process': {
                        'id': created_job_id,
                        'main_processor': 'transformer_template',
                        'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'is_from_cache': False
                    },
                    'job': {'id': job_id_form or created_job_id},
                    'webhook': {'delivered_to': callback_url},
                    'error': None
                }
                logger.info("Webhook-ACK gesendet (Job enqueued)", process_id=created_job_id, callback_url=callback_url)
                return ack, 202

            # Wähle die passende Transformationsmethode (synchroner Pfad)
            if url:
                # Container-Selector automatisch bestimmen, falls nicht angegeben
                if not container_selector:
                    container_selector = _determine_container_selector_from_url(url)
                    if container_selector:
                        logger.info(f"Container-Selector automatisch bestimmt: {container_selector} für URL: {url}")
                
                # URL-basierte Transformation
                transform_result: TransformerResponse = transformer_processor.transformByUrl(
                    url=url,
                    source_language=source_language,
                    target_language=target_language,
                    template=template,
                    template_content=template_content,
                    context=context,
                    additional_field_descriptions=additional_field_descriptions,
                    use_cache=use_cache,
                    container_selector=container_selector,
                    model=model,
                    provider=provider_override
                )
            else:
                # Text-basierte Transformation
                # Übergebe Modell/Provider-Überschreibung falls vorhanden
                transform_result = transformer_processor.transformByTemplate(
                    text=text,
                    source_language=source_language,
                    target_language=target_language,
                    template=template,
                    template_content=template_content,
                    context=context,
                    additional_field_descriptions=additional_field_descriptions,
                    use_cache=use_cache,
                    model=model,
                    provider=provider_override
                )

            # Antwort erstellen
            end_time: float = time.time()
            duration_ms = int((end_time - start_time) * 1000)

            response: TransformerResponse = transformer_processor.create_response(
                processor_name="transformer",
                result=transform_result,
                request_info={
                    'text': _truncate_text(text) if text else None,
                    'url': url if url else None,
                    'template': template,
                    'template_content': _truncate_text(template_content) if template_content else None,
                    'source_language': source_language,
                    'target_language': target_language,
                    'context': context,
                    'additional_field_descriptions': additional_field_descriptions,
                    'use_cache': use_cache,
                    'duration_ms': duration_ms
                },
                response_class=TransformerResponse,
                from_cache=transformer_processor.process_info.is_from_cache,    
                cache_key=transformer_processor.process_info.cache_key or ""
            )

            return response.to_dict()
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            error_response = transformer_processor.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'source_text': _truncate_text(text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'context': context
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code=error.__class__.__name__,
                    message=str(error),
                    details={}
                )
            )
            return error_response.to_dict(), 400
        except Exception as error:
            logger.error(
                'Fehler bei der Template-Transformation',
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                'status': 'error',
                'error': {
                    'code': 'ProcessingError', 
                    'message': f'Fehler bei der Template-Transformation: {error}',
                    'details': {}
                }
            }, 400

# Chat-Completion-Endpunkt
@transformer_ns.route('/chat')
class ChatEndpoint(Resource):
    """
    Chat-Completion-Endpoint, der die Chat-Features von LLM-Providern direkt durchreicht.
    Unterstützt alle Standard-Chat-Completion-Parameter wie OpenRouter.
    """
    @transformer_ns.doc(description='Chat-Completion-Endpoint für direkte LLM-Chat-Interaktionen. Unterstützt Chat-Historie durch Übergabe mehrerer Nachrichten in der messages-Liste. Beispiel: [{"role": "system", "content": "Du bist ein hilfreicher Assistent."}, {"role": "user", "content": "Hallo!"}, {"role": "assistant", "content": "Hallo! Wie kann ich dir helfen?"}, {"role": "user", "content": "Was ist 2+2?"}]')  # type: ignore
    @transformer_ns.expect(chat_parser)  # type: ignore
    @transformer_ns.response(200, 'Erfolgreiche Chat-Completion')  # type: ignore
    @transformer_ns.response(400, 'Ungültige Anfrage')  # type: ignore
    @transformer_ns.response(500, 'Server-Fehler')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Verarbeitet Chat-Completion-Anfragen mit vollständiger Chat-Historie-Unterstützung.
        
        Erwartet:
        - messages: JSON-String mit Liste von Nachrichten (Chat-Historie)
          Format: [{"role": "system|user|assistant", "content": "..."}, ...]
          Unterstützt vollständige Konversationshistorie:
          - "system": System-Prompt (optional, sollte am Anfang stehen)
          - "user": Benutzer-Nachrichten
          - "assistant": Vorherige Assistenten-Antworten (für Kontext)
          
          Beispiel für Chat-Historie:
          [
            {"role": "system", "content": "Du bist ein hilfreicher Assistent."},
            {"role": "user", "content": "Hallo!"},
            {"role": "assistant", "content": "Hallo! Wie kann ich dir helfen?"},
            {"role": "user", "content": "Was ist 2+2?"}
          ]
        
        - model: Optional, Modellname (verwendet Standard aus Config wenn nicht angegeben)
        - provider: Optional, Provider-Name (verwendet Standard aus Config wenn nicht angegeben)
        - temperature: Optional, Temperature (default: 0.7)
        - max_tokens: Optional, Maximale Anzahl Tokens
        - stream: Optional, Ob Streaming aktiviert werden soll (default: false)
        
        Returns:
            TransformerResponse mit der Chat-Antwort im üblichen Format
        """
        start_time: float = time.time()
        
        try:
            # Parse Request-Parameter
            args = chat_parser.parse_args()
            messages_json: str = args.get('messages', '')
            model: Optional[str] = args.get('model')
            provider: Optional[str] = args.get('provider')
            temperature: float = args.get('temperature', 0.7)
            max_tokens: Optional[int] = args.get('max_tokens')
            stream: bool = args.get('stream', False)
            response_format: str = args.get('response_format', 'text')
            schema_json: Optional[str] = args.get('schema_json')
            schema_id: Optional[str] = args.get('schema_id')
            strict: Optional[bool] = args.get('strict')
            use_cache: bool = args.get('use_cache', True)
            timeout_ms: Optional[int] = args.get('timeout_ms')
            
            # Validiere response_format
            if response_format not in ['text', 'json_object']:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidRequest',
                        'message': f'Ungültiger response_format: {response_format}. Erlaubt: "text", "json_object"',
                        'details': {}
                    }
                }, 400
            
            # Setze strict default basierend auf response_format
            if strict is None:
                strict = (response_format == 'json_object')
            
            # Lade Schema wenn response_format=json_object
            schema: Optional[Dict[str, Any]] = None
            if response_format == 'json_object':
                if schema_json:
                    try:
                        schema = json.loads(schema_json)
                    except json.JSONDecodeError as e:
                        return {
                            'status': 'error',
                            'error': {
                                'code': 'InvalidSchema',
                                'message': f'Ungültiger JSON-String für schema_json: {str(e)}',
                                'details': {}
                            }
                        }, 400
                elif schema_id:
                    from src.core.llm.schema_registry import get_schema
                    schema = get_schema(schema_id)
                    if not schema:
                        return {
                            'status': 'error',
                            'error': {
                                'code': 'SchemaNotFound',
                                'message': f'Schema mit ID "{schema_id}" nicht gefunden',
                                'details': {}
                            }
                        }, 400
                # Wenn kein Schema angegeben, aber json_object gewünscht, warnen aber nicht fehlschlagen
                if not schema:
                    logger.warning(
                        'response_format=json_object ohne Schema angegeben',
                        schema_json=schema_json,
                        schema_id=schema_id
                    )
            
            # Parse Messages
            try:
                messages: List[Dict[str, str]] = json.loads(messages_json)
                if not isinstance(messages, list):
                    raise ValueError("messages muss eine Liste sein")
                if not messages:
                    raise ValueError("messages darf nicht leer sein")
                # Validiere Message-Format
                valid_roles = {'system', 'user', 'assistant'}
                for i, msg in enumerate(messages):
                    if not isinstance(msg, dict):
                        raise ValueError(f"Nachricht {i+1} muss ein Dictionary sein")
                    if 'role' not in msg or 'content' not in msg:
                        raise ValueError(f"Nachricht {i+1} muss 'role' und 'content' haben")
                    if msg['role'] not in valid_roles:
                        raise ValueError(f"Nachricht {i+1}: Ungültige Rolle '{msg['role']}'. Erlaubt: {', '.join(valid_roles)}")
            except json.JSONDecodeError as e:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidJSON',
                        'message': f'Ungültiger JSON-String für messages: {str(e)}',
                        'details': {}
                    }
                }, 400
            except ValueError as e:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'InvalidMessages',
                        'message': str(e),
                        'details': {}
                    }
                }, 400
            
            # Streaming wird aktuell nicht unterstützt
            if stream:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'NotSupported',
                        'message': 'Streaming wird aktuell nicht unterstützt',
                        'details': {}
                    }
                }, 400
            
            # Hole Transformer-Processor für Response-Erstellung
            transformer_processor = get_transformer_processor()
            
            # Initialisiere LLM Config Manager
            llm_config_manager = LLMConfigManager()
            
            # Bestimme Provider und Modell
            use_case = "chat_completion"
            provider_name: Optional[str] = None
            default_model_name: Optional[str] = None
            
            # Wenn Provider angegeben, verwende diesen, sonst Standard aus Config
            if provider:
                provider_name = provider
            else:
                # Hole Standard-Modell für chat_completion
                default_model_name = llm_config_manager.get_model_for_use_case(use_case)
                if not default_model_name:
                    return {
                        'status': 'error',
                        'error': {
                            'code': 'NoDefaultModel',
                            'message': 'Kein Standard-Modell für chat_completion konfiguriert',
                            'details': {}
                        }
                    }, 400
                # Extrahiere Provider aus Modell-ID (Format: provider/model_name)
                if '/' in default_model_name:
                    provider_name, _ = default_model_name.split('/', 1)
                else:
                    # Fallback: Versuche Provider aus Config zu holen
                    use_case_config = llm_config_manager.get_use_case_config(use_case)
                    if use_case_config:
                        provider_name = use_case_config.provider
                    else:
                        return {
                            'status': 'error',
                            'error': {
                                'code': 'NoProvider',
                                'message': 'Kein Provider für chat_completion konfiguriert',
                                'details': {}
                            }
                        }, 400
                if not model:
                    model = default_model_name
            
            # Hole Provider-Instanz
            try:
                provider_instance = llm_config_manager.get_provider_for_use_case(use_case)
                if not provider_instance:
                    # Fallback: Versuche Provider direkt zu holen, wenn explizit angegeben
                    if provider:
                        provider_config = llm_config_manager.get_provider_config(provider)
                        if provider_config:
                            from src.core.llm.provider_manager import ProviderManager
                            pm = ProviderManager()
                            provider_instance = pm.get_provider(
                                provider_name=provider,
                                api_key=provider_config.api_key,
                                base_url=provider_config.base_url,
                                **provider_config.additional_config
                            )
                    
                    if not provider_instance:
                        return {
                            'status': 'error',
                            'error': {
                                'code': 'ProviderNotFound',
                                'message': f'Provider nicht gefunden: {provider_name}',
                                'details': {}
                            }
                        }, 400
            except Exception as e:
                return {
                    'status': 'error',
                    'error': {
                        'code': 'ProviderError',
                        'message': f'Fehler beim Laden des Providers: {str(e)}',
                        'details': {}
                    }
                }, 400
            
            # Rufe chat_completion auf
            try:
                # Bereite Parameter vor
                chat_kwargs: Dict[str, Any] = {
                    'temperature': temperature
                }
                if max_tokens:
                    chat_kwargs['max_tokens'] = max_tokens
                
                # Setze response_format für Provider (OpenAI-kompatibel)
                if response_format == 'json_object':
                    # OpenAI-kompatible response_format Struktur
                    response_format_dict: Dict[str, Any] = {"type": "json_object"}
                    # Wenn Schema vorhanden und Provider unterstützt es, füge Schema hinzu
                    # (OpenAI unterstützt schema im response_format, OpenRouter möglicherweise auch)
                    if schema:
                        # Versuche Schema hinzuzufügen (Provider-abhängig)
                        response_format_dict["schema"] = schema
                    chat_kwargs['response_format'] = response_format_dict
                
                # Rufe chat_completion auf
                response_text: str
                llm_request: Any
                response_text, llm_request = provider_instance.chat_completion(
                    messages=messages,
                    model=model or "",
                    **chat_kwargs
                )
                
                # Verarbeite Structured Output wenn response_format=json_object
                structured_data: Optional[Dict[str, Any]] = None
                if response_format == 'json_object':
                    try:
                        # Extrahiere und parse JSON aus LLM-Antwort
                        from src.utils.json_validation import extract_and_parse_json, validate_json_schema
                        structured_data = extract_and_parse_json(response_text)
                        
                        # Validiere gegen Schema wenn vorhanden
                        if schema:
                            is_valid, error_message = validate_json_schema(
                                data=structured_data,
                                schema=schema,
                                strict=strict
                            )
                            if not is_valid:
                                if strict:
                                    return {
                                        'status': 'error',
                                        'error': {
                                            'code': 'SchemaValidationError',
                                            'message': error_message or 'Schema-Validierung fehlgeschlagen',
                                            'details': {
                                                'schema_id': schema_id,
                                                'response_text': response_text[:500]
                                            }
                                        }
                                    }, 400
                                else:
                                    logger.warning(
                                        'Schema-Validierung fehlgeschlagen (strict=false)',
                                        error=error_message,
                                        schema_id=schema_id
                                    )
                    except Exception as e:
                        # Bei Fehler bei JSON-Extraktion/Validierung
                        if strict:
                            return {
                                'status': 'error',
                                'error': {
                                    'code': 'JSONParseError',
                                    'message': f'Fehler beim Extrahieren/Validieren von JSON: {str(e)}',
                                    'details': {
                                        'response_text': response_text[:500]
                                    }
                                }
                            }, 400
                        else:
                            logger.warning(
                                'Fehler bei JSON-Extraktion (strict=false)',
                                error=str(e),
                                response_text=response_text[:500]
                            )
                            # Versuche trotzdem zu parsen, falls möglich
                            try:
                                from src.utils.json_validation import extract_and_parse_json
                                structured_data = extract_and_parse_json(response_text)
                            except Exception:
                                # Garantie: structured_data darf nicht null sein bei response_format=json_object
                                # Setze leeres Dict statt None, um die Garantie zu erfüllen
                                structured_data = {}
                
                # Erstelle TransformerData mit der Antwort
                transformer_data = TransformerData(
                    text=response_text if response_format == 'text' else "",  # Bei json_object kann text leer sein
                    language="",  # Chat hat keine spezifische Sprache
                    format=OutputFormat.TEXT,
                    structured_data=structured_data
                )
                
                # Tracke LLM-Nutzung (nur wenn tokens > 0)
                if llm_request and hasattr(llm_request, 'model'):
                    # Extrahiere tokens sicher
                    tokens_value: int = 0
                    if hasattr(llm_request, 'total_tokens'):
                        tokens_value = int(llm_request.total_tokens) if llm_request.total_tokens else 0
                    elif hasattr(llm_request, 'tokens'):
                        tokens_value = int(llm_request.tokens) if llm_request.tokens else 0
                    
                    # Nur tracken wenn tokens > 0
                    if tokens_value > 0:
                        _track_llm_usage(
                            model=llm_request.model if hasattr(llm_request, 'model') else model or "unknown",
                            tokens=tokens_value,
                            duration=time.time() - start_time,
                            purpose="chat_completion"
                        )
                
                # Erstelle Response mit üblicher Struktur
                end_time: float = time.time()
                duration_ms = int((end_time - start_time) * 1000)
                
                response: TransformerResponse = transformer_processor.create_response(
                    processor_name="transformer",
                    result=transformer_data,
                    request_info={
                        'messages_count': len(messages),
                        'model': model,
                        'provider': provider_name or "unknown",
                        'temperature': temperature,
                        'max_tokens': max_tokens,
                        'response_format': response_format,
                        'schema_id': schema_id,
                        'strict': strict,
                        'duration_ms': duration_ms
                    },
                    response_class=TransformerResponse,
                    from_cache=False,
                    cache_key=""
                )
                
                # Füge LLM-Info hinzu, falls verfügbar
                if llm_request:
                    from src.core.models.llm import LLMRequest, LLMInfo
                    # Extrahiere Informationen aus llm_request
                    model_name: str = model or "unknown"
                    total_tokens: int = 0
                    duration_ms: float = (time.time() - start_time) * 1000
                    
                    if hasattr(llm_request, 'model'):
                        model_name = str(llm_request.model)
                    if hasattr(llm_request, 'total_tokens'):
                        total_tokens = int(llm_request.total_tokens)
                    elif hasattr(llm_request, 'tokens'):
                        total_tokens = int(llm_request.tokens)
                    
                    # Erstelle LLMRequest-Objekt
                    llm_req = LLMRequest(
                        model=model_name,
                        purpose="chat_completion",
                        tokens=total_tokens if total_tokens > 0 else 1,  # Mindestens 1 Token
                        duration=duration_ms,
                        processor="transformer"
                    )
                    
                    # Erstelle LLMInfo mit dem Request
                    llm_info = LLMInfo(requests=[llm_req])
                    
                    # Füge LLM-Info zur Process-Info hinzu
                    if transformer_processor.process_info:
                        object.__setattr__(transformer_processor.process_info, 'llm_info', llm_info)
                
                return response.to_dict()
                
            except Exception as e:
                logger.error(
                    'Fehler bei Chat-Completion',
                    error=e,
                    traceback=traceback.format_exc()
                )
                return {
                    'status': 'error',
                    'error': {
                        'code': 'ChatCompletionError',
                        'message': f'Fehler bei Chat-Completion: {str(e)}',
                        'details': {}
                    }
                }, 400
                
        except Exception as error:
            logger.error(
                'Fehler bei Chat-Completion-Endpoint',
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                'status': 'error',
                'error': {
                    'code': 'ProcessingError',
                    'message': f'Fehler bei Chat-Completion: {error}',
                    'details': {}
                }
            }, 400

# HTML-Tabellen-Transformations-Endpunkt
@transformer_ns.route('/html-table')
class HtmlTableTransformEndpoint(Resource):
    @transformer_ns.expect(html_table_transform_parser) # type: ignore
    @transformer_ns.response(200, 'Erfolg', transformer_ns.model('HtmlTableTransformResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Nested(transformer_ns.model('TableRequestInfo', {
            'processor': fields.String(description='Name des Prozessors'),
            'timestamp': fields.String(description='Zeitstempel der Anfrage'),
            'parameters': fields.Raw(description='Anfrageparameter')
        })),
        'process': fields.Nested(transformer_ns.model('TableProcessInfo', {
            'id': fields.String(description='Eindeutige Prozess-ID'),
            'main_processor': fields.String(description='Hauptprozessor'),
            'started': fields.String(description='Startzeitpunkt'),
            'completed': fields.String(description='Endzeitpunkt'),
            'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden')
        })),
        'data': fields.Nested(transformer_ns.model('HtmlTableData', {
            'input': fields.Nested(transformer_ns.model('TableInput', {
                'text': fields.String(description='Original URL'),
                'language': fields.String(description='Eingabesprache'),
                'format': fields.String(description='Eingabeformat')
            })),
            'output': fields.Nested(transformer_ns.model('TableOutput', {
                'text': fields.String(description='Transformierter Text (JSON)'),
                'language': fields.String(description='Ausgabesprache'),
                'format': fields.String(description='Ausgabeformat'),
                'structured_data': fields.Raw(description='Strukturierte Tabellendaten', example={
                    "url": "https://example.com",
                    "table_count": 1,
                    "tables": [{
                        "table_index": 0,
                        "headers": ["Name", "Alter"],
                        "rows": [{"Name": "Max", "Alter": "30"}],
                        "metadata": {
                            "total_rows": 1,
                            "column_count": 2,
                            "has_group_info": False,
                            "paging": {
                                "start_row": 0,
                                "row_count": 1,
                                "has_more": False
                            }
                        }
                    }]
                })
            }))
        })),
        'error': fields.Nested(transformer_ns.model('TableErrorInfo', {
            'code': fields.String(description='Fehlercode'),
            'message': fields.String(description='Fehlermeldung'),
            'details': fields.Raw(description='Detaillierte Fehlerinformationen')
        }))
    }))
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """HTML-Tabellen von einer Webseite in JSON transformieren"""
        args = html_table_transform_parser.parse_args()
        tracker = get_performance_tracker()
        process_start = time.time()
        
        try:
            # Parameter direkt vom Parser verwenden (Typkonvertierung erfolgt durch den Parser)
            source_url = args['source_url']
            output_format = args.get('output_format', 'json')
            table_index = args.get('table_index')
            start_row = args.get('start_row')
            row_count = args.get('row_count')

            transformer_processor: TransformerProcessor = get_transformer_processor()
            result: TransformerResponse = transformer_processor.transformHtmlTable(
                source_url=source_url,
                output_format=output_format,
                table_index=table_index,
                start_row=start_row,
                row_count=row_count
            )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker:
                tracker.eval_result(result)
            
            # Erstelle Response
            response: TransformerResponse = transformer_processor.create_response(
                processor_name="transformer_table",
                result=result.data,
                request_info={
                    'source_url': source_url,
                    'output_format': output_format,
                    'table_index': table_index,
                    'start_row': start_row,
                    'row_count': row_count
                },
                response_class=TransformerResponse,
                from_cache=getattr(transformer_processor.process_info, 'is_from_cache', False),
                cache_key=getattr(transformer_processor.process_info, 'cache_key', "")
            )
            
            return {
                "status": "success",
                "data": response.to_dict(),
                "process": {
                    "id": transformer_processor.process_info.id,
                    # Nutze die lokal gemessene Prozessdauer in Millisekunden.
                    # Die ProcessInfo-Klasse stellt aktuell kein duration_ms-Feld bereit,
                    # daher würde ein Zugriff auf transformer_processor.process_info.duration_ms
                    # einen AttributeError auslösen. Diese Änderung dokumentiert,
                    # dass process_duration bereits die gewünschte Metrik enthält.
                    "duration_ms": process_duration,
                    "is_from_cache": transformer_processor.process_info.is_from_cache,
                    "cache_key": transformer_processor.process_info.cache_key
                }
            }

        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            error_response: TransformerResponse = transformer_processor.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'source_url': source_url,
                    'output_format': output_format,
                    'table_index': table_index,
                    'start_row': start_row,
                    'row_count': row_count
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code=error.__class__.__name__,
                    message=str(error),
                    details={}
                )
            )
            return error_response.to_dict(), 400
        except Exception as error:
            logger.error(
                'Fehler bei der HTML-Tabellen-Transformation',
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                'status': 'error',
                'error': {
                    'code': 'ProcessingError',
                    'message': f'Fehler bei der HTML-Tabellen-Transformation: {error}'
                }
            }, 400 

# Definiere ein Fehlermodell für API-Responses
error_model = transformer_ns.model('ErrorModel', {
    'status': fields.String(description='Status der Verarbeitung (error)'),
    'error': fields.Raw(description='Fehlerinformationen')
})

# Text-Datei Upload Parser - für den Datei-basierten Text-Transformer
text_upload_parser = transformer_ns.parser()
text_upload_parser.add_argument(
    'file', 
    type=FileStorage, 
    location='files',
    required=True,
    help='Die zu transformierende Textdatei (TXT, MD)'
)
text_upload_parser.add_argument(
    'source_language',
    type=str,
    location='form',
    required=True,
    help='Die Quellsprache (ISO 639-1 Code, z.B. "de", "en")'
)
text_upload_parser.add_argument(
    'target_language',
    type=str,
    location='form',
    required=True,
    help='Die Zielsprache (ISO 639-1 Code, z.B. "de", "en")'
)
text_upload_parser.add_argument(
    'summarize',
    type=str,
    location='form',
    required=False,
    default='false',
    help='Ob der Text zusammengefasst werden soll (true/false)'
)
text_upload_parser.add_argument(
    'target_format',
    type=str,
    location='form',
    required=False,
    default='TEXT',
    help='Das Zielformat (TEXT, HTML, MARKDOWN, JSON)'
)
text_upload_parser.add_argument(
    'context',
    type=str,  # JSON string
    location='form',
    required=False,
    help='Optionaler JSON-Kontext mit zusätzlichen Informationen'
)
text_upload_parser.add_argument(
    'use_cache',
    type=str,
    location='form',
    required=False,
    default='true',
    help='Ob der Cache verwendet werden soll (true/false)'
)

# Text-Datei-Transformation Endpunkt
@transformer_ns.route('/text/file')
class TransformTextFileEndpoint(Resource):
    @transformer_ns.expect(text_upload_parser)
    @transformer_ns.response(200, 'Erfolg', transformer_ns.model('TransformTextFileResponse', {
        'status': fields.String(description='Status der Verarbeitung (success/error)'),
        'request': fields.Raw(description='Details zur Anfrage'),
        'process': fields.Raw(description='Informationen zur Verarbeitung'),
        'data': fields.Raw(description='Transformiertes Ergebnis'),
        'error': fields.Raw(description='Fehlerinformationen (falls vorhanden)')
    }))
    @transformer_ns.response(400, 'Validierungsfehler', error_model)
    @transformer_ns.doc(description='Transformiert eine Textdatei (TXT, MD) von einer Sprache in eine andere')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Transformiert eine Textdatei von einer Sprache in eine andere.
        
        Unterstützt werden Plain-Text und Markdown Dateien (.txt, .md).
        Optional kann der Text zusammengefasst und in verschiedenen Formaten ausgegeben werden.
        """
        # Zeitmessung starten
        process_start_time = time.time()
        processor: TransformerProcessor | None = None
        filename: str = ""
        source_text: str = ""
        source_language: str = "de"
        target_language: str = "de"
        summarize: bool = False
        target_format_str: str = "TEXT"
        context: Dict[str, Any] = {}
        use_cache: bool = True
        
        # Prozess-ID für Tracking
        process_id = str(uuid.uuid4())
        logger.info(f"Text-Datei-Transformation gestartet: {process_id}")
        
        # Performance Tracking
        tracker: PerformanceTracker | None = get_performance_tracker() 
        if not tracker:
            tracker = get_performance_tracker(process_id)
        
        try:
            # Request-Parameter extrahieren
            args = text_upload_parser.parse_args()
            
            # Datei extrahieren und überprüfen
            uploaded_file = args.get('file')
            if not uploaded_file:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": "Keine Datei im Request gefunden."
                    }
                }, 400
                
            # Dateityp überprüfen (nur .txt und .md erlaubt)
            filename = uploaded_file.filename or ""
            if not filename.lower().endswith(('.txt', '.md')):
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidFileType",
                        "message": "Der Dateityp wird nicht unterstützt. Nur .txt und .md Dateien sind erlaubt."
                    }
                }, 400
                
            # Dateiinhalt lesen
            try:
                source_text = uploaded_file.read().decode('utf-8')
            except UnicodeDecodeError:
                # Versuche mit einer anderen Kodierung
                uploaded_file.seek(0)  # Zurück zum Anfang der Datei
                try:
                    source_text = uploaded_file.read().decode('latin-1')
                except Exception:
                    return {
                        "status": "error",
                        "error": {
                            "code": "FileDecodingError",
                            "message": "Die Datei konnte nicht korrekt dekodiert werden. Bitte stellen Sie sicher, dass es sich um eine gültige Textdatei handelt."
                        }
                    }, 400
                    
            # Parameter extrahieren
            source_language = args.get('source_language', 'de')
            target_language = args.get('target_language', 'de')
            summarize_str = args.get('summarize', 'false').lower()
            summarize = summarize_str == 'true'
            target_format_str = args.get('target_format', 'TEXT')
            use_cache_str = args.get('use_cache', 'true').lower()
            use_cache = use_cache_str != 'false'  # Alles außer explizite 'false' wird als true behandelt
            
            # Kontext parsen, falls vorhanden
            context_str = args.get('context')
            context = {}
            if context_str:
                try:
                    context = json.loads(context_str)
                except json.JSONDecodeError:
                    logger.warning(f"Ungültiger JSON-Kontext: {context_str}")
                    context = {}
            
            # Target-Format konvertieren
            try:
                target_format = OutputFormat[target_format_str] if target_format_str else None
            except KeyError:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": f"Ungültiges Zielformat: {target_format_str}. Erlaubte Werte: {', '.join([f.name for f in OutputFormat])}"
                    }
                }, 400
                
            # Processor initialisieren und Text transformieren
            processor = get_transformer_processor()
            result: TransformerResponse = processor.transform(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize,
                target_format=target_format,
                context=context,
                use_cache=use_cache
            )
            
            # Antwort erstellen
            end_time: float = time.time()
            duration_ms = int((end_time - process_start_time) * 1000)
            
            response: TransformerResponse = processor.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    'filename': filename,
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format_str,
                    'context': context,
                    'duration_ms': duration_ms
                },
                response_class=TransformerResponse,
                from_cache=processor.process_info.is_from_cache,
                cache_key=processor.process_info.cache_key or ""
            )
            
            return response.to_dict()
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            # Spezifische Fehlerbehandlung
            logger.error(f"Bekannter Fehler bei der Text-Datei-Transformation: {str(e)}")

            proc = processor or get_transformer_processor()
            error_response = proc.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'filename': filename,
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format_str,
                    'context': context
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code=e.__class__.__name__,
                    message=str(e),
                    details={"traceback": traceback.format_exc()}
                )
            )
            return error_response.to_dict(), 400
            
        except Exception as e:
            # Allgemeine Fehlerbehandlung
            logger.error(f"Fehler bei der Text-Datei-Transformation: {str(e)}")
            logger.error(traceback.format_exc())

            proc = processor or get_transformer_processor()
            error_response = proc.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'filename': filename,
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format_str,
                    'context': context
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="ProcessingError",
                    message=f"Fehler bei der Text-Datei-Transformation: {str(e)}",
                    details={"traceback": traceback.format_exc()}
                )
            )
            return error_response.to_dict(), 400

# Metadata Upload Parser - für den integrierten Metadata-Endpoint
metadata_upload_parser = transformer_ns.parser()
metadata_upload_parser.add_argument(
    'file', 
    type=FileStorage, 
    location='files',
    required=True,
    help='Die zu analysierende Datei'
)
metadata_upload_parser.add_argument(
    'content',
    type=str,
    location='form',
    required=False,
    help='Optionaler zusätzlicher Text für die Analyse'
)
metadata_upload_parser.add_argument(
    'context',
    type=str,  # JSON string
    location='form',
    required=False,
    help='Optionaler JSON-Kontext mit zusätzlichen Informationen'
)
metadata_upload_parser.add_argument(
    'use_cache',
    type=str,
    location='form',
    required=False,
    default='true',
    help='Ob der Cache verwendet werden soll (true/false)'
)

metadata_response = transformer_ns.model('MetadataResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Raw(description='Details zur Anfrage'),
    'process': fields.Raw(description='Informationen zur Verarbeitung'),
    'data': fields.Raw(description='Extrahierte Metadaten'),
    'error': fields.Raw(description='Fehlerinformationen (falls vorhanden)')
})

# XXL-Text Upload Parser - für große Textdateien mit Chunking + Zusammenfassung
xxl_text_upload_parser = transformer_ns.parser()
xxl_text_upload_parser.add_argument(
    'file',
    type=FileStorage,
    location='files',
    required=True,
    help='Die zu zusammenfassende Textdatei (TXT, MD)'
)
xxl_text_upload_parser.add_argument(
    'target_language',
    type=str,
    location='form',
    required=False,
    default='de',
    help='Zielsprache der Zusammenfassung (ISO 639-1 Code, default: de)'
)
xxl_text_upload_parser.add_argument(
    'max_parallel',
    type=int,
    location='form',
    required=False,
    default=3,
    help='Maximale Parallelität (1..3, default: 3)'
)
xxl_text_upload_parser.add_argument(
    'overlap_ratio',
    type=float,
    location='form',
    required=False,
    default=0.04,
    help='Overlap-Anteil relativ zur Chunkgröße (0.01..0.10 empfohlen, default: 0.04)'
)
xxl_text_upload_parser.add_argument(
    'use_cache',
    type=str,
    location='form',
    required=False,
    default='false',
    help='Ob der Cache verwendet werden soll (true/false, default: false)'
)
xxl_text_upload_parser.add_argument(
    'detail_level',
    type=str,
    location='form',
    required=False,
    default='high',
    help="Detailgrad der Zusammenfassung ('normal' oder 'high', default: high)"
)
xxl_text_upload_parser.add_argument(
    'instructions',
    type=str,
    location='form',
    required=False,
    help='Optionale Zusatz-Anweisungen für den Prompt (max. 5000 Zeichen).'
)
xxl_text_upload_parser.add_argument(
    'prompt_use_case',
    type=str,
    location='form',
    required=False,
    default='cursor_chat_analysis',
    help="Prompt-Use-Case: 'general' oder 'cursor_chat_analysis' (default: cursor_chat_analysis)"
)
xxl_text_upload_parser.add_argument(
    'min_chunk_summary_chars',
    type=int,
    location='form',
    required=False,
    default=5000,
    help='Mindestlänge pro Chunk-Summary in Zeichen (default: 5000, 0 deaktiviert)'
)
xxl_text_upload_parser.add_argument(
    'min_final_summary_chars',
    type=int,
    location='form',
    required=False,
    default=7000,
    help='Mindestlänge der finalen Summary in Zeichen (default: 7000, 0 deaktiviert)'
)
xxl_text_upload_parser.add_argument(
    'chunk_max_tokens',
    type=int,
    location='form',
    required=False,
    default=8000,
    help='Maximale Output-Tokens pro Chunk-Summary (default: 8000)'
)
xxl_text_upload_parser.add_argument(
    'final_max_tokens',
    type=int,
    location='form',
    required=False,
    default=8000,
    help='Maximale Output-Tokens für die finale Summary (default: 8000)'
)

@transformer_ns.route('/xxl-text')
class XXLTextSummarizeEndpoint(Resource):
    @transformer_ns.expect(xxl_text_upload_parser)
    @transformer_ns.response(200, 'Erfolg')
    @transformer_ns.response(400, 'Validierungsfehler', error_model)
    @transformer_ns.doc(description='Fasst eine sehr große Textdatei zusammen (Chunking + Summary-of-summaries).')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        process_start_time = time.time()
        process_id = str(uuid.uuid4())
        processor: TransformerProcessor | None = None
        filename: str = ""
        file_size_bytes: int = 0
        detected_encoding: str = "unknown"
        file_sha256: str = ""

        try:
            args = xxl_text_upload_parser.parse_args()

            uploaded_file = args.get('file')
            if not uploaded_file:
                return {
                    "status": "error",
                    "error": {"code": "InvalidRequest", "message": "Keine Datei im Request gefunden."}
                }, 400

            filename = uploaded_file.filename or ""
            if not filename.lower().endswith(('.txt', '.md')):
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidFileType",
                        "message": "Der Dateityp wird nicht unterstützt. Nur .txt und .md Dateien sind erlaubt."
                    }
                }, 400

            # Dateiinhalt lesen (UTF-8 bevorzugt)
            try:
                raw_bytes = uploaded_file.read()
                file_size_bytes = len(raw_bytes)
                file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                source_text = raw_bytes.decode('utf-8')
                detected_encoding = "utf-8"
            except UnicodeDecodeError:
                try:
                    source_text = raw_bytes.decode('latin-1')
                    detected_encoding = "latin-1"
                except Exception:
                    return {
                        "status": "error",
                        "error": {
                            "code": "FileDecodingError",
                            "message": "Die Datei konnte nicht korrekt dekodiert werden (UTF-8/Latin-1)."
                        }
                    }, 400

            target_language = str(args.get('target_language', 'de') or 'de')
            max_parallel = int(args.get('max_parallel', 3) or 3)
            overlap_ratio = float(args.get('overlap_ratio', 0.04) or 0.04)
            use_cache_str = str(args.get('use_cache', 'true') or 'true').lower()
            use_cache = use_cache_str != 'false'
            detail_level = str(args.get('detail_level', 'normal') or 'normal').strip().lower()
            instructions_raw = args.get('instructions')
            instructions = str(instructions_raw) if instructions_raw is not None else None
            prompt_use_case = str(args.get('prompt_use_case', 'general') or 'general').strip().lower()
            min_chunk_summary_chars = int(args.get('min_chunk_summary_chars', 5000) or 5000)
            min_final_summary_chars = int(args.get('min_final_summary_chars', 5000) or 5000)
            chunk_max_tokens = int(args.get('chunk_max_tokens', 4096) or 4096)
            final_max_tokens = int(args.get('final_max_tokens', 4096) or 4096)

            # Clamp defensiv im API-Layer
            if max_parallel < 1:
                max_parallel = 1
            if max_parallel > 3:
                max_parallel = 3
            if overlap_ratio < 0.0:
                overlap_ratio = 0.0
            if overlap_ratio > 0.5:
                overlap_ratio = 0.5
            if detail_level not in {"normal", "high"}:
                detail_level = "normal"
            if instructions is not None:
                instructions = instructions.strip()
                if len(instructions) > 5000:
                    return {
                        "status": "error",
                        "error": {
                            "code": "InvalidRequest",
                            "message": "instructions ist zu lang (max. 5000 Zeichen)."
                        }
                    }, 400
                if not instructions:
                    instructions = None
            if prompt_use_case not in {"general", "cursor_chat_analysis"}:
                prompt_use_case = "general"

            # Mindestlängen defensiv clampen (0 erlaubt zum Deaktivieren)
            if min_chunk_summary_chars < 0:
                min_chunk_summary_chars = 0
            if min_final_summary_chars < 0:
                min_final_summary_chars = 0
            if min_chunk_summary_chars > 50_000:
                min_chunk_summary_chars = 50_000
            if min_final_summary_chars > 50_000:
                min_final_summary_chars = 50_000

            # Token-Limits defensiv clampen (0 deaktiviert)
            if chunk_max_tokens < 0:
                chunk_max_tokens = 0
            if final_max_tokens < 0:
                final_max_tokens = 0
            if chunk_max_tokens == 0:
                chunk_max_tokens = 4096
            if final_max_tokens == 0:
                final_max_tokens = 4096
            if chunk_max_tokens > 200_000:
                chunk_max_tokens = 200_000
            if final_max_tokens > 200_000:
                final_max_tokens = 200_000

            processor = get_transformer_processor()

            result: TransformerResponse = processor.summarize_xxl_text(
                source_text=source_text,
                source_filename=filename,
                source_file_size_bytes=file_size_bytes,
                source_detected_encoding=detected_encoding,
                source_sha256=file_sha256,
                target_language=target_language,
                max_parallel=max_parallel,
                overlap_ratio=overlap_ratio,
                use_cache=use_cache,
                detail_level=detail_level,
                instructions=instructions,
                prompt_use_case=prompt_use_case,
                min_chunk_summary_chars=min_chunk_summary_chars,
                min_final_summary_chars=min_final_summary_chars,
                chunk_max_tokens=chunk_max_tokens,
                final_max_tokens=final_max_tokens,
            )

            duration_ms = int((time.time() - process_start_time) * 1000)

            response: TransformerResponse = processor.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    "filename": filename,
                    "text": _truncate_text(source_text),
                    "file_size_bytes": file_size_bytes,
                    "detected_encoding": detected_encoding,
                    "file_sha256": file_sha256,
                    "input_chars": len(source_text),
                    "target_language": target_language,
                    "max_parallel": max_parallel,
                    "overlap_ratio": overlap_ratio,
                    "use_cache": use_cache,
                    "detail_level": detail_level,
                    "instructions": _truncate_text(instructions) if instructions else None,
                    "prompt_use_case": prompt_use_case,
                    "min_chunk_summary_chars": min_chunk_summary_chars,
                    "min_final_summary_chars": min_final_summary_chars,
                    "chunk_max_tokens": chunk_max_tokens,
                    "final_max_tokens": final_max_tokens,
                    "duration_ms": duration_ms,
                    "use_case": UseCase.TRANSFORMER_XXL.value,
                },
                response_class=TransformerResponse,
                from_cache=processor.process_info.is_from_cache,
                cache_key=processor.process_info.cache_key or "",
            )

            return response.to_dict()

        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            logger.error(f"Bekannter Fehler bei XXL-Text-Zusammenfassung: {str(e)}")
            proc = processor or get_transformer_processor()
            error_response = proc.create_response(
                processor_name="transformer",
                result=None,
                request_info={"filename": filename, "use_case": UseCase.TRANSFORMER_XXL.value},
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code=e.__class__.__name__,
                    message=str(e),
                    details={"traceback": traceback.format_exc()},
                ),
            )
            return error_response.to_dict(), 400
        except Exception as e:
            logger.error(f"Fehler bei XXL-Text-Zusammenfassung: {str(e)}")
            logger.error(traceback.format_exc())
            proc = processor or get_transformer_processor()
            error_response = proc.create_response(
                processor_name="transformer",
                result=None,
                request_info={"filename": filename, "use_case": UseCase.TRANSFORMER_XXL.value},
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="ProcessingError",
                    message=f"Fehler bei XXL-Text-Zusammenfassung: {str(e)}",
                    details={"traceback": traceback.format_exc()},
                ),
            )
            return error_response.to_dict(), 400

# Metadata-Extraktion Endpunkt (aus src/api/routes.py integriert)
@transformer_ns.route('/metadata')
class MetadataEndpoint(Resource):
    @transformer_ns.expect(metadata_upload_parser)
    @transformer_ns.response(200, 'Erfolg', metadata_response)
    @transformer_ns.response(400, 'Validierungsfehler', error_model)
    @transformer_ns.doc(description='Extrahiert Metadaten aus Dateien wie Bildern, Videos, PDFs und anderen Dokumenten')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Extrahiert Metadaten aus einer Datei oder einem Text.
        
        Die Metadaten enthalten technische Informationen (Dateigröße, Format, etc.) 
        und inhaltliche Metadaten (Titel, Autoren, Beschreibung, etc.).
        """
        # Zeitmessung starten
        process_start_time = time.time()
        
        # Prozess-Tracking initialisieren
        process_id = str(uuid.uuid4())
        logger.info(f"Metadata API Request gestartet: {process_id}")
        
        # Performance Tracking für detaillierte Zeitmessung
        tracker: PerformanceTracker | None = get_performance_tracker() or get_performance_tracker(process_id)
        
        try:
            # Request-Parameter extrahieren
            args = metadata_upload_parser.parse_args()
            uploaded_file = args.get('file')
            content = args.get('content')
            context_str = args.get('context')
            use_cache_str = args.get('use_cache', 'true').lower()
            use_cache = use_cache_str != 'false'  # Alles außer explizite 'false' wird als true behandelt
            
            # Kontext parsen, falls vorhanden
            context = None
            if context_str:
                try:
                    context = json.loads(context_str)
                except json.JSONDecodeError:
                    logger.warning(f"Ungültiger JSON-Kontext: {context_str}")
                    context = {}
            
            # MetadataProcessor verwenden
            processor = get_metadata_processor(process_id)
            
            # Metadaten extrahieren - mit asyncio.run ausführen, da die Methode asynchron ist
            result = asyncio.run(processor.process(
                binary_data=uploaded_file,
                content=content,
                context=context,
                use_cache=use_cache
            ))
            
            # Response direkt zurückgeben, da die process-Methode bereits eine vollständige
            # MetadataResponse zurückgibt, die unserem API-Format entspricht
            if isinstance(result, dict):
                return result
            else:
                return result.to_dict()
                
        except ProcessingError as e:
            logger.error("Bekannter Verarbeitungsfehler",
                        error=e,
                        error_type="ProcessingError",
                        process_id=process_id)
            return {
                'status': 'error',
                'error': {
                    'code': 'ProcessingError',
                    'message': str(e),
                    'details': {}
                }
            }, 400
        except Exception as e:
            logger.error("Fehler bei der Metadaten-Extraktion",
                        error=e,
                        error_type=type(e).__name__,
                        stack_trace=traceback.format_exc(),
                        process_id=process_id)
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