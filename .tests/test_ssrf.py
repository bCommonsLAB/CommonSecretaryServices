"""
Tests fuer AP-12 (SSRF-Schutz zentral, Befund H1).

- check_url: nur http/https, nur oeffentliche Ziele; alle bekannten Schreibweisen interner Adressen.
- Verbindungsebene: geprueft wird die Adresse, die tatsaechlich verbunden wird (DNS-Rebinding),
  und jede Weiterleitung.
- Ausnahmen je Installation ueber FETCH_ALLOWED_HOSTS / WEBHOOK_ALLOWED_HOSTS.
- Webhooks: Callback-Adresse wird beim Annehmen der Anfrage (400) und beim Senden geprueft.
- yt-dlp: jede abgerufene Adresse und das Ziel einer Weiterleitung werden geprueft.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List

import pytest
import requests

import conftest
from auth_test_support import TOKEN, clear_security_env, make_app
from src.utils import http_fetch, ssrf
from src.utils.ssrf import SsrfBlocked, check_url, is_public_ip

AUTH = {"Authorization": f"Bearer {TOKEN}"}


# ------------------------------------------------------------------------------- check_url

@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:27017/",
        "http://localhost:11434/api/tags",
        "http://127.1/",                      # Kurzschreibweise
        "http://2130706433/",                 # 127.0.0.1 als Dezimalzahl
        "http://0x7f.0.0.1/",                 # hexadezimal
        "http://0.0.0.0/",
        "http://10.0.0.5/",
        "http://172.16.3.4/",
        "http://192.168.1.10/",
        "http://169.254.169.254/latest/meta-data/",   # Cloud-Metadaten
        "http://100.64.0.1/",                 # Carrier-Grade-NAT
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",         # IPv4 in IPv6 eingebettet
        "http://[::ffff:169.254.169.254]/",
        "http://224.0.0.1/",
    ],
)
def test_interne_ziele_werden_abgelehnt(url: str) -> None:
    with pytest.raises(SsrfBlocked):
        check_url(url)
    assert not ssrf.is_url_allowed(url)


@pytest.mark.parametrize(
    "url",
    ["ftp://example.org/x", "file:///etc/passwd", "gopher://example.org/", "//example.org/x", "example.org/x", "", "http:///pfad"],
)
def test_nur_http_und_https_mit_host(url: str) -> None:
    with pytest.raises(SsrfBlocked):
        check_url(url)


def test_oeffentliche_ziele_sind_erlaubt() -> None:
    assert check_url("https://example.org/datei.pdf") == [conftest.PUBLIC_TEST_IP]
    assert check_url("http://8.8.8.8/") == ["8.8.8.8"]
    assert is_public_ip("2606:4700:4700::1111")
    assert not is_public_ip("kein-ip")


def test_hostname_der_auf_interne_adresse_zeigt() -> None:
    conftest.FAKE_DNS["intern.example"] = ["10.1.2.3"]
    with pytest.raises(SsrfBlocked) as info:
        check_url("https://intern.example/api")
    assert info.value.code == "SSRF_BLOCKED"
    assert "10.1.2.3" not in str(info.value)  # keine interne Adresse in der Meldung


def test_eine_interne_adresse_unter_mehreren_genuegt() -> None:
    conftest.FAKE_DNS["gemischt.example"] = [conftest.PUBLIC_TEST_IP, "127.0.0.1"]
    with pytest.raises(SsrfBlocked):
        check_url("https://gemischt.example/")


def test_nicht_aufloesbarer_host_wird_abgelehnt() -> None:
    conftest.FAKE_DNS["gibtsnicht.example"] = []
    with pytest.raises(SsrfBlocked):
        check_url("https://gibtsnicht.example/")


def test_zugangsdaten_in_der_adresse_taeuschen_nicht() -> None:
    with pytest.raises(SsrfBlocked):
        check_url("http://example.org@127.0.0.1/")
    with pytest.raises(SsrfBlocked):
        check_url("http://example.org:pw@localhost/")


# ----------------------------------------------------------------------------- Ausnahmelisten

def test_ausnahmeliste_je_zweck(monkeypatch: pytest.MonkeyPatch) -> None:
    conftest.FAKE_DNS["ks.intern.example"] = ["10.0.0.7"]
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", " *.intern.example , 127.0.0.1")
    assert check_url("http://ks.intern.example:3000/hook", ssrf.PURPOSE_WEBHOOK) == ["10.0.0.7"]
    assert check_url("http://127.0.0.1:3000/hook", ssrf.PURPOSE_WEBHOOK) == ["127.0.0.1"]
    # Die Webhook-Ausnahme gilt nicht für Downloads und nicht für andere Hosts
    with pytest.raises(SsrfBlocked):
        check_url("http://ks.intern.example:3000/datei", ssrf.PURPOSE_FETCH)
    with pytest.raises(SsrfBlocked):
        check_url("http://192.168.0.1/hook", ssrf.PURPOSE_WEBHOOK)
    # Das Muster passt nur auf das Ende des Hostnamens, nicht auf einen Namen, der es nur enthält
    conftest.FAKE_DNS["intern.example.boese.test"] = ["10.0.0.8"]
    with pytest.raises(SsrfBlocked):
        check_url("http://intern.example.boese.test/hook", ssrf.PURPOSE_WEBHOOK)


# ------------------------------------------------------------------ Verbindung und Redirects

class _Handler(BaseHTTPRequestHandler):
    hits: List[str] = []

    def log_message(self, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        _Handler.hits.append(self.path)
        if self.path.startswith("/redirect-intern"):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/loop"):
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"geheim-intern"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET  # noqa: N815


@pytest.fixture
def local_server() -> Iterator[str]:
    _Handler.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_auf_internes_ziel_wird_nicht_ausgefuehrt(local_server: str) -> None:
    with pytest.raises(SsrfBlocked):
        http_fetch.fetch_bytes(f"http://{local_server}/x", max_bytes=1000)
    assert _Handler.hits == []  # es wurde keine Verbindung aufgebaut


def test_allow_private_und_ausnahmeliste_erlauben_den_abruf(local_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert http_fetch.fetch_bytes(f"http://{local_server}/x", max_bytes=1000, allow_private=True) == b"geheim-intern"
    monkeypatch.setenv("FETCH_ALLOWED_HOSTS", "127.0.0.1")
    assert ssrf.get(f"http://{local_server}/x", timeout=5).content == b"geheim-intern"


def test_weiterleitung_auf_internes_ziel_wird_abgelehnt(local_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FETCH_ALLOWED_HOSTS", "127.0.0.1")
    with pytest.raises(SsrfBlocked):
        ssrf.get(f"http://{local_server}/redirect-intern", timeout=5)
    assert _Handler.hits == ["/redirect-intern"]


def test_hoechstens_fuenf_weiterleitungen(local_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FETCH_ALLOWED_HOSTS", "127.0.0.1")
    with pytest.raises(requests.TooManyRedirects):
        ssrf.get(f"http://{local_server}/loop", timeout=5)
    assert len(_Handler.hits) == ssrf.MAX_REDIRECTS + 1


def test_dns_rebinding_verbunden_wird_die_gepruefte_adresse(local_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Der Name zeigt bei der ersten Auflösung auf eine öffentliche Adresse, danach auf 127.0.0.1.
    Die Verbindung löst selbst auf und prüft: der zweite Wert wird abgelehnt, der lokale Server
    wird nie erreicht.
    """
    port = int(local_server.split(":")[1])
    answers = [[conftest.PUBLIC_TEST_IP], ["127.0.0.1"]]

    def rebinding(host: str, _port: int) -> List[Any]:
        import socket
        address = (answers.pop(0) if answers else ["127.0.0.1"])[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, _port))]

    monkeypatch.setattr(ssrf, "_getaddrinfo", rebinding)
    # Ohne ausgehenden Proxy, damit die Verbindung direkt aufgebaut wird
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SsrfBlocked):
        ssrf.get(f"http://rebind.example:{port}/x", timeout=5)
    assert _Handler.hits == []


