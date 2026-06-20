"""
@fileoverview Health API Routes - Flask-RESTX endpoints for LLM availability checks

@description
Stellt Health-Check-Endpunkte bereit, mit denen ein Client *vor* dem Aufruf
eines Endpoints prüfen kann, ob die zugrunde liegende LLM-Operation gerade
verfügbar ist. Geprüft werden je Use-Case der konfigurierte Provider/Modell
(MongoDB-first), Erreichbarkeit/Auth und – bei OpenRouter – das Restguthaben.

Endpunkte sind teilweise kaskadierend; ``/endpoint/<name>`` aggregiert daher die
transitive Hülle der benötigten Use-Cases.

Endpoints:
- GET /api/health/live                  - Liveness (Prozess lebt)
- GET /api/health/                       - Übersicht aller Use-Cases + Endpunkte
- GET /api/health/use-case/<use_case>    - Status eines einzelnen Use-Cases
- GET /api/health/endpoint/<endpoint>    - Status eines (kaskadierenden) Endpoints

Hinweis: ``/api/health*`` ist in der Auth-Middleware ausgenommen (kein Token
nötig), siehe src/api/routes/__init__.py.

@module api.routes.health_routes

@exports
- health_ns: Namespace - Flask-RESTX namespace für Health-Endpunkte
"""

from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Union

from flask_restx import Namespace, Resource  # type: ignore

from src.core.llm.health import LLMHealthService, KNOWN_ENDPOINTS
from src.core.llm.use_cases import UseCase
from src.utils.logger import get_logger

logger = get_logger(process_id="health-api")

# Namespace für Health-Checks
health_ns = Namespace(
    "health",
    description="Verfügbarkeits-Checks für LLM-Operationen und Endpunkte",
)

# Ein gemeinsamer Service (hält den TTL-Cache der Probe-Ergebnisse).
_service = LLMHealthService()


@health_ns.route("/live")  # type: ignore
class LiveEndpoint(Resource):
    @health_ns.doc(description="Liveness-Probe: ist der Prozess erreichbar? (für Docker/k8s)")  # type: ignore
    def get(self) -> Dict[str, Any]:
        """Liveness-Probe – antwortet immer mit 200, solange der Prozess lebt."""
        return {
            "status": "alive",
            "service": "common-secretary-services",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@health_ns.route("/")  # type: ignore
class HealthOverviewEndpoint(Resource):
    @health_ns.doc(description="Übersicht: Status aller Use-Cases und (kaskadierender) Endpunkte")  # type: ignore
    def get(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        """Aggregierter Health-Status aller LLM-Use-Cases und Endpunkte."""
        try:
            return _service.check_all()
        except Exception as exc:
            logger.error(f"Health-Overview fehlgeschlagen: {exc}")
            return {"status": "unknown", "error": str(exc)}, 500


@health_ns.route("/use-case/<string:use_case>")  # type: ignore
class UseCaseHealthEndpoint(Resource):
    @health_ns.doc(description="Verfügbarkeit eines einzelnen Use-Cases (Pre-Flight)")  # type: ignore
    def get(self, use_case: str) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        """Health-Status eines einzelnen Use-Cases."""
        try:
            UseCase(use_case)
        except ValueError:
            return {
                "status": "unknown",
                "error": f"Unbekannter Use-Case '{use_case}'.",
                "valid_use_cases": [u.value for u in UseCase],
            }, 404
        try:
            return _service.check_use_case(use_case)
        except Exception as exc:
            logger.error(f"Health-Check (use-case={use_case}) fehlgeschlagen: {exc}")
            return {"status": "unknown", "use_case": use_case, "error": str(exc)}, 500


@health_ns.route("/endpoint/<string:endpoint>")  # type: ignore
class EndpointHealthEndpoint(Resource):
    @health_ns.doc(description="Verfügbarkeit eines (kaskadierenden) Endpoints (Pre-Flight)")  # type: ignore
    def get(self, endpoint: str) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        """Health-Status eines Endpoints inkl. aller kaskadierend genutzten Use-Cases."""
        try:
            result = _service.check_endpoint(endpoint)
            if result.get("status") == "unknown" and endpoint not in KNOWN_ENDPOINTS:
                return result, 404
            return result
        except Exception as exc:
            logger.error(f"Health-Check (endpoint={endpoint}) fehlgeschlagen: {exc}")
            return {"status": "unknown", "endpoint": endpoint, "error": str(exc)}, 500
