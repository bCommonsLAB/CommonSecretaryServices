"""
@fileoverview Dashboard Auth - Anmeldung fuer alle Nicht-API-Seiten (Dashboard, Logs, LLM-Config, Docs)

@description
Arbeitspaket AP-02 aus docs/sicherheitsplan-umsetzung.md. Die Anwendung schuetzt sich
selbst; es wird keine Proxy-Konfiguration vorausgesetzt.

Modi (DASHBOARD_AUTH_MODE):
- oidc:    Anmeldung ueber einen OpenID-Connect-Anbieter (vorgesehen: eigene Nextcloud
           mit der App "OIDC Identity Provider"), Authorization Code Flow mit PKCE.
- basic:   HTTP Basic Auth mit DASHBOARD_USER und DASHBOARD_PASSWORD_HASH (Notzugang,
           lokale Installationen, Rechner ohne Zugang zur Nextcloud).
- forward: Benutzer aus einem Header eines vorgeschalteten Proxys (nur mit
           TRUSTED_PROXY_COUNT > 0; optionale Variante, siehe AP-20).
- off:     keine Anmeldung, nur zusammen mit ALLOW_INSECURE_NO_AUTH=true.
Ohne DASHBOARD_AUTH_MODE: oidc, wenn OIDC_* gesetzt ist; basic, wenn DASHBOARD_USER
gesetzt ist; sonst ist das Dashboard GESPERRT (503 mit Hinweisseite).

Die API (/api-Blueprint) wird hier nicht geprueft; dafuer ist src/api/auth.py zustaendig.

Kommandozeile zum Erzeugen eines Passwort-Hashes fuer den Basic-Modus:
    python -m src.dashboard.auth hash-password

@module dashboard.auth
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional, cast
from urllib.parse import urlencode

from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    g,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
)
from werkzeug.security import check_password_hash

from src.core.security import (
    constant_time_equals,
    env_str,
    insecure_no_auth_allowed,
    trusted_proxy_count,
)
from src.utils.logger import get_logger

logger = get_logger(process_id="dashboard-auth", processor_name="auth")

EXTENSION_KEY = "secretary_dashboard_auth"
SESSION_USER_KEY = "dashboard_user"
SESSION_NEXT_KEY = "dashboard_next"
OIDC_CLIENT_NAME = "nextcloud"
MODES = ("oidc", "basic", "forward", "off")
LOCKED = "locked"
_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Blueprints, die nicht vom Dashboard-Schutz erfasst werden:
# api (eigene Token-Pruefung), restx_doc (nur statische Swagger-Dateien), dashboard_auth (Login selbst)
_EXEMPT_BLUEPRINTS = {"api", "restx_doc", "dashboard_auth"}


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

@dataclass
class DashboardAuthState:
    mode: str
    problems: List[str] = field(default_factory=list)
    public_base_url: Optional[str] = None
    session_hours: int = 12
    oauth: Any = None


def resolve_mode() -> str:
    """Bestimmt den Modus aus DASHBOARD_AUTH_MODE oder den gesetzten Variablen."""
    raw = env_str("DASHBOARD_AUTH_MODE")
    if raw:
        return raw.lower()
    if env_str("OIDC_CLIENT_ID") or env_str("OIDC_ISSUER") or env_str("OIDC_DISCOVERY_URL"):
        return "oidc"
    if env_str("DASHBOARD_USER"):
        return "basic"
    return LOCKED


def public_base_url() -> Optional[str]:
    value = env_str("PUBLIC_BASE_URL")
    return value.rstrip("/") if value else None


def _session_hours() -> int:
    raw = env_str("DASHBOARD_SESSION_HOURS")
    try:
        return max(1, int(raw)) if raw else 12
    except ValueError:
        return 12


def _split_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


def dashboard_security_problems(mode: Optional[str] = None) -> List[str]:
    """Konfigurationsfehler, die das Dashboard sperren und den Serverstart verhindern."""
    mode = mode or resolve_mode()
    problems: List[str] = []
    if mode == LOCKED:
        return problems
    if mode not in MODES:
        return [f"DASHBOARD_AUTH_MODE='{mode}' ist unbekannt (erlaubt: {', '.join(MODES)})."]

    secret = env_str("FLASK_SECRET_KEY")
    if mode in ("oidc", "basic", "forward"):
        if not secret:
            problems.append("FLASK_SECRET_KEY fehlt (Zufallswert je Installation, z. B. `openssl rand -hex 32`).")
        elif len(secret) < 32:
            problems.append("FLASK_SECRET_KEY ist zu kurz (mindestens 32 Zeichen).")

    if mode == "off" and not insecure_no_auth_allowed():
        problems.append("DASHBOARD_AUTH_MODE=off ist nur zusammen mit ALLOW_INSECURE_NO_AUTH=true erlaubt.")

    if mode == "forward" and trusted_proxy_count() <= 0:
        problems.append("DASHBOARD_AUTH_MODE=forward setzt TRUSTED_PROXY_COUNT > 0 voraus (Header nur vom eigenen Proxy).")

    if mode == "basic":
        if not env_str("DASHBOARD_USER"):
            problems.append("DASHBOARD_USER fehlt.")
        pw_hash = env_str("DASHBOARD_PASSWORD_HASH")
        if not pw_hash:
            problems.append("DASHBOARD_PASSWORD_HASH fehlt (erzeugen mit `python -m src.dashboard.auth hash-password`).")
        elif ":" not in pw_hash or "$" not in pw_hash:
            problems.append("DASHBOARD_PASSWORD_HASH hat kein gueltiges Format (Werkzeug-Hash, z. B. 'scrypt:...$...$...').")

    if mode == "oidc":
        for var in ("OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
            if not env_str(var):
                problems.append(f"{var} fehlt.")
        if not (env_str("OIDC_ISSUER") or env_str("OIDC_DISCOVERY_URL")):
            problems.append("OIDC_ISSUER oder OIDC_DISCOVERY_URL fehlt (Adresse der Nextcloud).")
        base = public_base_url()
        if not base:
            problems.append("PUBLIC_BASE_URL fehlt (oeffentliche Adresse dieser Installation, daraus entsteht die Ruecksprungadresse).")
        elif not base.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            problems.append("PUBLIC_BASE_URL muss mit https:// beginnen (http nur fuer localhost).")
        if not (env_str("DASHBOARD_REQUIRED_GROUP") or env_str("DASHBOARD_ALLOWED_USERS")):
            problems.append(
                "DASHBOARD_REQUIRED_GROUP oder DASHBOARD_ALLOWED_USERS fehlt; sonst kaeme jedes Konto des Anbieters ins Dashboard."
            )
    return problems


def dashboard_security_summary() -> Dict[str, Any]:
    """Zusammenfassung fuer das Startup-Log, ohne Geheimnisse."""
    mode = resolve_mode()
    return {
        "dashboard_auth_mode": mode,
        "dashboard_problems": len(dashboard_security_problems(mode)),
        "public_base_url": public_base_url(),
        "required_group_set": bool(env_str("DASHBOARD_REQUIRED_GROUP")),
        "allowed_users_count": len(_split_list(env_str("DASHBOARD_ALLOWED_USERS"))),
    }


# ---------------------------------------------------------------------------
# Initialisierung
# ---------------------------------------------------------------------------

def _state() -> Optional[DashboardAuthState]:
    try:
        return current_app.extensions.get(EXTENSION_KEY)
    except RuntimeError:
        return None


def init_dashboard_auth(app: Flask) -> DashboardAuthState:
    """
    Aktiviert Dashboard-Anmeldung, CSRF-Schutz und Login-Routen fuer eine Flask-App.

    Muss vor allen anderen before_request-Funktionen der App registriert werden,
    damit nicht angemeldete Requests keine weitere Verarbeitung ausloesen.
    """
    if EXTENSION_KEY in app.extensions:
        return cast(DashboardAuthState, app.extensions[EXTENSION_KEY])

    mode = resolve_mode()
    problems = dashboard_security_problems(mode)
    state = DashboardAuthState(
        mode=mode,
        problems=problems,
        public_base_url=public_base_url(),
        session_hours=_session_hours(),
    )

    secret = env_str("FLASK_SECRET_KEY")
    if secret:
        app.secret_key = secret
    elif mode == "off" and not problems:
        import secrets as _secrets

        app.secret_key = _secrets.token_hex(32)

    base = state.public_base_url or ""
    app.config.update(
        SESSION_COOKIE_NAME="secretary_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=base.startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=state.session_hours),
        WTF_CSRF_CHECK_DEFAULT=False,
        WTF_CSRF_TIME_LIMIT=None,
    )

    from flask_wtf.csrf import CSRFProtect  # type: ignore[import-untyped]

    csrf = CSRFProtect()
    csrf.init_app(app)
    app.extensions["secretary_csrf"] = csrf

    if mode == "oidc" and not problems:
        from authlib.integrations.flask_client import OAuth  # type: ignore[import-untyped]

        oauth = OAuth(app)
        discovery = env_str("OIDC_DISCOVERY_URL") or (
            (env_str("OIDC_ISSUER") or "").rstrip("/") + "/.well-known/openid-configuration"
        )
        oauth.register(
            name=OIDC_CLIENT_NAME,
            client_id=env_str("OIDC_CLIENT_ID"),
            client_secret=env_str("OIDC_CLIENT_SECRET"),
            server_metadata_url=discovery,
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )
        state.oauth = oauth

    app.extensions[EXTENSION_KEY] = state
    app.register_blueprint(_build_auth_blueprint())
    app.before_request_funcs.setdefault(None, []).insert(0, _dashboard_guard)
    app.context_processor(_template_context)

    if problems:
        logger.error("Dashboard gesperrt: Konfiguration unvollstaendig", mode=mode, problems=problems)
    elif mode == LOCKED:
        logger.warning(
            "Dashboard gesperrt: keine Anmeldung konfiguriert (DASHBOARD_AUTH_MODE, OIDC_* oder DASHBOARD_USER setzen)."
        )
    elif mode == "off":
        logger.warning("Dashboard OHNE Anmeldung (DASHBOARD_AUTH_MODE=off). Nur fuer lokale Entwicklung.")
    else:
        logger.info("Dashboard-Anmeldung aktiv", mode=mode)
    return state


# ---------------------------------------------------------------------------
# Wer ist angemeldet?
# ---------------------------------------------------------------------------

def current_dashboard_user() -> Optional[Dict[str, Any]]:
    """Angemeldeter Dashboard-Benutzer fuer den aktuellen Request oder None."""
    if "dashboard_user" in g:
        return cast(Optional[Dict[str, Any]], g.dashboard_user)
    state = _state()
    user: Optional[Dict[str, Any]] = None
    if state is not None and not state.problems:
        if state.mode == "oidc":
            user = _user_from_session(state)
        elif state.mode == "basic":
            user = _user_from_basic()
        elif state.mode == "forward":
            user = _user_from_forward_header()
        elif state.mode == "off":
            user = {"name": "anonymous", "auth": "off", "groups": []}
    g.dashboard_user = user
    return user


def _user_from_session(state: DashboardAuthState) -> Optional[Dict[str, Any]]:
    data = session.get(SESSION_USER_KEY)
    if not isinstance(data, dict):
        return None
    login_at = data.get("login_at")
    if not isinstance(login_at, (int, float)) or time.time() - login_at > state.session_hours * 3600:
        session.pop(SESSION_USER_KEY, None)
        return None
    return data


def _user_from_basic() -> Optional[Dict[str, Any]]:
    auth = request.authorization
    if auth is None or (auth.type or "").lower() != "basic":
        return None
    expected_user = env_str("DASHBOARD_USER")
    pw_hash = env_str("DASHBOARD_PASSWORD_HASH")
    if not expected_user or not pw_hash:
        return None
    user_ok = constant_time_equals(auth.username or "", expected_user)
    try:
        pw_ok = check_password_hash(pw_hash, auth.password or "")
    except Exception:
        pw_ok = False
    if user_ok and pw_ok:
        return {"name": expected_user, "auth": "basic", "groups": []}
    return None


def _user_from_forward_header() -> Optional[Dict[str, Any]]:
    user_header = env_str("DASHBOARD_FORWARD_USER_HEADER") or "X-Auth-Request-User"
    groups_header = env_str("DASHBOARD_FORWARD_GROUPS_HEADER") or "X-Auth-Request-Groups"
    name = (request.headers.get(user_header) or "").strip()
    if not name:
        return None
    groups = _split_list(request.headers.get(groups_header))
    required = env_str("DASHBOARD_REQUIRED_GROUP")
    if required and not _group_match(groups, required):
        return None
    return {"name": name, "auth": "forward", "groups": groups}


def _group_match(groups: List[str], required: str) -> bool:
    wanted = required.casefold()
    return any(str(gname).casefold() == wanted for gname in groups)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

def _is_exempt() -> bool:
    if request.endpoint == "static":
        return True
    blueprints = set(getattr(request, "blueprints", []) or [])
    if blueprints & _EXEMPT_BLUEPRINTS:
        return True
    # Unbekannte Pfade unter /api/ beantwortet die API mit 404, nicht das Dashboard.
    if request.url_rule is None and (request.path or "").startswith("/api/"):
        return True
    return False


def _wants_html() -> bool:
    if request.method != "GET":
        return False
    path = request.path or ""
    is_swagger_page = path == "/api/doc" or path.startswith("/api/doc/")
    if not is_swagger_page and (path.startswith("/api/") or "/api/" in path):
        return False
    accept = request.accept_mimetypes
    return accept.accept_html and accept["text/html"] >= accept["application/json"]


def _dashboard_guard() -> Optional[Any]:
    if _is_exempt():
        return None
    state = _state()
    if state is None:
        return None
    if state.problems or state.mode == LOCKED:
        return _locked_response(state)

    user = current_dashboard_user()
    if user is None:
        return challenge_response(state)

    if request.method in _CSRF_METHODS:
        csrf = current_app.extensions.get("secretary_csrf")
        if csrf is not None:
            csrf.protect()
    return None


def challenge_response(state: Optional[DashboardAuthState] = None) -> Any:
    """Antwort fuer nicht angemeldete Requests, passend zum Modus."""
    state = state or _state()
    if state is None or state.problems or state.mode == LOCKED:
        return _locked_response(state)
    if state.mode == "oidc" and _wants_html():
        next_path = request.full_path if request.query_string else request.path
        return redirect("/auth/login?" + urlencode({"next": _safe_next(next_path)}))
    if state.mode == "basic":
        resp = _message_page(
            "Anmeldung erforderlich",
            "Bitte mit den Zugangsdaten für das Dashboard anmelden.",
            401,
        )
        resp.headers["WWW-Authenticate"] = 'Basic realm="Secretary Dashboard", charset="UTF-8"'
        return resp
    if _wants_html():
        return _message_page("Anmeldung erforderlich", "Bitte zuerst anmelden.", 401)
    return jsonify({"status": "error", "error": {"code": "LOGIN_REQUIRED", "message": "Dashboard-Anmeldung erforderlich"}}), 401


def _locked_response(state: Optional[DashboardAuthState]) -> Any:
    if state is not None and state.problems:
        detail = "Die Anmeldung ist unvollständig konfiguriert. Details stehen im Server-Log."
    else:
        detail = (
            "Für dieses Dashboard ist keine Anmeldung eingerichtet. Setze in der .env dieser Installation "
            "entweder die OIDC-Variablen (OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, PUBLIC_BASE_URL, "
            "DASHBOARD_REQUIRED_GROUP, FLASK_SECRET_KEY) oder für den Notzugang DASHBOARD_USER, "
            "DASHBOARD_PASSWORD_HASH und FLASK_SECRET_KEY. Anleitung: docs/deployment/dashboard-anmeldung.md"
        )
    if _wants_html():
        return _message_page("Dashboard gesperrt", detail, 503)
    return jsonify({"status": "error", "error": {"code": "DASHBOARD_NOT_CONFIGURED", "message": detail}}), 503


def _safe_next(target: Optional[str]) -> str:
    """Nur relative Pfade dieser Anwendung als Weiterleitungsziel (kein Open Redirect)."""
    if not target or not target.startswith("/") or target.startswith("//") or target.startswith("/\\"):
        return "/"
    if target.startswith("/auth/"):
        return "/"
    return target


_MESSAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:64px auto;padding:0 16px;color:#1f2937}
h1{font-size:1.4rem}p{line-height:1.5}a{color:#1565c0}</style></head>
<body><h1>{{ title }}</h1><p>{{ message }}</p>{% if link %}<p><a href="{{ link }}">{{ link_text }}</a></p>{% endif %}</body></html>"""


