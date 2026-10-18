"""
Tests fuer AP-02: Dashboard-Anmeldung per OpenID Connect (Nextcloud).

Der Anbieter wird mit echtem RSA-Schluessel nachgebildet (auth_test_support.FakeOidcProvider),
damit Signatur, nonce, Issuer und Audience wirklich von Authlib geprueft werden.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from auth_test_support import TOKEN, FakeOidcProvider, clear_security_env, make_app


@pytest.fixture
def provider(monkeypatch: Any) -> FakeOidcProvider:
    clear_security_env(monkeypatch)
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("DASHBOARD_REQUIRED_GROUP", "secretary-admins")
    return FakeOidcProvider(monkeypatch)


@pytest.fixture
def client(provider: FakeOidcProvider) -> Any:
    return make_app().test_client()


def test_unauthenticated_page_redirects_to_login(client: Any) -> None:
    resp = client.get("/logs", headers={"Accept": "text/html"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/auth/login?next=%2Flogs"


def test_unauthenticated_json_request_gets_401(client: Any) -> None:
    resp = client.get("/llm-config/api/models", headers={"Accept": "application/json"})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "LOGIN_REQUIRED"


def test_login_redirect_uses_pkce_state_nonce_and_public_base_url(provider: FakeOidcProvider) -> None:
    client = make_app().test_client()
    resp = client.get("/auth/login?next=/logs", headers={"Host": "evil.example.net"})
    assert resp.status_code == 302
    params = {k: v[0] for k, v in parse_qs(urlparse(resp.headers["Location"]).query).items()}
    assert params["response_type"] == "code"
    assert params["client_id"] == provider.CLIENT_ID
    assert params["redirect_uri"] == f"{provider.PUBLIC_BASE_URL}/auth/callback"
    assert params["code_challenge_method"] == "S256" and params["code_challenge"]
    assert params["state"] and params["nonce"]
    assert set(params["scope"].split()) == {"openid", "profile", "email", "groups"}


def test_successful_login_with_group(provider: FakeOidcProvider, client: Any) -> None:
    resp = provider.login(client, groups=["staff", "secretary-admins"])
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/logs"
    assert client.get("/logs").data == b"LOGS"
    # Der Code wurde mit PKCE-Verifier eingetauscht
    assert provider.token_requests and provider.token_requests[0].get("code_verifier")


def test_login_without_group_is_forbidden(provider: FakeOidcProvider, client: Any) -> None:
    resp = provider.login(client, groups=["staff"])
    assert resp.status_code == 403
    assert client.get("/logs", headers={"Accept": "text/html"}).status_code == 302


def test_allowed_users_list_as_fallback(monkeypatch: Any, provider: FakeOidcProvider) -> None:
    monkeypatch.delenv("DASHBOARD_REQUIRED_GROUP")
    monkeypatch.setenv("DASHBOARD_ALLOWED_USERS", "someone@example.org, Peter@Example.org")
    client = make_app().test_client()
    assert provider.login(client, groups=None).status_code == 302
    assert client.get("/logs").status_code == 200


def test_groups_from_userinfo_endpoint(provider: FakeOidcProvider, client: Any) -> None:
    provider.userinfo = {"sub": "user-123", "groups": ["secretary-admins"]}
    resp = provider.login(client, groups=None)
    assert resp.status_code == 302
    assert any(call.endswith("/apps/oidc/userinfo") for call in provider.calls)


def test_userinfo_for_other_subject_is_ignored(provider: FakeOidcProvider, client: Any) -> None:
    provider.userinfo = {"sub": "someone-else", "groups": ["secretary-admins"]}
    assert provider.login(client, groups=None).status_code == 403


def test_wrong_state_is_rejected(provider: FakeOidcProvider, client: Any) -> None:
    params = provider.start_login(client)
    provider.set_identity(params, groups=["secretary-admins"])
    resp = client.get("/auth/callback?code=auth-code&state=manipuliert")
    assert resp.status_code == 400
    assert not provider.token_requests


@pytest.mark.parametrize("override", [
    {"nonce": "falsch"},
    {"iss": "https://evil.example.net"},
    {"aud": "anderer-client"},
    {"exp": int(time.time()) - 3600},
])
def test_invalid_id_token_claims_are_rejected(provider: FakeOidcProvider, client: Any, override: dict) -> None:
    resp = provider.login(client, groups=["secretary-admins"], **override)
    assert resp.status_code == 400
    assert client.get("/logs", headers={"Accept": "text/html"}).status_code == 302


def test_id_token_with_foreign_signature_is_rejected(provider: FakeOidcProvider, client: Any) -> None:
    provider.sign_with_other_key = True
    assert provider.login(client, groups=["secretary-admins"]).status_code == 400


@pytest.mark.parametrize("target", ["//evil.example.net/x", "https://evil.example.net", "/\\evil", "/auth/logout"])
def test_next_parameter_cannot_redirect_elsewhere(provider: FakeOidcProvider, client: Any, target: str) -> None:
    resp = provider.login(client, groups=["secretary-admins"], next_path=target)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_session_expires(monkeypatch: Any, provider: FakeOidcProvider, client: Any) -> None:
    provider.login(client, groups=["secretary-admins"])
    with client.session_transaction() as sess:
        user = dict(sess["dashboard_user"])
        user["login_at"] = time.time() - 13 * 3600
        sess["dashboard_user"] = user
    assert client.get("/logs", headers={"Accept": "text/html"}).status_code == 302


def test_logout_clears_session_and_redirects_to_provider(provider: FakeOidcProvider, client: Any) -> None:
    provider.login(client, groups=["secretary-admins"])
    resp = client.get("/auth/logout")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith(f"{provider.ISSUER}/apps/oidc/logout?")
    assert "post_logout_redirect_uri=https%3A%2F%2Fsecretary.example.org%2Fauth%2Flogged-out" in resp.headers["Location"]
    assert client.get("/logs", headers={"Accept": "text/html"}).status_code == 302


def test_swagger_with_dashboard_session(provider: FakeOidcProvider, client: Any) -> None:
    redirect = client.get("/api/doc", headers={"Accept": "text/html"})
    assert redirect.status_code == 302 and redirect.headers["Location"].startswith("/auth/login")
    provider.login(client, groups=["secretary-admins"])
    assert client.get("/api/swagger.json").status_code == 200
    # Eine Dashboard-Sitzung oeffnet keine Verarbeitungsrouten
    assert client.get("/api/booklet/themes").status_code == 401


def test_secure_cookie_flags(provider: FakeOidcProvider) -> None:
    app = make_app()
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


@pytest.mark.parametrize("missing", ["PUBLIC_BASE_URL", "FLASK_SECRET_KEY", "OIDC_CLIENT_SECRET", "DASHBOARD_REQUIRED_GROUP"])
def test_incomplete_oidc_config_is_reported(monkeypatch: Any, provider: FakeOidcProvider, missing: str) -> None:
    from src.dashboard.auth import dashboard_security_problems

    monkeypatch.delenv(missing)
    problems = dashboard_security_problems()
    assert problems
    assert make_app().test_client().get("/logs").status_code == 503


def test_public_base_url_must_be_https(monkeypatch: Any, provider: FakeOidcProvider) -> None:
    from src.dashboard.auth import dashboard_security_problems

    monkeypatch.setenv("PUBLIC_BASE_URL", "http://secretary.example.org")
    assert any("https" in p for p in dashboard_security_problems())
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:5001")
    assert dashboard_security_problems() == []
