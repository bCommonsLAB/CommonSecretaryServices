"""
@fileoverview API Route Registration - Central API route registration and authentication

@description
API routes for various processors. This file organizes all API routes into separate
modules per processor and provides authentication middleware.

Main functionality:
- Creates Flask-RESTX API instance with Swagger UI support
- Registers all processor-specific route modules
- Registers the authentication middleware (rules in src/api/auth.py)

Authentication (see src/api/auth.py):
All API requests require a valid API key, fail-closed without configured key:
- Header: Authorization: Bearer <token>
- Alternative header: X-Secretary-Api-Key: <token>
- Public: /api/health/live only
- Swagger (/api/doc, /api/swagger.json): token, dashboard login or SWAGGER_IP_WHITELIST

@module api.routes

@exports
- blueprint: Blueprint - Flask blueprint for API routes
- api: Api - Flask-RESTX API instance with Swagger UI

@usedIn
- src.dashboard.app: Registers api blueprint under /api
- src.api.__init__.py: Imports blueprint for app factory

@dependencies
- External: flask - Flask web framework
- External: flask_restx - RESTX for API documentation and Swagger UI
- Internal: src.utils.logger - Logging system
- Internal: src.api.auth - Token check
"""
# pyright: reportUnusedFunction=false
from flask import Blueprint, request
from flask.typing import ResponseReturnValue
from flask_restx import Api, Namespace, Resource  # type: ignore
from typing import Any

# Erstelle den Haupt-API-Blueprint
blueprint = Blueprint('api', __name__)

# Swagger/OpenAPI werden im Browser häufig aggressiv gecached.
# Das führt dazu, dass neue Parameter im Swagger-UI nicht auftauchen, obwohl sie serverseitig existieren.
@blueprint.after_request
def _disable_swagger_cache(response: Any) -> Any:
    try:
        path = request.path or ""
        if path.startswith("/api/swagger.json") or path.startswith("/api/doc"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    except Exception:
        pass
    return response

# Erstelle die API mit dem Blueprint
api = Api(
    blueprint,
    title='Common Secretary Services API',
    version='1.0',
    description='API für die Verarbeitung von verschiedenen Medientypen',
    doc='/doc'  # Swagger-UI unter /api/doc verfügbar machen
)

# Middleware: Token-Pruefung fuer alle /api-Requests (Arbeitspaket AP-01).
# Die Regeln stehen in src/api/auth.py.
from src.api.auth import check_api_request


@blueprint.before_request
def _check_service_token() -> ResponseReturnValue | None:
    return check_api_request()

# Importiere Namespaces aus den Modulen
from .audio_routes import audio_ns
# Haengt POST /audio/process-diarized an denselben Namespace (Import genuegt)
from . import audio_diarized_routes  # noqa: F401
from .video_routes import video_ns
from .session_routes import session_ns
from .common_routes import common_ns, SamplesEndpoint, SampleFileEndpoint
from .transformer_routes import transformer_ns
from .track_routes import track_ns
from .event_routes import event_ns
from .pdf_routes import pdf_ns
from .office_routes import office_ns
from .imageocr_routes import imageocr_ns
from .story_routes import story_ns
from .secretary_job_routes import secretary_ns
from .llm_config_routes import llm_config
from .rag_routes import rag_ns
from .text2image_routes import text2image_ns
from .image_analyzer_routes import image_analyzer_ns
from .health_routes import health_ns
from .realtime_routes import realtime_ns
from .booklet_routes import booklet_ns
from .transcript_routes import transcript_ns
from .media_routes import media_ns

# Registriere alle Namespaces bei der API
api.add_namespace(audio_ns, path='/audio')  # type: ignore
api.add_namespace(video_ns, path='/video')  # type: ignore
api.add_namespace(session_ns, path='/session')  # type: ignore
api.add_namespace(common_ns, path='/common')  # type: ignore
api.add_namespace(transformer_ns, path='/transformer')  # type: ignore
api.add_namespace(track_ns, path='/tracks')  # type: ignore
api.add_namespace(event_ns, path='/events')  # type: ignore
api.add_namespace(pdf_ns, path='/pdf')  # type: ignore
api.add_namespace(office_ns, path='/office')  # type: ignore
api.add_namespace(imageocr_ns, path='/imageocr')  # type: ignore
api.add_namespace(story_ns, path='/story')  # type: ignore
api.add_namespace(secretary_ns, path='/jobs')  # type: ignore
api.add_namespace(rag_ns, path='/rag')  # type: ignore
api.add_namespace(booklet_ns, path='/booklet')  # type: ignore
api.add_namespace(text2image_ns, path='/text2image')  # type: ignore
api.add_namespace(image_analyzer_ns, path='/image-analyzer')  # type: ignore
api.add_namespace(health_ns, path='/health')  # type: ignore
api.add_namespace(realtime_ns, path='/realtime')  # type: ignore
api.add_namespace(transcript_ns, path='/transcript')  # type: ignore
api.add_namespace(media_ns, path='/media')  # type: ignore

# Root-Namespace für die API-Root-Seite
root_ns: Namespace = api.namespace('', description='Root Namespace')  # type: ignore

# Registriere die Samples-Endpoints direkt unter /api/samples für Kompatibilität mit der alten API
root_ns.add_resource(SamplesEndpoint, '/samples')  # type: ignore
root_ns.add_resource(SampleFileEndpoint, '/samples/<string:filename>')  # type: ignore

# Registriere LLM-Config Blueprint
blueprint.register_blueprint(llm_config)

# Home-Endpoint - exakt wie in der alten routes.py
@root_ns.route('/')  # type: ignore
class HomeEndpoint(Resource):
    @root_ns.doc(description='API Willkommensseite')  # type: ignore
    def get(self):
        """API Willkommensseite"""
        return {'message': 'Welcome to the Processing Service API!'}