def _message_page(title: str, message: str, status: int, link: Optional[str] = None, link_text: str = "") -> Response:
    html = render_template_string(_MESSAGE_TEMPLATE, title=title, message=message, link=link, link_text=link_text)
    return Response(html, status=status, mimetype="text/html")


def _template_context() -> Dict[str, Any]:
    state = _state()
    try:
        user = current_dashboard_user()
    except Exception:
        user = None
    return {
        "dashboard_user": user,
        "dashboard_auth_mode": state.mode if state else None,
    }


# ---------------------------------------------------------------------------
# OIDC-Routen
# ---------------------------------------------------------------------------

def _build_auth_blueprint() -> Blueprint:
    bp = Blueprint("dashboard_auth", __name__)

    @bp.route("/auth/login")
    def login() -> Any:
        state = _state()
        if state is None or state.mode != "oidc" or state.problems or state.oauth is None:
            return _message_page("Nicht verfügbar", "Die Anmeldung über OIDC ist nicht eingerichtet.", 404)
        client = state.oauth.create_client(OIDC_CLIENT_NAME)
        try:
            metadata = client.load_server_metadata()
        except Exception as exc:
            logger.error("OIDC-Anbieter nicht erreichbar", error=exc)
            return _message_page(
                "Anmeldedienst nicht erreichbar",
                "Die Nextcloud-Anmeldung ist gerade nicht erreichbar. Notzugang: DASHBOARD_AUTH_MODE=basic.",
                503,
            )
        session[SESSION_NEXT_KEY] = _safe_next(request.args.get("next"))
        redirect_uri = f"{state.public_base_url}/auth/callback"
        return client.authorize_redirect(redirect_uri, scope=_scope_for(metadata))

    @bp.route("/auth/callback")
    def callback() -> Any:
        state = _state()
        if state is None or state.mode != "oidc" or state.problems or state.oauth is None:
            return _message_page("Nicht verfügbar", "Die Anmeldung über OIDC ist nicht eingerichtet.", 404)
        if request.args.get("error"):
            logger.warning("OIDC-Anbieter meldet Fehler", error=request.args.get("error"))
            return _message_page("Anmeldung abgebrochen", "Der Anmeldedienst hat die Anmeldung abgelehnt.", 400,
                                 link="/auth/login", link_text="Erneut anmelden")
        client = state.oauth.create_client(OIDC_CLIENT_NAME)
        try:
            token = client.authorize_access_token()
        except Exception as exc:
            logger.warning("OIDC-Callback ungueltig", error_type=type(exc).__name__, error=str(exc))
            return _message_page("Anmeldung fehlgeschlagen", "Die Antwort des Anmeldedienstes war ungültig.", 400,
                                 link="/auth/login", link_text="Erneut anmelden")

        claims: Dict[str, Any] = dict(token.get("userinfo") or {})
        if not claims:
            logger.warning("OIDC-Callback ohne ID-Token")
            return _message_page("Anmeldung fehlgeschlagen", "Der Anmeldedienst hat kein ID-Token geliefert.", 400)

        groups_claim = env_str("OIDC_GROUPS_CLAIM") or "groups"
        if groups_claim not in claims:
            try:
                extra = client.userinfo(token=token)
                if extra.get("sub") == claims.get("sub"):
                    for key, value in extra.items():
                        claims.setdefault(key, value)
            except Exception as exc:
                logger.info("Userinfo-Endpunkt nicht abrufbar", error=str(exc))

        logger.info("OIDC-Anmeldung: empfangene Claims", claim_names=sorted(claims.keys()))
        user = _user_from_claims(claims, groups_claim)
        if not _oidc_user_allowed(user):
            logger.warning("OIDC-Anmeldung abgewiesen: keine Berechtigung", user=user.get("name"))
            return _message_page("Kein Zugriff", "Dieses Konto ist für das Dashboard nicht freigegeben.", 403)

        next_path = _safe_next(session.get(SESSION_NEXT_KEY))
        session.clear()
        session.permanent = True
        session[SESSION_USER_KEY] = user
        logger.info("OIDC-Anmeldung erfolgreich", user=user.get("name"))
        return redirect(next_path)

    @bp.route("/auth/logout")
    def logout() -> Any:
        state = _state()
        session.clear()
        if state is not None and state.mode == "oidc" and state.oauth is not None and not state.problems:
            try:
                metadata = state.oauth.create_client(OIDC_CLIENT_NAME).load_server_metadata()
                end_session = metadata.get("end_session_endpoint")
            except Exception:
                end_session = None
            if end_session:
                query = urlencode({
                    "client_id": env_str("OIDC_CLIENT_ID") or "",
                    "post_logout_redirect_uri": f"{state.public_base_url}/auth/logged-out",
                })
                return redirect(f"{end_session}?{query}")
            return redirect("/auth/logged-out")
        if state is not None and state.mode == "basic":
            return _message_page("Abmelden", "Bei Basic Auth endet die Anmeldung, wenn der Browser geschlossen wird.", 200)
        logout_url = env_str("DASHBOARD_LOGOUT_URL")
        if state is not None and state.mode == "forward" and logout_url:
            return redirect(logout_url)
        return redirect("/auth/logged-out")

    @bp.route("/auth/logged-out")
    def logged_out() -> Any:
        return _message_page("Abgemeldet", "Du bist vom Dashboard abgemeldet.", 200, link="/", link_text="Erneut anmelden")

    return bp


