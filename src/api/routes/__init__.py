"""
API-Routen für die verschiedenen Prozessoren.
Diese Datei organisiert alle API-Routen in separate Module pro Prozessor.
"""
# pyright: reportUnusedFunction=false
from flask import Blueprint, request
from flask.typing import ResponseReturnValue
import os
from flask_restx import Api, Namespace, Resource  # type: ignore
from typing import Any
from src.utils.logger import get_logger

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
_ALLOW_LOCALHOST_NO_AUTH = os.environ.get('ALLOW_LOCALHOST_NO_AUTH', 'false').lower() in {'1', 'true', 'yes'}
_ALLOW_SWAGGER_WHITELIST = os.environ.get('ALLOW_SWAGGER_WHITELIST', '')
_AUTH_LOG_DECISIONS = os.environ.get('AUTH_LOG_DECISIONS', 'false').lower() in {'1', 'true', 'yes'}

def _parse_ip_whitelist(raw_value: str) -> set[str]:
    """
    Parsed eine komma- oder leerzeichen-separierte Liste von IPs/Hosts.
    - Leere Einträge werden ignoriert
    - Trim von Whitespace
    - Gibt ein Set für O(1)-Lookup zurück
    """
    try:
        separators = [',', ';', ' ']  # erlaubte Trenner
        normalized = raw_value
        for sep in separators[:-1]:
            normalized = normalized.replace(sep, ' ')
        parts = [p.strip() for p in normalized.split(' ') if p.strip()]
        return set(parts)
    except Exception:
        return set()

_WHITELISTED_IPS: set[str] = _parse_ip_whitelist(_ALLOW_SWAGGER_WHITELIST)

# Initialisiere Logger für Auth-Middleware
_auth_logger = get_logger(process_id="api-auth", processor_name="auth")

def _log_auth_decision(reason: str, **kwargs: Any) -> None:
    """Loggt Auth-Entscheidungen, wenn aktiviert."""
    if not _AUTH_LOG_DECISIONS:
        return
    try:
        _auth_logger.info(f"Auth-Decision: {reason}", **kwargs)
    except Exception:
        pass

@blueprint.before_request
def _check_service_token() -> ResponseReturnValue | None:
    # Ausnahmen erlauben
    exempt_paths = {'/api/doc', '/api/swagger.json', '/api/health'}
    path = request.path
    if any(path.startswith(p) for p in exempt_paths):
        _log_auth_decision(
            reason="exempt_path",
            method=request.method,
            path=path,
            exempt=True
        )
        return None
    # Localhost-Ausnahme erlauben, z. B. fr Swagger-Tests lokal
    # Nur aktiv, wenn Env-Flag gesetzt ist
    if _ALLOW_LOCALHOST_NO_AUTH:
        try:
            remote_addr = request.remote_addr or ''
            host = request.host.split(':', 1)[0] if request.host else ''
        except Exception:
            remote_addr = ''
            host = ''
        if remote_addr in {'127.0.0.1', '::1'} or host in {'localhost', '127.0.0.1', '::1'}:
            _log_auth_decision(
                reason="allow_localhost",
                method=request.method,
                path=path,
                remote_addr=remote_addr,
                host=host,
                allow_localhost=_ALLOW_LOCALHOST_NO_AUTH
            )
            return None
    # Whitelist-Ausnahme: erlaubte IPs/Hosts ohne Token, z. B. fr Swagger in Prod
    if _WHITELISTED_IPS:
        remote_addr: str = ''
        host: str = ''
        try:
            remote_addr = request.remote_addr or ''
            host = request.host.split(':', 1)[0] if request.host else ''
            # Berücksichtige Forwarded-Header (typisch hinter Reverse Proxies)
            x_forwarded_for: str = request.headers.get('X-Forwarded-For', '')
            x_real_ip: str = request.headers.get('X-Real-IP', '')
            forwarded_ip: str = ''
            if x_forwarded_for:
                # Erster Eintrag ist der ursprüngliche Client
                forwarded_ip = x_forwarded_for.split(',')[0].strip()
            candidate_ips: set[str] = {ip for ip in [remote_addr, host, forwarded_ip, x_real_ip] if ip}
        except Exception:
            candidate_ips = set()
        if candidate_ips & _WHITELISTED_IPS:
            _log_auth_decision(
                reason="allow_whitelist",
                method=request.method,
                path=path,
                remote_addr=remote_addr,
                host=host,
                x_forwarded_for=request.headers.get('X-Forwarded-For', ''),
                x_real_ip=request.headers.get('X-Real-IP', ''),
                ip_candidates=sorted(candidate_ips),
                whitelist=sorted(_WHITELISTED_IPS)
            )
            return None
    # Nur prüfen, wenn ein Token konfiguriert ist
    if not _SERVICE_TOKEN:
        _log_auth_decision(
            reason="no_service_token_configured",
            method=request.method,
            path=path
        )
        return None
    auth = request.headers.get('Authorization', '')
    x_token = request.headers.get('X-Secretary-Api-Key', '')
    token = ''
    if auth.lower().startswith('bearer '):
        token = auth.split(' ', 1)[1].strip()
    elif x_token:
        token = x_token.strip()
    if token != _SERVICE_TOKEN:
        # Abgewiesene Anfrage loggen (ohne Tokeninhalte)
        try:
            _path = path if 'path' in locals() else request.path
            remote_addr_log: str = request.remote_addr or ''
            host_log: str = request.host.split(':', 1)[0] if request.host else ''
            xff_log: str = request.headers.get('X-Forwarded-For', '')
            xreal_log: str = request.headers.get('X-Real-IP', '')
            forwarded_ip_log: str = xff_log.split(',')[0].strip() if xff_log else ''
            candidate_ips_log: list[str] = [ip for ip in [remote_addr_log, host_log, forwarded_ip_log, xreal_log] if ip]
            matched_whitelist: bool = any(ip in _WHITELISTED_IPS for ip in candidate_ips_log)
            _auth_logger.warning(
                "Request abgewiesen (401)",
                method=request.method,
                path=_path,
                remote_addr=remote_addr_log,
                host=host_log,
                x_forwarded_for=xff_log,
                x_real_ip=xreal_log,
                ip_candidates=candidate_ips_log,
                whitelist=list(_WHITELISTED_IPS),
                matched_whitelist=matched_whitelist,
                allow_localhost=_ALLOW_LOCALHOST_NO_AUTH,
                token_present=bool(token),
                user_agent=request.headers.get('User-Agent', '')
            )
        except Exception:
            pass
        # Flask before_request kann Response oder None zurückgeben; hier JSON
        return ({'status': 'error', 'error': {'code': 'UNAUTHORIZED', 'message': 'Invalid or missing service token'}}, 401)
    else:
        _log_auth_decision(
            reason="token_valid",
            method=request.method,
            path=path,
            token_present=bool(token)
        )
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

