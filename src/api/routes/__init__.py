"""
API-Routen für die verschiedenen Prozessoren.
Diese Datei organisiert alle API-Routen in separate Module pro Prozessor.
"""
# pyright: reportUnusedFunction=false
from flask import Blueprint, request
from flask.typing import ResponseReturnValue
import os
from flask_restx import Api, Namespace, Resource  # type: ignore

# Erstelle den Haupt-API-Blueprint
blueprint = Blueprint('api', __name__)

# Erstelle die API mit dem Blueprint
api = Api(
    blueprint,
    title='Common Secretary Services API',
    version='1.0',
    description='API für die Verarbeitung von verschiedenen Medientypen',
    doc='/doc'  # Swagger-UI unter /api/doc verfügbar machen
)

# Middleware: SECRETARY_SERVICE_API_KEY Check für alle /api-Requests
_SERVICE_TOKEN = os.environ.get('SECRETARY_SERVICE_API_KEY')

@blueprint.before_request
def _check_service_token() -> ResponseReturnValue | None:
    # Ausnahmen erlauben
    exempt_paths = {'/api/doc', '/api/swagger.json', '/api/health'}
    path = request.path
    if any(path.startswith(p) for p in exempt_paths):
        return None
    # Nur prüfen, wenn ein Token konfiguriert ist
    if not _SERVICE_TOKEN:
        return None
    auth = request.headers.get('Authorization', '')
    x_token = request.headers.get('X-Secretary-Api-Key', '')
    token = ''
    if auth.lower().startswith('bearer '):
        token = auth.split(' ', 1)[1].strip()
    elif x_token:
        token = x_token.strip()
    if token != _SERVICE_TOKEN:
        # Flask before_request kann Response oder None zurückgeben; hier JSON
        return ({'status': 'error', 'error': {'code': 'UNAUTHORIZED', 'message': 'Invalid or missing service token'}}, 401)
    return None

# Importiere Namespaces aus den Modulen
from .audio_routes import audio_ns
from .video_routes import video_ns
from .session_routes import session_ns
from .common_routes import common_ns, SamplesEndpoint, SampleFileEndpoint
from .transformer_routes import transformer_ns
from .event_job_routes import event_job_ns
from .track_routes import track_ns
from .event_routes import event_ns
from .pdf_routes import pdf_ns
from .imageocr_routes import imageocr_ns
from .story_routes import story_ns
from .secretary_job_routes import secretary_ns

# Registriere alle Namespaces bei der API
api.add_namespace(audio_ns, path='/audio')  # type: ignore
api.add_namespace(video_ns, path='/video')  # type: ignore
api.add_namespace(session_ns, path='/session')  # type: ignore
api.add_namespace(common_ns, path='/common')  # type: ignore
api.add_namespace(transformer_ns, path='/transformer')  # type: ignore
api.add_namespace(event_job_ns, path='/event-job')  # type: ignore
api.add_namespace(track_ns, path='/tracks')  # type: ignore
api.add_namespace(event_ns, path='/events')  # type: ignore
api.add_namespace(pdf_ns, path='/pdf')  # type: ignore
api.add_namespace(imageocr_ns, path='/imageocr')  # type: ignore
api.add_namespace(story_ns, path='/story')  # type: ignore
api.add_namespace(secretary_ns, path='/jobs')  # type: ignore

# Root-Namespace für die API-Root-Seite
root_ns: Namespace = api.namespace('', description='Root Namespace')  # type: ignore

# Registriere die Samples-Endpoints direkt unter /api/samples für Kompatibilität mit der alten API
root_ns.add_resource(SamplesEndpoint, '/samples')  # type: ignore
root_ns.add_resource(SampleFileEndpoint, '/samples/<string:filename>')  # type: ignore

# Home-Endpoint - exakt wie in der alten routes.py
@root_ns.route('/')  # type: ignore
class HomeEndpoint(Resource):
    @root_ns.doc(description='API Willkommensseite')  # type: ignore
    def get(self):
        """API Willkommensseite"""
        return {'message': 'Welcome to the Processing Service API!'}

