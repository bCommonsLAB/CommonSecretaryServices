"""
@fileoverview API Auth - Token-Pruefung fuer alle Routen des /api-Blueprints

@description
Schuetzt den API-Blueprint (src/api/routes/__init__.py). Arbeitspaket AP-01
aus docs/sicherheitsplan-umsetzung.md.

Regeln:
- Fail-closed: Ohne SECRETARY_SERVICE_API_KEY antworten geschuetzte Routen mit 503,
  ausser ALLOW_INSECURE_NO_AUTH=true ist ausdruecklich gesetzt (nur Entwicklung).
  Der Serverstart in src/main.py bricht in diesem Fall vorher ab.
- Token per "Authorization: Bearer <token>" oder "X-Secretary-Api-Key: <token>",
  zeitkonstant verglichen.
- Frei zugaenglich ist nur /api/health/live (Liveness-Probe).
- Swagger (/api/doc, /api/swagger.json) zusaetzlich mit gueltiger Dashboard-Anmeldung
  oder aus SWAGGER_IP_WHITELIST (IPs/CIDR, geprueft gegen request.remote_addr).
- Lesende Aufrufe (GET/HEAD) auf /api/health/ und /api/llm-config/ zusaetzlich mit
  gueltiger Dashboard-Anmeldung, weil die Dashboard-Seiten sie aus dem Browser laden.
- ALLOW_LOCALHOST_NO_AUTH=true erlaubt Anfragen, deren Gegenstelle Loopback ist.
  Host-, X-Forwarded-For- und X-Real-IP-Header werden dafuer NICHT ausgewertet;
  Forwarded-Header wirken nur ueber ProxyFix mit TRUSTED_PROXY_COUNT > 0.

@module api.auth
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple, cast

from flask import request
from flask.typing import ResponseReturnValue

from src.core.security import (
    constant_time_equals,
    env_flag,
    env_str,
    insecure_no_auth_allowed,
    ip_in_networks,
    is_loopback,
    parse_ip_networks,
)
from src.utils.logger import get_logger

_auth_logger = get_logger(process_id="api-auth", processor_name="auth")

PUBLIC_PATHS = ("/api/health/live",)
DOC_PREFIXES = ("/api/doc", "/api/swagger.json")
DASHBOARD_READABLE_PREFIXES = ("/api/health/", "/api/llm-config/")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_warned: set[str] = set()


def _warn_once(key: str, message: str, **kwargs: Any) -> None:
    if key in _warned:
        return
    _warned.add(key)
    try:
        _auth_logger.warning(message, **kwargs)
    except Exception:
        pass


def service_token() -> Optional[str]:
    """Der konfigurierte Service-Token oder None."""
    return env_str("SECRETARY_SERVICE_API_KEY")


def swagger_whitelist_raw() -> Optional[str]:
    """SWAGGER_IP_WHITELIST, ersatzweise der alte Name ALLOW_SWAGGER_WHITELIST (veraltet)."""
    new_value = env_str("SWAGGER_IP_WHITELIST")
    if new_value:
        return new_value
    old_value = env_str("ALLOW_SWAGGER_WHITELIST")
    if old_value:
        _warn_once(
            "old-whitelist-name",
            "ALLOW_SWAGGER_WHITELIST ist veraltet; bitte SWAGGER_IP_WHITELIST verwenden. "
            "Die Whitelist gilt nur noch fuer /api/doc und /api/swagger.json.",
        )
    return old_value


def extract_token() -> str:
    """Token aus Authorization: Bearer oder X-Secretary-Api-Key."""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.headers.get("X-Secretary-Api-Key", "").strip()


def _path_matches(path: str, prefixes: Tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p) for p in prefixes)


def is_public_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in PUBLIC_PATHS


def _dashboard_user_present() -> bool:
    """Gueltige Dashboard-Anmeldung (Session, Basic oder Forward) fuer diesen Request?"""
    try:
        from src.dashboard.auth import current_dashboard_user

        return current_dashboard_user() is not None
    except Exception:
        return False


def _dashboard_challenge() -> Optional[ResponseReturnValue]:
    """Swagger im Browser: zur Dashboard-Anmeldung fuehren, wenn eine eingerichtet ist."""
    try:
        from src.dashboard.auth import LOCKED, _state, challenge_response

        state = _state()
        if state is None or state.problems or state.mode in (LOCKED, "off"):
            return None
        return cast(ResponseReturnValue, challenge_response(state))
    except Exception:
        return None


def _error(code: str, message: str, status: int) -> ResponseReturnValue:
    return ({"status": "error", "error": {"code": code, "message": message}}, status)


def check_api_request() -> Optional[ResponseReturnValue]:
    """
    before_request-Pruefung fuer den API-Blueprint.

    Returns:
        None, wenn der Request weiterlaufen darf, sonst eine Fehlerantwort.
    """
    path = request.path or ""
    method = (request.method or "GET").upper()

    if method == "OPTIONS" or is_public_path(path):
        return None

    remote_addr = request.remote_addr or ""

    if env_flag("ALLOW_LOCALHOST_NO_AUTH") and is_loopback(remote_addr):
        _log_decision("allow_localhost", path=path, remote_addr=remote_addr)
        return None

    token = service_token()
    presented = extract_token()
    if token and constant_time_equals(presented, token):
        _log_decision("token_valid", path=path)
        return None

    is_doc = _path_matches(path, DOC_PREFIXES)
    if is_doc and ip_in_networks(remote_addr, parse_ip_networks(swagger_whitelist_raw())):
        _log_decision("allow_swagger_whitelist", path=path, remote_addr=remote_addr)
        return None

    if method in _SAFE_METHODS and (is_doc or _path_matches(path, DASHBOARD_READABLE_PREFIXES)):
        if _dashboard_user_present():
            _log_decision("allow_dashboard_user", path=path)
            return None
        if is_doc:
            challenge = _dashboard_challenge()
            if challenge is not None:
                return challenge

    if not token:
        if insecure_no_auth_allowed():
            _warn_once(
                "insecure-no-auth",
                "API laeuft OHNE Token-Pruefung (ALLOW_INSECURE_NO_AUTH=true). Nur fuer lokale Entwicklung.",
            )
            return None
        _warn_once(
            "no-token",
            "SECRETARY_SERVICE_API_KEY ist nicht gesetzt; geschuetzte API-Routen antworten mit 503.",
        )
        return _error(
            "SERVICE_TOKEN_NOT_CONFIGURED",
            "Der Dienst ist nicht konfiguriert: SECRETARY_SERVICE_API_KEY fehlt.",
            503,
        )

    try:
        _auth_logger.warning(
            "Request abgewiesen (401)",
            method=method,
            path=path,
            remote_addr=remote_addr,
            token_present=bool(presented),
            user_agent=request.headers.get("User-Agent", ""),
        )
    except Exception:
        pass
    return _error("UNAUTHORIZED", "Invalid or missing service token", 401)


def _log_decision(reason: str, **kwargs: Any) -> None:
    if not env_flag("AUTH_LOG_DECISIONS"):
        return
    try:
        _auth_logger.info(f"Auth-Decision: {reason}", method=request.method, **kwargs)
    except Exception:
        pass


def api_security_problems() -> List[str]:
    """Konfigurationsprobleme, die einen Serverstart verhindern sollen."""
    problems: List[str] = []
    if not service_token() and not insecure_no_auth_allowed():
        problems.append(
            "SECRETARY_SERVICE_API_KEY ist nicht gesetzt. Zufallswert erzeugen, z. B. `openssl rand -hex 32`. "
            "Nur fuer lokale Entwicklung: ALLOW_INSECURE_NO_AUTH=true."
        )
    return problems


def api_security_warnings() -> List[str]:
    """Hinweise, die den Start nicht verhindern, aber im Log stehen sollen."""
    warnings: List[str] = []
    token = service_token()
    if token and len(token) < 32:
        warnings.append("SECRETARY_SERVICE_API_KEY ist kuerzer als 32 Zeichen; empfohlen: `openssl rand -hex 32`.")
    if insecure_no_auth_allowed():
        warnings.append("ALLOW_INSECURE_NO_AUTH=true: API und Dashboard koennen ohne Anmeldung laufen. Nur lokal verwenden.")
    if env_flag("ALLOW_LOCALHOST_NO_AUTH"):
        warnings.append("ALLOW_LOCALHOST_NO_AUTH=true: Anfragen von Loopback-Adressen brauchen keinen Token.")
    return warnings


def api_security_summary() -> dict[str, Any]:
    """Zusammenfassung fuer das Startup-Log, ohne Geheimnisse und ohne Rohwerte."""
    return {
        "service_token_present": bool(service_token()),
        "allow_insecure_no_auth": insecure_no_auth_allowed(),
        "allow_localhost_no_auth": env_flag("ALLOW_LOCALHOST_NO_AUTH"),
        "swagger_whitelist_entries": len(parse_ip_networks(swagger_whitelist_raw())),
        "trusted_proxy_count": os.environ.get("TRUSTED_PROXY_COUNT", "0"),
    }
