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

from flask import request
from flask_restx import Namespace, Resource, fields  # type: ignore

from core.models.transformer import TransformerResponse
from src.processors.transformer_processor import TransformerProcessor
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, RateLimitExceeded
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.performance_tracker import get_performance_tracker
from utils.logger import ProcessingLogger
from utils.performance_tracker import PerformanceTracker
from src.core.models.enums import OutputFormat

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="transformer-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
transformer_ns = Namespace('transformer', description='Transformer Operationen')

# Helper-Funktion zum Abrufen des Transformer-Processors
def get_transformer_processor(process_id: Optional[str] = None) -> TransformerProcessor:
    """Get or create transformer processor instance with process ID"""
    return TransformerProcessor(resource_calculator, process_id=process_id or str(uuid.uuid4()))

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
            
            # Logging
            logger.info(f"Transformiere Text: {_truncate_text(source_text)}")
            logger.info(f"Von {source_language} nach {target_language}, Zusammenfassung: {summarize}")
            
            # Performance-Tracking starten
            process_id = str(uuid.uuid4())
            tracker: PerformanceTracker | None = get_performance_tracker(process_id)
            start_time = time.time()
            start_datetime = datetime.now().isoformat()
            
            # Processor initialisieren und Text transformieren
            processor = get_transformer_processor(process_id)
            result = processor.transform(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize,
                target_format=target_format,
                context=context,
                use_cache=use_cache
            )
            
            # LLM-Nutzung tracken
            if hasattr(processor, 'llm_usage') and processor.llm_usage:  # type: ignore
                model_name = processor.llm_usage.get('model', 'gpt-3.5-turbo')  # type: ignore
                total_tokens = processor.llm_usage.get('total_tokens', 0)  # type: ignore
                duration = time.time() - start_time
                
                _track_llm_usage(
                    model=model_name,  # type: ignore
                    tokens=total_tokens,  # type: ignore
                    duration=duration,
                    purpose="transform-text"
                )
                
                # Kosten berechnen
                cost = _calculate_llm_cost(model_name, total_tokens)  # type: ignore
                
                # LLM-Info für Response vorbereiten
                llm_info = {  # type: ignore
                    'model': model_name,
                    'prompt_tokens': processor.llm_usage.get('prompt_tokens', 0),  # type: ignore
                    'completion_tokens': processor.llm_usage.get('completion_tokens', 0),  # type: ignore
                    'total_tokens': total_tokens,
                    'cost': cost
                }
            else:
                llm_info = {}
            
            # Antwort erstellen
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            response_data = {
                "status": "success",
                "data": {
                    "transformed_text": result.data.output.text,
                    "language": result.data.output.language,
                    "format": result.data.output.format.value,
                    "summarized": result.data.output.summarized,
                    "structured_data": result.data.output.structured_data
                }
            }
            
            return response_data
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as e:
            # Spezifische Fehlerbehandlung
            logger.error(f"Bekannter Fehler bei der Text-Transformation: {str(e)}")
            
            return {
                "status": "error",
                "error": {
                    "code": e.__class__.__name__,
                    "message": str(e),
                    "details": traceback.format_exc()
                }
            }, 400
            
        except Exception as e:
            # Allgemeine Fehlerbehandlung
            logger.error(f"Fehler bei der Text-Transformation: {str(e)}")
            logger.error(traceback.format_exc())
            
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError",
                    "message": f"Fehler bei der Text-Transformation: {str(e)}",
                    "details": traceback.format_exc()
                }
            }, 400

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
            # Zeitmessung für Gesamtprozess starten
            process_start = time.time()
            
            transformer_processor: TransformerProcessor = get_transformer_processor(tracker.process_id if tracker else None)
            result: TransformerResponse = transformer_processor.transformByTemplate(
                source_text=data['text'],
                source_language=data.get('source_language', 'de'),
                target_language=data.get('target_language', 'de'),
                template=data['template'],
                context=data.get('context', {}),
                use_cache=data.get('use_cache', True)
            )

            # Tracke LLM-Nutzung wenn vorhanden
            if result.llm_info:
                for request in result.llm_info.requests:
                    _track_llm_usage(
                        model=request.model,
                        tokens=request.tokens,
                        duration=request.duration,
                        purpose='template_transformation'
                    )

            # Berechne Gesamtkosten
            total_cost = 0.0
            if result.llm_info:
                for request in result.llm_info.requests:
                    total_cost += _calculate_llm_cost(
                        model=request.model,
                        tokens=request.tokens
                    )

            # Gesamtprozessdauer in Millisekunden berechnen
            process_duration = int((time.time() - process_start) * 1000)

            # Füge Ressourcenverbrauch zum Tracker hinzu
            if tracker:
                tracker.eval_result(result)
            
            # Erstelle Response
            response: Dict[str, Any] = {
                'status': 'error' if result.error else 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_text': _truncate_text(data['text']),
                        'source_language': data.get('source_language', 'de'),
                        'target_language': data.get('target_language', 'de'),
                        'template': data['template'],
                        'context': data.get('context', {}),
                        'duration_ms': process_duration
                    }
                },
                'process': result.process.to_dict(),  # Nutze die to_dict() Methode von ProcessInfo
                'data': {
                    'input': {
                        'text': data['text'],
                        'language': data.get('source_language', ''),
                        'template': data['template'],
                        'context': data.get('context', {})
                    },
                    'output': {
                        'text': result.data.output.text if not result.error else None,
                        'language': result.data.output.language if not result.error else None,
                        'structured_data': result.data.output.structured_data if hasattr(result.data.output, 'structured_data') and not result.error else {}
                    }
                }
            }

            # Füge error-Informationen hinzu wenn vorhanden
            if result.error:
                response['error'] = {
                    'code': result.error.code,
                    'message': result.error.message,
                    'details': result.error.details if hasattr(result.error, 'details') else {}
                }
                return response, 400
            
            return response
            
        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            return {
                'status': 'error',
                'error': {
                    'code': error.__class__.__name__,
                    'message': str(error),
                    'details': {}
                }
            }, 400
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

            transformer_processor: TransformerProcessor = get_transformer_processor(tracker.process_id if tracker else None)
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
            response = {
                'status': 'success',
                'request': {
                    'processor': 'transformer',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'source_url': data['source_url'],
                        'output_format': data.get('output_format', 'json'),
                        'table_index': data.get('table_index'),
                        'start_row': data.get('start_row'),
                        'row_count': data.get('row_count'),
                        'duration_ms': process_duration
                    }
                },
                'process': {
                    'id': tracker.process_id if tracker else None,
                    'main_processor': 'transformer',
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': process_duration
                },
                'data': {
                    'input': {
                        'text': result.data.input.text,
                        'language': result.data.input.language,
                        'format': result.data.input.format.value
                    },
                    'output': {
                        'text': result.data.output.text,
                        'language': result.data.output.language,
                        'format': result.data.output.format.value,
                        'structured_data': result.data.output.structured_data
                    }
                }
            }

            if result.error:
                response['error'] = {
                    'code': result.error.code,
                    'message': result.error.message,
                    'details': result.error.details
                }
                return response, 400

            return response

        except (ProcessingError, FileSizeLimitExceeded, RateLimitExceeded) as error:
            return {
                'status': 'error',
                'error': {
                    'code': error.__class__.__name__,
                    'message': str(error)
                }
            }, 400
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