# ----------------------------------------------------------------------------------- Webhooks

def test_post_webhook_sperrt_interne_ziele_und_kennt_ausnahmen(local_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SsrfBlocked):
        ssrf.post_webhook(f"http://{local_server}/hook", json={"a": 1}, timeout=5)
    assert _Handler.hits == []
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "127.0.0.1")
    assert ssrf.post_webhook(f"http://{local_server}/hook", json={"a": 1}, timeout=5).status_code == 200
    assert _Handler.hits == ["/hook"]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    clear_security_env(monkeypatch)
    monkeypatch.setenv("SECRETARY_SERVICE_API_KEY", TOKEN)
    return make_app().test_client()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data": {"callback_url": "http://127.0.0.1:1/"}},                         # Formular (Akzeptanzkriterium)
        {"json": {"callback_url": "http://169.254.169.254/x"}},                    # JSON
        {"json": {"webhook": {"url": "http://10.0.0.1/hook"}}},                    # verschachtelt
        {"json": {"parameters": {"webhook": {"url": "http://localhost/hook"}}}},   # Job-Parameter
        {"query_string": {"callback_url": "http://192.168.1.1/"}, "json": {}},
    ],
)
def test_callback_url_wird_beim_annehmen_mit_400_abgelehnt(client: Any, kwargs: Dict[str, Any]) -> None:
    response = client.post("/api/transformer/template", headers=AUTH, **kwargs)
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "SSRF_BLOCKED"
    assert body["status"] == "error"


