"""
@fileoverview Text2Image API Routes - Flask-RESTX endpoints for text-to-image generation

@description
Text2Image Processor API routes. Contains all endpoints for generating images from text prompts.
This file defines REST API endpoints for text-to-image generation with Flask-RESTX,
including prompt-based generation and caching.

Main endpoints:
- POST /api/text2image/generate: Generate image from text prompt

Features:
- JSON-based request/response
- Support for various image sizes and quality settings
- Caching support
- Swagger UI documentation

@module api.routes.text2image_routes

@exports
- text2image_ns: Namespace - Flask-RESTX namespace for text2image endpoints
- generate_parser: RequestParser - Parser for generation parameters

@usedIn
- src.api.routes.__init__: Registers text2image_ns namespace

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- Internal: src.processors.text2image_processor - Text2ImageProcessor
- Internal: src.core.models.text2image - Text2ImageResponse
- Internal: src.core.exceptions - ProcessingError
- Internal: src.utils.logger - Logging system
"""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# type: ignore
from flask_restx import Model, Namespace, OrderedModel, Resource, fields, inputs
from typing import Dict, Any, Union, Optional, cast
import asyncio
import uuid

from src.processors.text2image_processor import Text2ImageProcessor
from src.core.models.text2image import Text2ImageResponse
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.utils.logger import get_logger
from src.utils.logger import ProcessingLogger

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="text2image-api")

# Initialisiere Resource Calculator
resource_calculator = ResourceCalculator()

# Erstelle Namespace
text2image_ns = Namespace('text2image', description='Text-zu-Bild-Generierungs-Operationen')

# Parser für Text2Image-Generierung Parameter
# Verwende 'form' statt 'json', damit Swagger UI ein Formular zeigt
generate_parser = text2image_ns.parser()
generate_parser.add_argument('prompt', location='form', type=str, required=True, help='Text-Prompt für Bildgenerierung')
generate_parser.add_argument('size', location='form', type=str, default='1024x1024', help='Bildgröße (z.B. "1024x1024", "1792x1024", "1024x1792")')
generate_parser.add_argument('quality', location='form', type=str, default='standard', choices=['standard', 'hd'], help='Qualität ("standard" oder "hd")')
generate_parser.add_argument('n', location='form', type=int, default=1, help='Anzahl der Bilder (default: 1, max: 1 für die meisten Modelle)')
generate_parser.add_argument('seed', location='form', type=int, required=False, help='Optional: Seed für Reproduzierbarkeit')
generate_parser.add_argument('seeds', location='form', type=str, required=False, help='Optional: Kommaseparierte Liste von Seeds')
generate_parser.add_argument('useCache', location='form', type=inputs.boolean, default=True, help='Cache verwenden (default: True)')

# Definiere Error-Modell
error_model: Model | OrderedModel = text2image_ns.model('Error', {
    'status': fields.String(description='Status der Anfrage (error)'),
    'error': fields.Nested(text2image_ns.model('ErrorDetails', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Zusätzliche Fehlerdetails')
    }))
})

# Definiere Modelle für die API-Dokumentation
text2image_response: Model | OrderedModel = text2image_ns.model('Text2ImageResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(text2image_ns.model('Text2ImageRequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(text2image_ns.model('Text2ImageProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Dauer in Millisekunden'),
        'sub_processors': fields.List(fields.String, description='Verwendete Sub-Prozessoren'),
        'llm_info': fields.Raw(description='LLM-Nutzungsinformationen'),
        'is_from_cache': fields.Boolean(description='Gibt an, ob das Ergebnis aus dem Cache geladen wurde'),
        'cache_key': fields.String(description='Cache-Key (falls aus Cache)')
    })),
    'data': fields.Nested(text2image_ns.model('Text2ImageData', {
        'image_base64': fields.String(description='Base64-kodiertes Bild (erstes Ergebnis)'),
        'image_format': fields.String(description='Bildformat (png)'),
        'size': fields.String(description='Bildgröße (z.B. "1024x1024")'),
        'model': fields.String(description='Verwendetes Modell'),
        'prompt': fields.String(description='Original-Prompt'),
        'seed': fields.Integer(description='Seed für Reproduzierbarkeit (optional)'),
        'images': fields.List(fields.Nested(text2image_ns.model('Text2ImageItem', {
            'image_base64': fields.String(description='Base64-kodiertes Bild'),
            'image_format': fields.String(description='Bildformat'),
            'size': fields.String(description='Bildgröße'),
            'seed': fields.Integer(description='Seed für dieses Bild')
        })), description='Optionale Liste von Bildern für n>1')
    })),
    'error': fields.Nested(text2image_ns.model('Text2ImageError', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})

# Helper-Funktion zum Abrufen des Text2Image-Processors
def get_text2image_processor(process_id: Optional[str] = None) -> Text2ImageProcessor:
    """Get or create text2image processor instance with process ID"""
    return Text2ImageProcessor(
        resource_calculator,
        process_id=process_id or str(uuid.uuid4())
    )