def _scope_for(metadata: Dict[str, Any]) -> str:
    configured = env_str("OIDC_SCOPES")
    if configured:
        return configured
    scopes = ["openid", "profile", "email"]
    supported = metadata.get("scopes_supported") or []
    if "groups" in supported:
        scopes.append("groups")
    return " ".join(scopes)


def _user_from_claims(claims: Dict[str, Any], groups_claim: str) -> Dict[str, Any]:
    raw_groups = claims.get(groups_claim) or []
    if isinstance(raw_groups, str):
        groups = _split_list(raw_groups)
    elif isinstance(raw_groups, (list, tuple)):
        groups = [str(x) for x in raw_groups]
    else:
        groups = []
    name = str(claims.get("preferred_username") or claims.get("email") or claims.get("sub") or "")
    return {
        "name": name,
        "email": str(claims.get("email") or ""),
        "sub": str(claims.get("sub") or ""),
        "groups": groups,
        "auth": "oidc",
        "login_at": time.time(),
    }


def _oidc_user_allowed(user: Dict[str, Any]) -> bool:
    if not user.get("sub"):
        return False
    required = env_str("DASHBOARD_REQUIRED_GROUP")
    if required and _group_match(list(user.get("groups") or []), required):
        return True
    allowed = {u.casefold() for u in _split_list(env_str("DASHBOARD_ALLOWED_USERS"))}
    identities = {str(user.get(k) or "").casefold() for k in ("name", "email", "sub")} - {""}
    return bool(allowed & identities)


# ---------------------------------------------------------------------------
# Hilfe fuer die Kommandozeile
# ---------------------------------------------------------------------------

def _cli(argv: List[str]) -> int:
    if len(argv) >= 1 and argv[0] == "hash-password":
        import getpass

        from werkzeug.security import generate_password_hash

        pw1 = getpass.getpass("Neues Dashboard-Passwort: ")
        pw2 = getpass.getpass("Wiederholen: ")
        if not pw1 or pw1 != pw2:
            print("Passwoerter leer oder nicht gleich.")
            return 1
        print(generate_password_hash(pw1))
        print("In die .env als DASHBOARD_PASSWORD_HASH eintragen, in einfachen Anfuehrungszeichen (wegen der $-Zeichen).")
        return 0
    print("Verwendung: python -m src.dashboard.auth hash-password")
    return 2


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_cli(sys.argv[1:]))
