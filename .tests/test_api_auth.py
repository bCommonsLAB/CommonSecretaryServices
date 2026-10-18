"""
Tests fuer AP-01: API-Token-Pruefung fail-closed und ohne Umgehung ueber Header.

Geschuetzte Beispielroute ist /api/booklet/themes (liefert nur Konstanten, keine
externen Abhaengigkeiten). /api/health/live ist die einzige oeffentliche Route.
"""
from __future__ import annotations

from typing import Any

import pytest

from auth_test_support import TOKEN, clear_security_env, make_app

PROTECTED = "/api/booklet/themes"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: Any) -> None:
    clear_security_env(monkeypatch)


def _client(remote_addr: str = "203.0.113.5") -> Any:
    client = make_app().test_client()
    client.environ_base["REMOTE_ADDR"] = remote_addr
    return client


def test_without_configured_token_protected_routes_are_closed() -> None:
    client = _client()
    resp = client.get(PROTECTED)
    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "SERVICE_TOKEN_NOT_CONFIGURED"


def test_liveness_probe_stays_public() -> None:
    client = _client()
    assert client.get("/api/health/live").status_code == 200


def test_health_overview_requires_token(monkeypatch: Any) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    client = _client()
    assert client.get("/api/health/").status_code == 401
    assert client.get("/api/health/use-case/transcription").status_code == 401


def test_insecure_mode_must_be_explicit(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    client = _client()
    assert client.get(PROTECTED).status_code == 200


@pytest.mark.parametrize("headers", [
    {"Authorization": f"Bearer {TOKEN}"},
    {"authorization": f"bearer {TOKEN}"},
    {"X-Secretary-Api-Key": TOKEN},
])
def test_valid_token_is_accepted(monkeypatch: Any, headers: dict) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    assert _client().get(PROTECTED, headers=headers).status_code == 200


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": f"Basic {TOKEN}"},
    {"X-Secretary-Api-Key": TOKEN[:-1]},
])
def test_missing_or_wrong_token_is_rejected(monkeypatch: Any, headers: dict) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    resp = _client().get(PROTECTED, headers=headers)
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("headers", [
    {"X-Forwarded-For": "127.0.0.1"},
    {"X-Real-IP": "127.0.0.1"},
    {"Host": "localhost"},
    {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1", "Host": "localhost"},
])
def test_spoofed_headers_do_not_bypass_localhost_or_whitelist(monkeypatch: Any, headers: dict) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("ALLOW_LOCALHOST_NO_AUTH", "true")
    monkeypatch.setenv("SWAGGER_IP_WHITELIST", "127.0.0.1,localhost")
    client = _client("203.0.113.5")
    assert client.get(PROTECTED, headers=headers).status_code == 401
    assert client.get("/api/swagger.json", headers=headers).status_code == 401


def test_localhost_exception_uses_real_peer_address(monkeypatch: Any) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("ALLOW_LOCALHOST_NO_AUTH", "true")
    assert _client("127.0.0.1").get(PROTECTED).status_code == 200
    assert _client("::1").get(PROTECTED).status_code == 200


def test_whitelist_supports_cidr_and_only_opens_swagger(monkeypatch: Any) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("SWAGGER_IP_WHITELIST", "198.51.100.0/24; 2001:db8::/32")
    client = _client("198.51.100.7")
    assert client.get("/api/swagger.json").status_code == 200
    assert client.get(PROTECTED).status_code == 401
    assert _client("2001:db8::5").get("/api/swagger.json").status_code == 200
    assert _client("192.0.2.1").get("/api/swagger.json").status_code == 401


def test_old_whitelist_variable_still_works_for_swagger(monkeypatch: Any) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("ALLOW_SWAGGER_WHITELIST", "198.51.100.7")
    client = _client("198.51.100.7")
    assert client.get("/api/swagger.json").status_code == 200
    assert client.get(PROTECTED).status_code == 401


def test_forwarded_for_only_counts_behind_trusted_proxy(monkeypatch: Any) -> None:
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("SWAGGER_IP_WHITELIST", "198.51.100.7")

    # Ohne TRUSTED_PROXY_COUNT zaehlt nur die direkte Gegenstelle (hier der Proxy).
    without_proxy = _client("10.0.0.2")
    assert without_proxy.get("/api/swagger.json", headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 401

    # Mit einem vertrauenswuerdigen Proxy zaehlt der letzte, vom Proxy angehaengte Eintrag.
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "1")
    behind_proxy = _client("10.0.0.2")
    assert behind_proxy.get("/api/swagger.json", headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 200
    # Ein vom Client vorangestellter Eintrag wird ignoriert.
    spoofed = behind_proxy.get("/api/swagger.json", headers={"X-Forwarded-For": "198.51.100.7, 203.0.113.9"})
    assert spoofed.status_code == 401


def test_security_problems_block_start_without_token(monkeypatch: Any) -> None:
    from src.api.auth import api_security_problems, api_security_warnings

    assert api_security_problems()
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    assert api_security_problems() == []
    assert any("ALLOW_INSECURE_NO_AUTH" in w for w in api_security_warnings())
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH")
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", "short")
    assert api_security_problems() == []
    assert any("32" in w for w in api_security_warnings())


def test_summary_contains_no_secret_values(monkeypatch: Any) -> None:
    from src.api.auth import api_security_summary

    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    monkeypatch.setenv("SWAGGER_IP_WHITELIST", "198.51.100.7")
    summary = api_security_summary()
    assert TOKEN not in str(summary)
    assert "198.51.100.7" not in str(summary)
    assert summary["service_token_present"] is True