def test_oeffentliche_und_freigegebene_callback_url_laufen_durch(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Die Anfrage scheitert danach fachlich (kein Text), aber nicht am SSRF-Schutz
    r1 = client.post("/api/media/resolve", headers=AUTH, json={"callback_url": "https://ks.example.org/hook"})
    assert r1.get_json()["error"]["code"] == "MISSING_URL"
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "localhost")
    r2 = client.post("/api/media/resolve", headers=AUTH, json={"callback_url": "http://localhost:3000/hook"})
    assert r2.get_json()["error"]["code"] == "MISSING_URL"


def test_media_route_meldet_ssrf_blocked(client: Any) -> None:
    response = client.post("/api/media/resolve", headers=AUTH, json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "SSRF_BLOCKED"


# ------------------------------------------------------------------------------------- yt-dlp

class _FakeResponse:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_ytdlp_prueft_jede_abgerufene_adresse(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_dlp
    from yt_dlp.networking import Request

    opened: List[str] = []
    responses: Dict[str, _FakeResponse] = {}

    def fake_urlopen(self: Any, req: Any) -> Any:
        url = req if isinstance(req, str) else req.url
        opened.append(url)
        final = "http://127.0.0.1:27017/" if "weiter" in url else url
        responses[url] = _FakeResponse(final)
        return responses[url]

    monkeypatch.setattr(yt_dlp.YoutubeDL, "urlopen", fake_urlopen)
    ydl = ssrf.GuardedYoutubeDL({"quiet": True})
    try:
        # öffentliche Adresse: wird abgerufen
        assert ydl.urlopen(Request("https://example.org/video")).url == "https://example.org/video"
        # interne Adresse: wird gar nicht erst abgerufen
        with pytest.raises(SsrfBlocked):
            ydl.urlopen(Request("http://192.168.0.10/player"))
        with pytest.raises(SsrfBlocked):
            ydl.urlopen("http://localhost:11434/")
        assert opened == ["https://example.org/video"]
        # Weiterleitung auf internes Ziel: Antwort wird verworfen
        with pytest.raises(SsrfBlocked):
            ydl.urlopen(Request("https://example.org/weiter"))
        assert responses["https://example.org/weiter"].closed is True
    finally:
        ydl.close()


def test_ytdlp_prueft_adressen_fuer_externe_downloader(monkeypatch: pytest.MonkeyPatch) -> None:
    import yt_dlp

    called: List[Any] = []
    monkeypatch.setattr(yt_dlp.YoutubeDL, "dl", lambda self, name, info, subtitle=False, test=False: called.append(info) or True)
    ydl = ssrf.GuardedYoutubeDL({"quiet": True})
    try:
        assert ydl.dl("a.mp4", {"url": "https://cdn.example.org/a.m3u8"}) is True
        with pytest.raises(SsrfBlocked):
            ydl.dl("a.mp4", {"url": "http://10.0.0.9/stream.m3u8"})
        with pytest.raises(SsrfBlocked):
            ydl.dl("a.mp4", {"requested_formats": [{"url": "https://cdn.example.org/v"}, {"url": "http://127.0.0.1/a"}]})
        assert len(called) == 1
    finally:
        ydl.close()


# ------------------------------------------------------------ statisch: keine ungeschützten Stellen

def test_request_adressen_gehen_nicht_an_ungeschuetzte_aufrufe() -> None:
    """
    Stellen, die Adressen aus Requests abrufen oder Webhooks senden, dürfen weder requests.get/post
    direkt noch yt_dlp.YoutubeDL ohne Prüfung verwenden.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src"
    findings: List[str] = []
    webhook_files = list((root / "core" / "processing" / "handlers").glob("*.py")) + [
        root / "core" / "mongodb" / "secretary_worker_manager.py",
        root / "utils" / "metrics_trace.py",
    ]
    for path in webhook_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\brequests\.(post|get|put|request)\(", line) and not line.strip().startswith(("#", '"', "requests.post für")):
                findings.append(f"{path.name}:{number}: {line.strip()}")
    ytdlp_files = [root / "api" / "routes" / "media_routes.py", root / "processors" / "video_processor.py", root / "processors" / "youtube_processor.py"]
    fetch_files = [
        root / "processors" / "booklet" / "images.py",
        root / "processors" / "session_processor.py",
        root / "processors" / "transformer_processor.py",
        root / "processors" / "audio_processor.py",
        root / "processors" / "imageocr_processor.py",
        root / "api" / "routes" / "image_analyzer_routes.py",
    ]
    for path in ytdlp_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "yt_dlp.YoutubeDL(" in line:
                findings.append(f"{path.name}:{number}: {line.strip()}")
    for path in fetch_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\brequests\.(get|head|post)\(", line):
                findings.append(f"{path.name}:{number}: {line.strip()}")
    assert not findings, "Ungeschützte Abrufe:\n" + "\n".join(findings)


# ------------------------------------------------- HTTPS: geprüfte IP, Zertifikat gegen Hostname

def test_https_verbindet_gepruefte_ip_und_prueft_zertifikat_gegen_hostname(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Die Verbindung geht an die geprüfte IP, SNI und Zertifikatsprüfung laufen aber gegen den
    Hostnamen: ein Zertifikat für tls.example wird akzeptiert, für einen anderen Namen abgelehnt.
    """
    import datetime
    import ssl

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tls.example")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("tls.example")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))

    _Handler.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_file), str(key_file))
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(proxy, raising=False)
        conftest.FAKE_DNS["tls.example"] = ["127.0.0.1"]
        conftest.FAKE_DNS["anderer-name.example"] = ["127.0.0.1"]
        monkeypatch.setenv("FETCH_ALLOWED_HOSTS", "tls.example,anderer-name.example")

        response = ssrf.get(f"https://tls.example:{port}/x", timeout=5, verify=str(cert_file))
        assert response.content == b"geheim-intern"
        with pytest.raises(requests.exceptions.SSLError):
            ssrf.get(f"https://anderer-name.example:{port}/x", timeout=5, verify=str(cert_file))
    finally:
        httpd.shutdown()
