"""
Gemeinsame Hilfen fuer die Auth-Tests (AP-01/AP-02).

- make_app(): kleine Flask-App mit echtem API-Blueprint und echter Dashboard-Anmeldung,
  ohne die schwergewichtige Initialisierung aus src/dashboard/app.py.
- FakeOidcProvider: bildet Discovery, JWKS, Token- und Userinfo-Endpunkt einer Nextcloud
  nach, mit echtem RSA-Schluessel und signierten ID-Tokens.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from flask import Flask, jsonify
from flask_wtf.csrf import generate_csrf

SECURITY_ENV_VARS: List[str] = [
    "SECRETARY_SERVICE_API_KEY",
    "ALLOW_INSECURE_NO_AUTH",
    "ALLOW_LOCALHOST_NO_AUTH",
    "ALLOW_SWAGGER_WHITELIST",
    "SWAGGER_IP_WHITELIST",
    "AUTH_LOG_DECISIONS",
    "TRUSTED_PROXY_COUNT",
    "DASHBOARD_AUTH_MODE",
    "DASHBOARD_USER",
    "DASHBOARD_PASSWORD_HASH",
    "DASHBOARD_REQUIRED_GROUP",
    "DASHBOARD_ALLOWED_USERS",
    "DASHBOARD_FORWARD_USER_HEADER",
    "DASHBOARD_FORWARD_GROUPS_HEADER",
    "DASHBOARD_SESSION_HOURS",
    "DASHBOARD_LOGOUT_URL",
    "FLASK_SECRET_KEY",
    "PUBLIC_BASE_URL",
    "OIDC_ISSUER",
    "OIDC_DISCOVERY_URL",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_GROUPS_CLAIM",
    "OIDC_SCOPES",
]

TOKEN = "t" * 40
SECRET_KEY = "k" * 64


def clear_security_env(monkeypatch: Any) -> None:
    for var in SECURITY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def make_app() -> Flask:
    """App wie in Produktion verdrahtet: ProxyFix, Dashboard-Anmeldung, API-Blueprint, Dashboard-Routen."""
    from src.api.routes import blueprint as api_blueprint
    from src.core.security import apply_proxy_fix
    from src.dashboard.auth import init_dashboard_auth

    app = Flask(__name__)
    app.testing = True
    apply_proxy_fix(app)
    init_dashboard_auth(app)
    app.register_blueprint(api_blueprint, url_prefix="/api")

    @app.route("/logs")
    def logs() -> str:
        return "LOGS"

    @app.route("/clear-logs", methods=["POST"])
    def clear_logs() -> str:
        return "CLEARED"

    @app.route("/api/dashboard-stats")
    def dashboard_stats() -> Any:
        return jsonify({"ok": True})

    @app.route("/llm-config/api/models")
    def llm_models() -> Any:
        return jsonify({"models": []})

    @app.route("/csrf")
    def csrf_token_route() -> str:
        return generate_csrf()

    return app


def _json_response(url: str, data: Any, status: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(data).encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    resp.url = url
    resp.encoding = "utf-8"
    return resp


class FakeOidcProvider:
    """Nachgebildete Nextcloud mit OIDC-App; faengt requests.Session.request ab."""

    ISSUER = "https://cloud.example.org"
    CLIENT_ID = "secretary-dashboard"
    CLIENT_SECRET = "client-secret-value"
    PUBLIC_BASE_URL = "https://secretary.example.org"

    def __init__(self, monkeypatch: Any, scopes_supported: Optional[List[str]] = None,
                 end_session: bool = True) -> None:
        from authlib.jose import JsonWebKey

        self.key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        self.kid = "test-key-1"
        self.other_key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        self.metadata: Dict[str, Any] = {
            "issuer": self.ISSUER,
            "authorization_endpoint": f"{self.ISSUER}/apps/oidc/authorize",
            "token_endpoint": f"{self.ISSUER}/apps/oidc/token",
            "jwks_uri": f"{self.ISSUER}/apps/oidc/jwks",
            "userinfo_endpoint": f"{self.ISSUER}/apps/oidc/userinfo",
            "scopes_supported": scopes_supported or ["openid", "profile", "email", "groups"],
            "response_types_supported": ["code"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        if end_session:
            self.metadata["end_session_endpoint"] = f"{self.ISSUER}/apps/oidc/logout"
        self.id_claims: Dict[str, Any] = {}
        self.userinfo: Dict[str, Any] = {}
        self.sign_with_other_key = False
        self.token_requests: List[Dict[str, Any]] = []
        self.calls: List[str] = []

        monkeypatch.setenv("OIDC_ISSUER", self.ISSUER)
        monkeypatch.setenv("OIDC_CLIENT_ID", self.CLIENT_ID)
        monkeypatch.setenv("OIDC_CLIENT_SECRET", self.CLIENT_SECRET)
        monkeypatch.setenv("PUBLIC_BASE_URL", self.PUBLIC_BASE_URL)
        monkeypatch.setenv("FLASK_SECRET_KEY", SECRET_KEY)
        provider = self

        def fake_request(session: Any, method: str, url: str, *args: Any, **kwargs: Any) -> requests.Response:
            return provider._request(method, url, *args, **kwargs)

        monkeypatch.setattr(requests.Session, "request", fake_request)

    # -- HTTP --------------------------------------------------------------
    def _request(self, method: str, url: str, *args: Any, **kwargs: Any) -> requests.Response:
        self.calls.append(f"{method.upper()} {url}")
        if url == f"{self.ISSUER}/.well-known/openid-configuration":
            return _json_response(url, self.metadata)
        if url == self.metadata["jwks_uri"]:
            public = self.key.as_dict(is_private=False)
            public.update({"kid": self.kid, "alg": "RS256", "use": "sig"})
            return _json_response(url, {"keys": [public]})
        if url == self.metadata["token_endpoint"]:
            self.token_requests.append(dict(kwargs.get("data") or {}))
            return _json_response(url, {
                "access_token": "access-token-value",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": self._id_token(),
            })
        if url == self.metadata["userinfo_endpoint"]:
            return _json_response(url, self.userinfo)
        return _json_response(url, {"error": "not found"}, 404)

    def _id_token(self) -> str:
        from authlib.jose import jwt

        key = self.other_key if self.sign_with_other_key else self.key
        header = {"alg": "RS256", "kid": self.kid}
        return jwt.encode(header, self.id_claims, key).decode("utf-8")

    # -- Ablauf ------------------------------------------------------------
    def start_login(self, client: Any, next_path: str = "/logs") -> Dict[str, str]:
        """Ruft /auth/login auf und liefert die Parameter der Authorize-Weiterleitung."""
        resp = client.get(f"/auth/login?next={next_path}")
        assert resp.status_code == 302, resp.status_code
        location = resp.headers["Location"]
        assert location.startswith(self.metadata["authorization_endpoint"]), location
        return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}

    def set_identity(self, params: Dict[str, str], groups: Optional[List[str]] = None,
                     **overrides: Any) -> None:
        now = int(time.time())
        claims: Dict[str, Any] = {
            "iss": self.ISSUER,
            "aud": self.CLIENT_ID,
            "sub": "user-123",
            "iat": now,
            "exp": now + 300,
            "nonce": params.get("nonce"),
            "preferred_username": "peter",
            "email": "peter@example.org",
        }
        if groups is not None:
            claims["groups"] = groups
        claims.update(overrides)
        self.id_claims = {k: v for k, v in claims.items() if v is not None}

    def login(self, client: Any, groups: Optional[List[str]] = None, next_path: str = "/logs",
              **overrides: Any) -> Any:
        params = self.start_login(client, next_path)
        self.set_identity(params, groups=groups, **overrides)
        return client.get(f"/auth/callback?code=auth-code&state={params['state']}")
