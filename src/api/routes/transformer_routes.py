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
from flask_restx import Namespace, Resource, fields  # type: ignore

from core.models.transformer import TransformerResponse
from src.processors.transformer_processor import TransformerProcessor
from src.processors.metadata_processor import MetadataProcessor, MetadataResponse
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from utils.logger import ProcessingLogger
from utils.performance_tracker import PerformanceTracker
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

# Text-Transformation Endpoint
@transformer_ns.route('/text')  # type: ignore
class TransformTextEndpoint(Resource):
    # Swagger-Dokumentation für den Endpunkt
    transform_model = transformer_ns.model('TransformRequest', {
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'source_language': fields.String(required=True, description='Die Quellsprache (ISO 639-1 Code)'),
        'target_language': fields.String(required=True, description='Die Zielsprache (ISO 639-1 Code)'),
        'summarize': fields.Boolean(required=False, default=False, description='Ob der Text zusammengefasst werden soll'),
        'target_format': fields.String(required=False, description='Das Zielformat (TEXT, HTML, MARKDOWN, JSON)'),
        'context': fields.Raw(required=False, description='Optionaler Kontext für die Transformation'),
        'use_cache': fields.Boolean(required=False, default=True, description='Ob der Cache verwendet werden soll')
    })
    
    @transformer_ns.doc(description='Transformiert Text von einer Sprache in eine andere')  # type: ignore
    @transformer_ns.expect(transform_model)  # type: ignore
    @transformer_ns.response(200, 'Erfolgreiche Transformation')  # type: ignore
    @transformer_ns.response(400, 'Ungültige Anfrage')  # type: ignore
    @transformer_ns.response(500, 'Server-Fehler')  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Transformiert Text von einer Sprache in eine andere, mit optionaler Zusammenfassung."""
        try:
            # Request-Daten extrahieren
            data = request.json
            if not data:
                return {
                    "status": "error",
                    "error": {
                        "code": "InvalidRequest",
                        "message": "Keine Daten im Request gefunden."
                    }
                }, 400
            
            # Parameter extrahieren
            source_text = data.get('text', '')
            source_language = data.get('source_language', 'de')
            target_language = data.get('target_language', 'de')
            summarize = data.get('summarize', False)
            target_format_str = data.get('target_format', 'TEXT')
            context = data.get('context', {})
            use_cache = data.get('use_cache', True)
            
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
    @transformer_ns.expect(transformer_ns.model('TransformTemplateInput', {  # type: ignore
        'text': fields.String(required=True, description='Der zu transformierende Text'),
        'source_language': fields.String(default='de', description='Quellsprache (ISO 639-1 code, z.B. "en", "de")'),
        'target_language': fields.String(default='de', description='Zielsprache (ISO 639-1 code, z.B. "en", "de")'),
        'template': fields.String(required=True, description='Name des Templates (ohne .md Endung)'),
        'context': fields.String(required=False, description='Kontextinformationen für die Template-Verarbeitung'),
        'use_cache': fields.Boolean(required=False, default=True, description='Ob der Cache verwendet werden soll')
    }))
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
        from flask import request as flask_request  # Lokaler Import, um Namenskonflikte zu vermeiden
        data = flask_request.get_json()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:

            # Parameter extrahieren
            text = data.get('text', '')
            source_language = data.get('source_language', 'de')
            target_language = data.get('target_language', 'de')
            template = data.get('template', '')
            context = data.get('context', {})
            use_cache = data.get('use_cache', True)


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
                    'source_text': _truncate_text(data['text']),
                    'source_language': data.get('source_language', 'de'),
                    'target_language': data.get('target_language', 'de'),
                    'template': data['template'],
                    'context': data.get('context', {})
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
    @transformer_ns.expect(transformer_ns.model('TransformHtmlTableInput', {
        'source_url': fields.String(required=True, description='Die URL der Webseite mit der HTML-Tabelle'),
        'output_format': fields.String(default='json', enum=['json'], description='Ausgabeformat (aktuell nur JSON unterstützt)'),
        'table_index': fields.Integer(required=False, description='Optional - Index der gewünschten Tabelle (0-basiert). Wenn nicht angegeben, werden alle Tabellen zurückgegeben.'),
        'start_row': fields.Integer(required=False, description='Optional - Startzeile für das Paging (0-basiert)'),
        'row_count': fields.Integer(required=False, description='Optional - Anzahl der zurückzugebenden Zeilen')
    }))
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
        data = request.get_json()
        tracker = get_performance_tracker()
        process_start = time.time()
        
        try:
            # Konvertiere numerische Parameter explizit zu Integer
            table_index = int(data.get('table_index')) if data.get('table_index') is not None else None
            start_row = int(data.get('start_row')) if data.get('start_row') is not None else None
            row_count = int(data.get('row_count')) if data.get('row_count') is not None else None

            transformer_processor: TransformerProcessor = get_transformer_processor()
            result: TransformerResponse = transformer_processor.transformHtmlTable(
                source_url=data['source_url'],
                output_format=data.get('output_format', 'json'),
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
                    'source_url': data['source_url'],
                    'output_format': data.get('output_format', 'json'),
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
                    'source_url': data['source_url'],
                    'output_format': data.get('output_format', 'json'),
                    'table_index': data.get('table_index'),
                    'start_row': data.get('start_row'),
                    'row_count': data.get('row_count')
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