# Text2Image-Generierungs-Endpunkt
@text2image_ns.route('/generate')
class Text2ImageGenerateEndpoint(Resource):
    """Text2Image-Generierungs-Endpunkt."""
    
    @text2image_ns.expect(generate_parser)
    @text2image_ns.response(200, 'Erfolg', text2image_response)
    @text2image_ns.response(400, 'Validierungsfehler', error_model)
    @text2image_ns.doc(description='Generiert ein Bild aus einem Text-Prompt. Unterstützt sowohl multipart/form-data (Formular) als auch application/json. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.')
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Generiert ein Bild aus einem Text-Prompt"""
        try:
            from flask import request
            
            # Unterstütze sowohl Form-Daten als auch JSON
            try:
                # Versuche zuerst Form-Daten (multipart/form-data)
                if request.form:
                    prompt = str(request.form.get('prompt', '') or '')
                    size = str(request.form.get('size', '1024x1024') or '1024x1024')
                    quality = str(request.form.get('quality', 'standard') or 'standard')
                    n_val = request.form.get('n', '1')
                    n = int(n_val) if n_val else 1
                    seed_val = request.form.get('seed')
                    seed = int(seed_val) if seed_val and seed_val.strip() else None
                    seeds_val = request.form.get('seeds')
                    seeds = None
                    if seeds_val and seeds_val.strip():
                        seeds = [int(s.strip()) for s in seeds_val.split(",") if s.strip()]
                    use_cache_str = request.form.get('useCache', 'true')
                    use_cache = use_cache_str.lower() in ('true', '1', 'yes', 'on')
                # Fallback auf JSON
                elif request.is_json:
                    json_data = cast(Dict[str, Any], request.get_json(silent=True) or {})
                    prompt = str(json_data.get('prompt', '') or '')
                    size = str(json_data.get('size', '1024x1024') or '1024x1024')
                    quality = str(json_data.get('quality', 'standard') or 'standard')
                    n = int(json_data.get('n', 1) or 1)
                    seed_val = json_data.get('seed')
                    seed = int(seed_val) if seed_val is not None else None
                    seeds_raw = json_data.get('seeds')
                    seeds = None
                    if isinstance(seeds_raw, list):
                        seeds = [int(s) for s in seeds_raw]
                    elif isinstance(seeds_raw, str):
                        seeds = [int(s.strip()) for s in seeds_raw.split(",") if s.strip()]
                    use_cache = bool(json_data.get('useCache', True))
                # Fallback auf Parser (für Swagger UI)
                else:
                    args_any = generate_parser.parse_args()
                    args = cast(Dict[str, Any], args_any)
                    prompt = str(args.get('prompt', '') or '')
                    size = str(args.get('size', '1024x1024') or '1024x1024')
                    quality = str(args.get('quality', 'standard') or 'standard')
                    n = int(args.get('n', 1) or 1)
                    seed_val = args.get('seed')
                    seed = int(seed_val) if seed_val is not None else None
                    seeds_val = args.get('seeds')
                    seeds = None
                    if isinstance(seeds_val, str) and seeds_val.strip():
                        seeds = [int(s.strip()) for s in seeds_val.split(",") if s.strip()]
                    use_cache = bool(args.get('useCache', True))
            except Exception as parse_error:
                logger.error(f"Fehler beim Parsen der Request-Daten: {parse_error}")
                return {
                    'status': 'error',
                    'error': {
                        'code': 'PARSE_ERROR',
                        'message': 'Fehler beim Parsen der Request-Daten',
                        'details': {
                            'error_type': type(parse_error).__name__,
                            'error_message': str(parse_error)
                        }
                    }
                }, 400
            
            # Validiere Prompt
            if not prompt or not prompt.strip():
                return {
                    'status': 'error',
                    'error': {
                        'code': 'MISSING_PROMPT',
                        'message': 'Prompt darf nicht leer sein',
                        'details': {}
                    }
                }, 400
            
            # Initialisiere Processor
            process_id = str(uuid.uuid4())
            processor: Text2ImageProcessor = get_text2image_processor(process_id)
            
            # Verarbeite die Anfrage
            result: Text2ImageResponse = asyncio.run(processor.process(
                prompt=prompt,
                size=size,
                quality=quality,
                n=n,
                use_cache=use_cache,
                seed=seed,
                seeds=seeds
            ))
            
            # Konvertiere zu Dictionary
            return result.to_dict()
            
        except ProcessingError as e:
            logger.error("Text2Image-Verarbeitungsfehler",
                        error=e,
                        error_type=type(e).__name__)
            return {
                'status': 'error',
                'error': {
                    'code': type(e).__name__,
                    'message': str(e),
                    'details': getattr(e, 'details', None)
                }
            }, 400
            
        except Exception as e:
            logger.error("Unerwarteter Fehler bei der Text2Image-Verarbeitung",
                        error=e,
                        error_type=type(e).__name__)
            return {
                'status': 'error',
                'error': {
                    'code': 'INTERNAL_ERROR',
                    'message': 'Ein unerwarteter Fehler ist aufgetreten',
                    'details': {
                        'error_type': type(e).__name__,
                        'error_message': str(e)
                    }
                }
            }, 500
