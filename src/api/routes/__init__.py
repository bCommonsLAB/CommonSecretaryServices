"""
API-Routen für die verschiedenen Prozessoren.
Diese Datei organisiert alle API-Routen in separate Module pro Prozessor.
"""
from flask import Blueprint
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

# Importiere Namespaces aus den Modulen
from .audio_routes import audio_ns
from .video_routes import video_ns
from .session_routes import session_ns
from .common_routes import common_ns, SamplesEndpoint, SampleFileEndpoint
from .transformer_routes import transformer_ns
from .event_job_routes import event_job_ns
from .track_routes import track_ns
from .pdf_routes import pdf_ns
from .imageocr_routes import imageocr_ns

# Registriere alle Namespaces bei der API
api.add_namespace(audio_ns, path='/audio')  # type: ignore
api.add_namespace(video_ns, path='/video')  # type: ignore
api.add_namespace(session_ns, path='/session')  # type: ignore
api.add_namespace(common_ns, path='/common')  # type: ignore
api.add_namespace(transformer_ns, path='/transformer')  # type: ignore
api.add_namespace(event_job_ns, path='/event-job')  # type: ignore
api.add_namespace(track_ns, path='/tracks')  # type: ignore
api.add_namespace(pdf_ns, path='/pdf')  # type: ignore
api.add_namespace(imageocr_ns, path='/imageocr')  # type: ignore

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

