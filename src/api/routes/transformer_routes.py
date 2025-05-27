# type: ignore
"""
Transformer API-Routen.
Enthält Endpoints für Text- und Template-Transformationen.
"""
from datetime import datetime
import time
from typing import Dict, Any, Union, Optional, List, cast
import traceback
import uuid
import json
import asyncio

from flask import request
from werkzeug.datastructures import FileStorage
from flask_restx import Namespace, Resource, fields, inputs  # type: ignore

from src.core.models.transformer import TransformerResponse
from src.processors.transformer_processor import TransformerProcessor
from src.processors.metadata_processor import MetadataProcessor, MetadataResponse
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from src.utils.logger import ProcessingLogger
from src.utils.performance_tracker import PerformanceTracker
from src.core.models.enums import OutputFormat
from src.core.models.base import (
    BaseResponse,
    RequestInfo,
    ProcessInfo,
    ErrorInfo
)

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
            error=e,
            model=model,
            tokens=tokens,
            duration=duration
        )

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

# Parser für den Template-Transformations-Endpunkt
template_transform_parser = transformer_ns.parser()
template_transform_parser.add_argument('text', type=str, location='form', required=True, help='Der zu transformierende Text')
template_transform_parser.add_argument('source_language', type=str, location='form', default='de', help='Quellsprache (ISO 639-1 code, z.B. "en", "de")')
template_transform_parser.add_argument('target_language', type=str, location='form', default='de', help='Zielsprache (ISO 639-1 code, z.B. "en", "de")')
template_transform_parser.add_argument('template', type=str, location='form', required=True, help='Name des Templates (ohne .md Endung)')
template_transform_parser.add_argument('context', type=str, location='form', required=False, help='Optionaler JSON-String Kontext für die Template-Verarbeitung')
template_transform_parser.add_argument('use_cache', type=inputs.boolean, location='form', required=False, default=True, help='Ob der Cache verwendet werden soll (true/false)')

# Parser für den HTML-Tabellen-Transformations-Endpunkt
html_table_transform_parser = transformer_ns.parser()
html_table_transform_parser.add_argument('source_url', type=str, location='form', required=True, help='Die URL der Webseite mit der HTML-Tabelle')
html_table_transform_parser.add_argument('output_format', type=str, location='form', default='json', help='Ausgabeformat (aktuell nur JSON unterstützt)')
html_table_transform_parser.add_argument('table_index', type=int, location='form', required=False, help='Optional - Index der gewünschten Tabelle (0-basiert).')
html_table_transform_parser.add_argument('start_row', type=int, location='form', required=False, help='Optional - Startzeile für das Paging (0-basiert)')
html_table_transform_parser.add_argument('row_count', type=int, location='form', required=False, help='Optional - Anzahl der zurückzugebenden Zeilen')

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
        try:
            # Request-Daten extrahieren mit dem Parser
            args = text_transform_parser.parse_args()
            
            # Parameter extrahieren
            source_text = args.get('text', '')
            source_language = args.get('source_language', 'de')
            target_language = args.get('target_language', 'de')
            summarize = args.get('summarize', False)
            target_format_str = args.get('target_format', 'TEXT')
            context_str = args.get('context')
            use_cache = args.get('use_cache', True)

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
            processor: TransformerProcessor = get_transformer_processor()
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
                    'duration_ms': duration_ms
                },
                response_class=TransformerResponse,
                from_cache=processor.process_info.is_from_cache,    
                cache_key=processor.process_info.cache_key
            )

            return response.to_dict()
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            # Spezifische Fehlerbehandlung
            logger.error(f"Bekannter Fehler bei der Text-Transformation: {str(e)}")
            
            error_response = processor.create_response(
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
                    details=traceback.format_exc()
                )
            )
            return error_response.to_dict(), 400
            
        except Exception as e:
            # Allgemeine Fehlerbehandlung
            logger.error(f"Fehler bei der Text-Transformation: {str(e)}")
            logger.error(traceback.format_exc())
            
            error_response = processor.create_response(
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
                    details=traceback.format_exc()
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
        args = template_transform_parser.parse_args()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            # Parameter extrahieren
            text = args.get('text', '')
            source_language = args.get('source_language', 'de')
            target_language = args.get('target_language', 'de')
            template = args.get('template', '')
            context_str = args.get('context')
            use_cache = args.get('use_cache', True)

            # Kontext parsen, falls vorhanden
            context = {}
            if context_str:
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

            start_time: float = time.time()
            transformer_processor: TransformerProcessor = get_transformer_processor()
            result: TransformerResponse = transformer_processor.transformByTemplate(
                text=text,
                template=template,
                source_language=source_language,
                target_language=target_language,
                context=context,
                use_cache=use_cache
            )

            # Antwort erstellen
            end_time: float = time.time()
            duration_ms = int((end_time - start_time) * 1000)

            response: TransformerResponse = transformer_processor.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    'text': _truncate_text(text),
                    'template': template,
                    'source_language': source_language,
                    'target_language': target_language,
                    'context': context,
                    'use_cache': use_cache,
                    'duration_ms': duration_ms
                },
                response_class=TransformerResponse,
                from_cache=transformer_processor.process_info.is_from_cache,    
                cache_key=transformer_processor.process_info.cache_key
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
                    "duration_ms": transformer_processor.process_info.duration_ms,
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
            processor: TransformerProcessor = get_transformer_processor()
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
                cache_key=processor.process_info.cache_key
            )
            
            return response.to_dict()
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            # Spezifische Fehlerbehandlung
            logger.error(f"Bekannter Fehler bei der Text-Datei-Transformation: {str(e)}")
            
            error_response = BaseResponse(
                status="error",
                error=ErrorInfo(
                    code=e.__class__.__name__,
                    message=str(e),
                    details=traceback.format_exc()
                ),
                request=RequestInfo(
                    processor="transformer",
                    timestamp=datetime.now().isoformat(),
                    parameters={
                        'filename': getattr(uploaded_file, 'filename', None),
                        'source_language': args.get('source_language', 'de'),
                        'target_language': args.get('target_language', 'de')
                    }
                ),
                process=ProcessInfo(
                    id=process_id,
                    main_processor="transformer",
                    started=datetime.now().isoformat(),
                    completed=datetime.now().isoformat(),
                    duration_ms=int((time.time() - process_start_time) * 1000)
                )
            )
            return error_response.to_dict(), 400
            
        except Exception as e:
            # Allgemeine Fehlerbehandlung
            logger.error(f"Fehler bei der Text-Datei-Transformation: {str(e)}")
            logger.error(traceback.format_exc())
            
            error_response = BaseResponse(
                status="error",
                error=ErrorInfo(
                    code="ProcessingError",
                    message=f"Fehler bei der Text-Datei-Transformation: {str(e)}",
                    details=traceback.format_exc()
                ),
                request=RequestInfo(
                    processor="transformer",
                    timestamp=datetime.now().isoformat(),
                    parameters={
                        'filename': getattr(uploaded_file, 'filename', None),
                        'source_language': args.get('source_language', 'de') if args else 'de',
                        'target_language': args.get('target_language', 'de') if args else 'de'
                    }
                ),
                process=ProcessInfo(
                    id=process_id,
                    main_processor="transformer",
                    started=datetime.now().isoformat(),
                    completed=datetime.now().isoformat(),
                    duration_ms=int((time.time() - process_start_time) * 1000)
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