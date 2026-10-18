"""
Tests fuer AP-07: Die mitgelieferte docker-compose.yml ist sicher per Default,
und Verbindungsadressen erscheinen ohne Passwort im Log.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"


def _compose() -> Dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _env_list(service: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in service.get("environment", []):
        key, _, value = str(item).partition("=")
        result[key] = value
    return result


def test_mongodb_has_no_host_port() -> None:
    mongodb = _compose()["services"]["mongodb"]
    assert "ports" not in mongodb


def test_mongodb_enforces_authentication() -> None:
    mongodb = _compose()["services"]["mongodb"]
    assert "--auth" in mongodb["command"]
    env = _env_list(mongodb)
    assert env["MONGO_INITDB_ROOT_USERNAME"].startswith("${MONGO_ROOT_USER:?")
    assert env["MONGO_INITDB_ROOT_PASSWORD"].startswith("${MONGO_ROOT_PASSWORD:?")


def test_secretary_uri_uses_credentials_database_and_auth_source() -> None:
    uri = _env_list(_compose()["services"]["secretary-services"])["MONGODB_URI"]
    assert "${MONGO_ROOT_USER:?" in uri and "${MONGO_ROOT_PASSWORD:?" in uri
    assert "@mongodb:27017/${MONGO_DB_NAME:-commonsec}" in uri
    assert uri.endswith("?authSource=admin")


def test_secretary_waits_for_healthy_database() -> None:
    services = _compose()["services"]
    assert services["secretary-services"]["depends_on"]["mongodb"]["condition"] == "service_healthy"
    assert "healthcheck" in services["mongodb"]
    assert "/api/health/live" in " ".join(services["secretary-services"]["healthcheck"]["test"])


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI nicht vorhanden")
def test_compose_refuses_to_start_without_credentials(tmp_path: Path) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "--env-file", str(empty_env), "config"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin:/usr/local/bin"}, timeout=60,
    )
    if "is not a docker command" in proc.stderr or "unknown command" in proc.stderr:
        pytest.skip("docker compose nicht verfuegbar")
    assert proc.returncode != 0
    assert "MONGO_ROOT_" in proc.stderr and "fehlt in der .env" in proc.stderr


@pytest.mark.parametrize("uri, expected", [
    ("mongodb://admin:geheim123@mongodb:27017/commonsec?authSource=admin",
     "mongodb://admin:***@mongodb:27017/commonsec?authSource=admin"),
    ("mongodb+srv://user:p%40ss@cluster.example.net/db", "mongodb+srv://user:***@cluster.example.net/db"),
    ("mongodb://mongodb:27017/commonsec", "mongodb://mongodb:27017/commonsec"),
    ("", ""),
    (None, ""),
])
def test_redact_uri_hides_password(uri: Any, expected: str) -> None:
    from src.core.security import redact_uri

    assert redact_uri(uri) == expected
