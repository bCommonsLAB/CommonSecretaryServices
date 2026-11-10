"""
Tests fuer AP-05 (Fehlerausgaben und Informationsabfluss, Befund M3).

- Unerwartete Ausnahmen liefern in API-Antworten nur eine allgemeine Meldung mit Referenz.
- Erwartete Fehler behalten ihre Meldung, bereinigt von Pfaden und Geheimnissen.
- Stacktraces stehen weder in API-Antworten noch in Job-Dokumenten oder Fehler-Webhooks.
- Statische Pruefung der Routen: `format_exc()` nur in Logger-Aufrufen, kein roher
  Ausnahmetext in Antworten.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from auth_test_support import TOKEN, clear_security_env, make_app
from src.core.exceptions import ProcessingError
from src.core.models.base import ErrorInfo, strip_internal_details
from src.core.models.job_models import JobError
from src.utils import error_responses
from src.utils.error_responses import is_public_error, public_error_message, redact_sensitive

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "src" / "api" / "routes"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


# --------------------------------------------------------------------------- redact_sensitive

@pytest.mark.parametrize(
    "text, forbidden, expected_part",
    [
        ("connect mongodb://admin:geheim123@db:27017/x failed", "geheim123", "mongodb://<zugang>@db:27017/x"),
        ("401 for Authorization: Bearer abcdef1234567890XYZ", "abcdef1234567890XYZ", "Bearer <token>"),
        ("Incorrect API key provided: sk-proj-abcdefgh12345678", "abcdefgh12345678", "<schluessel>"),
        ("GET https://api.example/v1?api_key=topsecretvalue&x=1", "topsecretvalue", "api_key=<geheim>"),
        ("[Errno 2] No such file: '/app/cache/uploads/abc/bericht.pdf'", "/app/cache", "<pfad>/bericht.pdf"),
        ("cookies in /home/peter/.config/cookies.txt unreadable", "/home/peter", "<pfad>/cookies.txt"),
        (r"Datei C:\Users\peter\secret\daten.xlsx fehlt", r"C:\Users\peter", "<pfad>/daten.xlsx"),
    ],
)
def test_redact_entfernt_geheimnisse_und_verzeichnisse(text: str, forbidden: str, expected_part: str) -> None:
    result = redact_sensitive(text)
    assert forbidden not in result
    assert expected_part in result


def test_redact_laesst_urls_und_normale_meldungen_stehen() -> None:
    text = "Kein Medium unter https://example.org/home/video/123 gefunden (Format: mp4)"
    assert redact_sensitive(text) == text
    assert redact_sensitive("Feld 'url' ist erforderlich") == "Feld 'url' ist erforderlich"
    assert redact_sensitive("") == ""


# ----------------------------------------------------------------------- public_error_message

def test_erwartete_fehler_behalten_ihre_meldung() -> None:
    assert public_error_message(ProcessingError("Datei zu gross (12 MB)")) == "Datei zu gross (12 MB)"
    assert public_error_message(ValueError("Feld 'x' fehlt")) == "Feld 'x' fehlt"
    assert is_public_error(ProcessingError("x"))
    assert not is_public_error(RuntimeError("x"))
    assert not is_public_error(FileNotFoundError("x"))


def test_erwartete_fehler_werden_bereinigt() -> None:
    error = ProcessingError("Download fehlgeschlagen: /app/cache/tmp/x.mp4 mit Bearer abcdefgh12345678")
    message = public_error_message(error)
    assert "/app/cache" not in message
    assert "abcdefgh12345678" not in message
    assert message.startswith("Download fehlgeschlagen")


def test_unerwartete_fehler_liefern_nur_referenz(monkeypatch: Any) -> None:
    logged: List[Dict[str, Any]] = []

    class _Logger:
        def error(self, message: str, error: Optional[Exception] = None, **kwargs: Any) -> None:
            logged.append({"message": message, **kwargs})

    monkeypatch.setattr(error_responses, "logger", _Logger())

    try:
        raise RuntimeError("pymongo: mongodb://admin:geheim@db:27017 nicht erreichbar, /app/config/config.yaml")
    except RuntimeError as exc:
        first = public_error_message(exc)
        second = public_error_message(exc)

    assert first.startswith("Interner Fehler (Referenz: ")
    assert "geheim" not in first and "/app" not in first and "mongodb" not in first
    # Dieselbe Ausnahme: dieselbe Referenz, nur ein Log-Eintrag mit vollem Stacktrace
    assert first == second
    assert len(logged) == 1
    ref = first.split("Referenz: ")[1].rstrip(")")
    assert logged[0]["error_ref"] == ref
    assert "RuntimeError" in logged[0]["stack_trace"]
    assert "test_unerwartete_fehler_liefern_nur_referenz" in logged[0]["stack_trace"]


def test_expected_gibt_fremde_fachfehler_bereinigt_weiter() -> None:
    error = RuntimeError("ERROR: [youtube] abc: Video unavailable (cookies: /home/app/cookies.txt)")
    message = public_error_message(error, expected=True)
    assert "Video unavailable" in message
    assert "/home/app" not in message


def test_logging_fehler_verhindert_die_antwort_nicht(monkeypatch: Any) -> None:
    class _Broken:
        def error(self, *args: Any, **kwargs: Any) -> None:
            raise OSError("Logdatei nicht schreibbar")

    monkeypatch.setattr(error_responses, "logger", _Broken())
    assert public_error_message(KeyError("x")).startswith("Interner Fehler (Referenz: ")


# ------------------------------------------------------------------ Modelle: kein Stacktrace

def test_error_info_serialisiert_keinen_stacktrace() -> None:
    info = ErrorInfo(code="X", message="y", details={"traceback": "Traceback ...", "stack_trace": "s", "feld": 1})
    assert info.to_dict() == {"code": "X", "message": "y", "details": {"feld": 1}}
    assert strip_internal_details(None) == {}


def test_job_error_liefert_keinen_stacktrace_auch_nicht_aus_alten_dokumenten() -> None:
    alt = JobError.from_dict({"code": "E", "message": "m", "details": {"traceback": "Traceback ...", "duration_ms": 5}})
    assert alt.to_dict() == {"code": "E", "message": "m", "details": {"duration_ms": 5}}
    assert JobError(code="E", message="m").to_dict()["details"] is None


# ------------------------------------------------------------------------ Route von aussen

@pytest.fixture
def client(monkeypatch: Any) -> Any:
    clear_security_env(monkeypatch)
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    return make_app().test_client()


def test_route_verraet_bei_unerwartetem_fehler_nichts(client: Any, monkeypatch: Any) -> None:
    from src.api.routes import media_routes

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("interner Zustand: /app/config/config.yaml, key sk-live-abcdefgh12345678")

    monkeypatch.setattr(media_routes, "resolve_media_url", _boom)
    response = client.post("/api/media/resolve", json={"url": "https://example.org/v"}, headers=AUTH)
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert "Interner Fehler (Referenz: " in body
    for forbidden in ("/app/config", "sk-live", "Traceback", "RuntimeError", "interner Zustand"):
        assert forbidden not in body


def test_route_gibt_erwarteten_fehler_weiter(client: Any, monkeypatch: Any) -> None:
    from src.api.routes import media_routes

    def _invalid(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Seite enthaelt kein Medium")

    monkeypatch.setattr(media_routes, "resolve_media_url", _invalid)
    response = client.post("/api/media/resolve", json={"url": "https://example.org/v"}, headers=AUTH)
    assert response.status_code == 422
    assert "Seite enthaelt kein Medium" in response.get_data(as_text=True)


# ------------------------------------------------------------- statische Pruefung der Routen

_LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception"}
_ERROR_NAMES = {"e", "exc", "err", "error", "ex"}


def _parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _ancestors(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> Iterator[ast.AST]:
    while node in parents:
        node = parents[node]
        yield node


def _is_logger_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LOG_METHODS
        and "log" in ast.unparse(node.func.value).lower()
    )


def _route_trees() -> Iterator[Tuple[Path, ast.AST]]:
    for path in sorted(ROUTES_DIR.glob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def test_format_exc_nur_in_logger_aufrufen() -> None:
    """Akzeptanzkriterium aus dem Plan: format_exc() in src/api/routes nur in Logger-Aufrufen."""
    findings: List[str] = []
    for path, tree in _route_trees():
        parents = _parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("format_exc"):
                if not any(_is_logger_call(a) for a in _ancestors(node, parents)):
                    findings.append(f"{path.name}:{node.lineno}")
    assert not findings, f"format_exc() ausserhalb eines Logger-Aufrufs: {findings}"


def test_keine_stacktrace_felder_in_antworten() -> None:
    findings: List[str] = []
    for path, tree in _route_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant) and key.value in ("traceback", "stack_trace", "stacktrace"):
                        findings.append(f"{path.name}:{node.lineno}")
    assert not findings, f"Stacktrace-Feld in einer Antwort: {findings}"


def test_kein_roher_ausnahmetext_ausserhalb_von_logs() -> None:
    """
    In except-Zweigen der Routen darf der Text der Ausnahme nur in Logger-Aufrufen, in einer
    neu geworfenen Ausnahme oder ueber public_error_message() verwendet werden.
    """
    # Bewusste Ausnahmen: (Datei, Quelltext der Zeile) mit Begruendung
    allowed = {
        # ProcessingError des eigenen Dienstes; der Text entscheidet nur ueber den Fehlercode
        # und wird nach aussen als eigene Meldung gegeben.
        ("realtime_routes.py", "message = str(e)"),
    }
    findings: List[str] = []
    for path, tree in _route_trees():
        parents = _parents(tree)
        lines = path.read_text(encoding="utf-8").splitlines()
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler) or handler.name not in _ERROR_NAMES:
                continue
            for node in ast.walk(handler):
                raw = (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("str", "repr")
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == handler.name
                ) or (
                    isinstance(node, ast.FormattedValue)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == handler.name
                )
                if not raw:
                    continue
                chain = list(_ancestors(node, parents))
                if any(_is_logger_call(a) or isinstance(a, ast.Raise) for a in chain):
                    continue
                if any(isinstance(a, ast.Call) and ast.unparse(a.func) in ("print", "set_error", "metric_tracker.set_error") for a in chain):
                    continue
                source = lines[node.lineno - 1].strip()
                if (path.name, source) in allowed:
                    continue
                findings.append(f"{path.name}:{node.lineno}: {source}")
    assert not findings, "Roher Ausnahmetext ausserhalb von Logs:\n" + "\n".join(findings)
