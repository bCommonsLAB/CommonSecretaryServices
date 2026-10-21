"""
Tests fuer AP-04: Downloads mit Timeout und Größenlimit, TLS-Prüfung nur im Entwicklungsmodus abschaltbar.
"""
from __future__ import annotations

import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest
import requests

from src.utils.http_fetch import DownloadError, DownloadTooLarge, download_to_file, fetch_bytes

ROOT = Path(__file__).resolve().parents[1]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D401 - Testserver ruhig halten
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/small":
            body = b"x" * 100
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/declared-large":
            self.send_response(200)
            self.send_header("Content-Length", str(10_000_000))
            self.end_headers()
            self.wfile.write(b"x" * 1000)
        elif self.path == "/chunked-large":
            # Kein Content-Length: Größe ist nur beim Streamen erkennbar
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(50):
                chunk = b"y" * 4096
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
        elif self.path == "/slow":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(20):
                self.wfile.write(b"1\r\nz\r\n")
                self.wfile.flush()
                time.sleep(0.2)
            self.wfile.write(b"0\r\n\r\n")
        elif self.path == "/ua":
            body = (self.headers.get("User-Agent") or "").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_small_file(server: str, tmp_path: Path) -> None:
    dest = tmp_path / "a.bin"
    assert download_to_file(f"{server}/small", dest, max_bytes=1000) == 100
    assert dest.read_bytes() == b"x" * 100


def test_declared_size_over_limit_is_rejected(server: str, tmp_path: Path) -> None:
    dest = tmp_path / "a.bin"
    with pytest.raises(DownloadTooLarge):
        download_to_file(f"{server}/declared-large", dest, max_bytes=5000)
    assert not dest.exists()


def test_streamed_size_over_limit_is_rejected_without_content_length(server: str, tmp_path: Path) -> None:
    dest = tmp_path / "a.bin"
    with pytest.raises(DownloadTooLarge):
        download_to_file(f"{server}/chunked-large", dest, max_bytes=50_000)
    assert not dest.exists()
    with pytest.raises(DownloadTooLarge):
        fetch_bytes(f"{server}/chunked-large", max_bytes=50_000)


def test_total_duration_is_limited(server: str, tmp_path: Path) -> None:
    dest = tmp_path / "a.bin"
    with pytest.raises(DownloadError):
        download_to_file(f"{server}/slow", dest, max_bytes=1000, max_seconds=0.5)
    assert not dest.exists()


def test_http_error_is_raised(server: str, tmp_path: Path) -> None:
    with pytest.raises(requests.HTTPError):
        download_to_file(f"{server}/missing", tmp_path / "a.bin", max_bytes=1000)


def test_user_agent_is_set(server: str) -> None:
    assert fetch_bytes(f"{server}/ua", max_bytes=1000).startswith(b"CommonSecretaryServices")


def test_file_urls_are_not_fetched(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("geheim", encoding="utf-8")
    with pytest.raises(requests.exceptions.InvalidSchema):
        fetch_bytes(secret.as_uri(), max_bytes=1000)


@pytest.mark.parametrize("verify_env, flask_env, expected_verify, expected_state", [
    (None, None, True, "verified"),
    ("1", "development", True, "verified"),
    ("0", None, True, "ignored"),
    ("false", "production", True, "ignored"),
    ("0", "development", False, "disabled"),
])
def test_tls_policy(
    monkeypatch: pytest.MonkeyPatch, verify_env: str, flask_env: str, expected_verify: bool, expected_state: str
) -> None:
    import ssl

    from src.core import security

    for name, value in (("PYTHONHTTPSVERIFY", verify_env), ("FLASK_ENV", flask_env)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(ssl, "_create_default_https_context", ssl.create_default_context)
    assert security.tls_verify() is expected_verify
    assert security.apply_tls_policy() == expected_state
    patched = ssl._create_default_https_context is ssl._create_unverified_context  # type: ignore[attr-defined]
    assert patched is (expected_state == "disabled")


def test_download_uses_tls_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.utils import http_fetch

    seen = {}

    def fake_get(url: str, **kwargs: object) -> object:
        seen.update(kwargs)
        raise requests.ConnectionError("stop")

    monkeypatch.setattr(http_fetch.requests, "get", fake_get)
    monkeypatch.setenv("PYTHONHTTPSVERIFY", "0")
    monkeypatch.delenv("FLASK_ENV", raising=False)
    with pytest.raises(requests.ConnectionError):
        fetch_bytes("https://example.org/x", max_bytes=10)
    assert seen["verify"] is True
    assert seen["timeout"] == http_fetch.DEFAULT_TIMEOUT


def test_config_does_not_disable_ytdlp_certificate_check() -> None:
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert "nocheckcertificate" not in cfg["processors"]["youtube"]["ydl_opts"]


def test_no_unconditional_tls_bypass_in_source() -> None:
    """Abnahme aus dem Plan: keine fest abgeschaltete TLS-Prüfung mehr im Code."""
    offenders = []
    pattern = re.compile(r"nocheckcertificate['\"]?\s*:\s*True|verify\s*=\s*False|_create_unverified_context")
    for path in list((ROOT / "src").rglob("*.py")) + [ROOT / "config" / "config.yaml"]:
        if "/tests/" in str(path) or path.name == "security.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert offenders == []


def test_audio_download_rejects_oversized_stream(server: str, tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from src.core.exceptions import ProcessingError
    from src.processors.audio_processor import AudioProcessor

    proc = AudioProcessor.__new__(AudioProcessor)
    proc.temp_dir = tmp_path
    proc.temp_file_suffix = ".mp3"
    proc.max_file_size = 50_000
    proc.logger = MagicMock()
    with pytest.raises(ProcessingError, match="zu groß"):
        proc._download_audio(f"{server}/chunked-large")
    assert list(tmp_path.iterdir()) == []
    assert proc._download_audio(f"{server}/small").read_bytes() == b"x" * 100
