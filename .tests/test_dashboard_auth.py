"""
Tests fuer AP-02: Dashboard geschlossen per Default, Basic-, Forward- und Off-Modus, CSRF.
OIDC wird in test_dashboard_oidc.py geprueft.
"""
from __future__ import annotations

import base64
from typing import Any, Dict

import pytest
from werkzeug.security import generate_password_hash

from auth_test_support import SECRET_KEY, TOKEN, clear_security_env, make_app

PASSWORD = "richtig-langes-passwort"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: Any) -> None:
    clear_security_env(monkeypatch)
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)


def _basic(user: str, password: str) -> Dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def _basic_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", generate_password_hash(PASSWORD))
    monkeypatch.setenv("FLASK_SECRET_KEY", SECRET_KEY)


# --- geschlossen per Default -------------------------------------------------

def test_dashboard_is_locked_without_configuration() -> None:
    client = make_app().test_client()
    html = client.get("/logs", headers={"Accept": "text/html"})
    assert html.status_code == 503
    assert b"Dashboard gesperrt" in html.data
    assert client.get("/api/dashboard-stats").status_code == 503
    assert client.post("/clear-logs").status_code == 503


def test_api_keeps_working_while_dashboard_is_locked() -> None:
    client = make_app().test_client()
    assert client.get("/api/booklet/themes", headers={"X-Secretary-Api-Key": TOKEN}).status_code == 200


def test_dashboard_login_does_not_grant_api_access(monkeypatch: Any) -> None:
    _basic_env(monkeypatch)
    client = make_app().test_client()
    assert client.get("/api/booklet/themes", headers=_basic("admin", PASSWORD)).status_code == 401


# --- basic ------------------------------------------------------------------

def test_basic_mode_requires_credentials(monkeypatch: Any) -> None:
    _basic_env(monkeypatch)
    client = make_app().test_client()
    resp = client.get("/logs")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Basic")
    assert client.get("/logs", headers=_basic("admin", "falsch")).status_code == 401
    assert client.get("/logs", headers=_basic("other", PASSWORD)).status_code == 401
    ok = client.get("/logs", headers=_basic("admin", PASSWORD))
    assert ok.status_code == 200 and ok.data == b"LOGS"


def test_basic_mode_opens_swagger_but_challenges_without_login(monkeypatch: Any) -> None:
    _basic_env(monkeypatch)
    client = make_app().test_client()
    assert client.get("/api/swagger.json", headers=_basic("admin", PASSWORD)).status_code == 200
    challenge = client.get("/api/swagger.json")
    assert challenge.status_code == 401
    assert challenge.headers["WWW-Authenticate"].startswith("Basic")


def test_basic_mode_with_incomplete_config_stays_locked(monkeypatch: Any) -> None:
    from src.dashboard.auth import dashboard_security_problems

    monkeypatch.setenv("DASHBOARD_USER", "admin")
    problems = dashboard_security_problems()
    assert any("DASHBOARD_PASSWORD_HASH" in p for p in problems)
    assert any("FLASK_SECRET_KEY" in p for p in problems)
    client = make_app().test_client()
    assert client.get("/logs", headers=_basic("admin", PASSWORD)).status_code == 503


def test_secret_key_must_be_long_enough(monkeypatch: Any) -> None:
    from src.dashboard.auth import dashboard_security_problems

    _basic_env(monkeypatch)
    monkeypatch.setenv("FLASK_SECRET_KEY", "kurz")
    assert any("FLASK_SECRET_KEY" in p for p in dashboard_security_problems())


# --- CSRF -------------------------------------------------------------------

def test_post_without_csrf_token_is_rejected(monkeypatch: Any) -> None:
    _basic_env(monkeypatch)
    client = make_app().test_client()
    assert client.post("/clear-logs", headers=_basic("admin", PASSWORD)).status_code == 400


def test_post_with_csrf_token_header_is_accepted(monkeypatch: Any) -> None:
    _basic_env(monkeypatch)
    client = make_app().test_client()
    token = client.get("/csrf", headers=_basic("admin", PASSWORD)).data.decode()
    resp = client.post("/clear-logs", headers={**_basic("admin", PASSWORD), "X-CSRFToken": token})
    assert resp.status_code == 200 and resp.data == b"CLEARED"


def test_api_posts_are_not_subject_to_csrf(monkeypatch: Any) -> None:
    _basic_env(monkeypatch)
    client = make_app().test_client()
    # Ein API-POST mit Token darf nicht am CSRF-Schutz scheitern (400 waere CSRF).
    resp = client.post("/api/booklet/jobs", headers={"X-Secretary-Api-Key": TOKEN}, data="kein json",
                       content_type="text/plain")
    assert resp.status_code != 401
    assert b"CSRF" not in resp.data


# --- forward ----------------------------------------------------------------

def test_forward_mode_requires_trusted_proxy(monkeypatch: Any) -> None:
    from src.dashboard.auth import dashboard_security_problems

    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "forward")
    monkeypatch.setenv("FLASK_SECRET_KEY", SECRET_KEY)
    assert any("TRUSTED_PROXY_COUNT" in p for p in dashboard_security_problems())
    client = make_app().test_client()
    assert client.get("/logs", headers={"X-Auth-Request-User": "admin"}).status_code == 503


def test_forward_mode_reads_user_and_group_from_proxy(monkeypatch: Any) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "forward")
    monkeypatch.setenv("FLASK_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    monkeypatch.setenv("DASHBOARD_REQUIRED_GROUP", "secretary-admins")
    client = make_app().test_client()
    assert client.get("/logs").status_code == 401
    assert client.get("/logs", headers={"X-Auth-Request-User": "admin",
                                         "X-Auth-Request-Groups": "staff"}).status_code == 401
    ok = client.get("/logs", headers={"X-Auth-Request-User": "admin",
                                       "X-Auth-Request-Groups": "staff,secretary-admins"})
    assert ok.status_code == 200


# --- off --------------------------------------------------------------------

def test_off_mode_needs_explicit_insecure_flag(monkeypatch: Any) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "off")
    assert make_app().test_client().get("/logs").status_code == 503
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    assert make_app().test_client().get("/logs").status_code == 200


def test_unknown_mode_is_a_problem(monkeypatch: Any) -> None:
    from src.dashboard.auth import dashboard_security_problems

    monkeypatch.setenv("DASHBOARD_AUTH_MODE", "magic")
    assert dashboard_security_problems()


# --- Verdrahtung --------------------------------------------------------------

def test_dashboard_guard_is_first_before_request_hook() -> None:
    """Die Dashboard-Pruefung muss vor dem Worker-Start-Hook laufen."""
    from src.dashboard.auth import _dashboard_guard

    app = make_app()
    assert app.before_request_funcs[None][0] is _dashboard_guard


# --- Passwort-Hash in verschiedenen Schreibweisen (Erfahrung aus dem ersten Rollout) -----

@pytest.mark.parametrize("variant", ["plain", "single_quotes", "double_quotes", "dotted", "compose_dollars"])
def test_password_hash_variants_are_accepted(monkeypatch: Any, variant: str) -> None:
    from src.dashboard.auth import dotted_password_hash

    real = generate_password_hash(PASSWORD, method="pbkdf2:sha256")
    value = {
        "plain": real,
        "single_quotes": f"'{real}'",
        "double_quotes": f'"{real}"',
        "dotted": dotted_password_hash(real),
        "compose_dollars": real.replace("$", "$$"),
    }[variant]
    _basic_env(monkeypatch)
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", value)
    client = make_app().test_client()
    assert client.get("/logs", headers=_basic("admin", PASSWORD)).status_code == 200
    assert client.get("/logs", headers=_basic("admin", "falsch")).status_code == 401


@pytest.mark.parametrize("broken", [
    "'scrypt:32768:8:1$...$...'",          # Platzhalter aus der Anleitung
    "pbkdf2:sha256:600000",                 # $-Teile beim Deployment ersetzt
    "pbkdf2:sha256:600000$abc$",            # Hash-Teil fehlt
    "geheim",                               # Klartext statt Hash
])
def test_broken_password_hash_locks_dashboard_with_reason(monkeypatch: Any, broken: str) -> None:
    from src.dashboard.auth import dashboard_security_problems

    _basic_env(monkeypatch)
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", broken)
    assert any("kein gueltiger Passwort-Hash" in p for p in dashboard_security_problems())
    assert make_app().test_client().get("/logs", headers=_basic("admin", PASSWORD)).status_code == 503


def test_dashboard_problem_does_not_block_api(monkeypatch: Any) -> None:
    from src.api.auth import api_security_problems

    _basic_env(monkeypatch)
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "kaputt")
    assert api_security_problems() == []
    client = make_app().test_client()
    assert client.get("/api/booklet/themes", headers={"X-Secretary-Api-Key": TOKEN}).status_code == 200
