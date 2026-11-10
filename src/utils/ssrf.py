"""
@fileoverview SSRF-Schutz: Abrufe und Webhooks nur zu öffentlichen Zielen

@description
Arbeitspaket AP-12 aus docs/sicherheitsplan-umsetzung.md (Befund H1).

Der Dienst ruft Adressen ab, die ein Aufrufer mitgibt (Dateien, Webseiten, Medien) und schickt
Ergebnisse an mitgegebene Callback-Adressen. Ohne Prüfung ließe er sich so auf interne Ziele
lenken: den eigenen Rechner, andere Container, das private Netz, die Metadaten-Adresse eines
Cloud-Anbieters.

Regel: Erlaubt sind nur ``http`` und ``https`` zu Hosts, deren **sämtliche** aufgelösten Adressen
öffentlich sind. Ausnahmen je Installation über Umgebungsvariablen:

- ``FETCH_ALLOWED_HOSTS``   – Hosts, von denen trotz interner Adresse geladen werden darf
- ``WEBHOOK_ALLOWED_HOSTS`` – Hosts, an die trotz interner Adresse Webhooks gehen dürfen

Beide sind kommagetrennte Listen von Hostnamen oder IP-Adressen, ``*`` als Platzhalter ist
erlaubt (``*.intern.example``). Leer bedeutet: nur öffentliche Ziele.

Zwei Prüfstellen greifen ineinander:

1. ``check_url`` vor dem Abruf: verständlicher Fehler, bevor eine Verbindung entsteht.
2. Die Verbindung selbst (``guarded_session``): Der Host wird beim Verbindungsaufbau aufgelöst,
   geprüft und genau die geprüfte Adresse wird verbunden. Das gilt für jede Weiterleitung erneut
   und verhindert, dass ein Name zwischen Prüfung und Abruf auf eine interne Adresse umspringt
   (DNS-Rebinding). Läuft der Abruf über einen ausgehenden Proxy, löst der Proxy den Namen auf;
   dann bleibt Prüfstelle 1, die vor jedem Abruf und jeder Weiterleitung läuft.

@exports
- SsrfBlocked: Ausnahme, Fehlercode ``SSRF_BLOCKED``
- check_url, is_url_allowed: Prüfung einer Adresse
- guarded_session: requests-Sitzung mit beiden Prüfstellen
- get, head, post: wie ``requests.get/head/post`` über eine geschützte Sitzung (Zweck „fetch“)
- post_webhook: wie ``requests.post`` für Callback-Adressen (Zweck „webhook“)
- GuardedYoutubeDL: yt-dlp, das jede abgerufene Adresse prüft
"""
from __future__ import annotations

import fnmatch
import ipaddress
import os
import socket
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from src.core.security import tls_verify

SSRF_BLOCKED = "SSRF_BLOCKED"
MAX_REDIRECTS = 5

PURPOSE_FETCH = "fetch"
PURPOSE_WEBHOOK = "webhook"
_ENV_BY_PURPOSE = {
    PURPOSE_FETCH: "FETCH_ALLOWED_HOSTS",
    PURPOSE_WEBHOOK: "WEBHOOK_ALLOWED_HOSTS",
}

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

# Bereiche, die ``ipaddress.is_global`` je nach Python-Version nicht sicher als intern einstuft.
_EXTRA_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",        # „dieses Netz“
        "100.64.0.0/10",    # Carrier-Grade-NAT
        "169.254.0.0/16",   # Link-Local inkl. Cloud-Metadaten 169.254.169.254
        "192.0.0.0/24",     # IETF-Protokollzuweisungen
        "198.18.0.0/15",    # Benchmark-Netze
        "224.0.0.0/4",      # Multicast
        "240.0.0.0/4",      # reserviert
        "fd00:ec2::/32",    # AWS-Metadaten über IPv6
        "64:ff9b::/96",     # NAT64, bildet IPv4-Adressen ab
        "ff00::/8",         # Multicast
    )
)


class SsrfBlocked(ValueError):
    """Das Ziel einer Adresse ist nicht erlaubt (internes Netz, falsches Schema, nicht auflösbar)."""

    code = SSRF_BLOCKED

    def __init__(self, message: str, url: Optional[str] = None) -> None:
        super().__init__(message)
        self.url = url
        self.details: Dict[str, Any] = {"error_code": SSRF_BLOCKED}


# --------------------------------------------------------------------------- Konfiguration

def allowed_hosts(purpose: str) -> List[str]:
    """Liest die Ausnahmeliste für einen Zweck aus der Umgebung (klein geschrieben, ohne Leerwerte)."""
    raw = os.getenv(_ENV_BY_PURPOSE.get(purpose, ""), "") if purpose in _ENV_BY_PURPOSE else ""
    return [entry.strip().lower().rstrip(".") for entry in raw.split(",") if entry.strip()]


def _host_is_allowlisted(host: str, purpose: str) -> bool:
    host = host.lower().rstrip(".")
    return any(fnmatch.fnmatchcase(host, pattern) for pattern in allowed_hosts(purpose))


# ------------------------------------------------------------------------------ IP-Prüfung

def _unwrap(ip: IPAddress) -> IPAddress:
    """IPv4-Adressen, die in IPv6 eingebettet sind, als IPv4 beurteilen."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip.sixtofour is not None:
            return ip.sixtofour
    return ip


def is_public_ip(value: Union[str, IPAddress]) -> bool:
    """True nur für Adressen im öffentlichen Internet."""
    try:
        ip = _unwrap(ipaddress.ip_address(value) if isinstance(value, str) else value)
    except ValueError:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    return not any(ip.version == net.version and ip in net for net in _EXTRA_BLOCKED_NETWORKS)


def _getaddrinfo(host: str, port: int) -> List[Any]:
    """Eigene Funktion, damit Tests die Namensauflösung ersetzen können."""
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _resolve(host: str, port: int) -> List[str]:
    """Löst einen Host auf; IP-Literale (auch 127.1, 0x7f.0.0.1, dezimal) gehen denselben Weg."""
    try:
        infos = _getaddrinfo(host, port)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise SsrfBlocked(f"Host nicht auflösbar: {host}") from exc
    addresses: List[str] = []
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]  # Zonenkennung bei fe80::…%eth0 abtrennen
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise SsrfBlocked(f"Host nicht auflösbar: {host}")
    return addresses


def _checked_addresses(host: str, port: int, purpose: str) -> List[str]:
    """Liefert die Adressen eines Hosts oder wirft SsrfBlocked, wenn eine davon intern ist."""
    addresses = _resolve(host, port)
    if _host_is_allowlisted(host, purpose):
        return addresses
    blocked = [address for address in addresses if not is_public_ip(address)]
    if blocked:
        # Schon EINE interne Adresse genügt: sonst entscheidet die Reihenfolge der DNS-Antwort.
        raise SsrfBlocked(
            f"Ziel nicht erlaubt: {host} zeigt auf eine interne oder reservierte Adresse. "
            f"Ausnahmen je Installation über {_ENV_BY_PURPOSE.get(purpose, 'FETCH_ALLOWED_HOSTS')}."
        )
    return addresses


def _split(url: str) -> Tuple[str, str, int]:
    if not isinstance(url, str) or not url.strip():
        raise SsrfBlocked("Adresse fehlt")
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname or ""
        port = parts.port
    except ValueError as exc:
        raise SsrfBlocked("Adresse ist ungültig") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SsrfBlocked("Nur Adressen mit http oder https sind erlaubt")
    if not host:
        raise SsrfBlocked("Adresse ohne Host")
    return scheme, host, port or (443 if scheme == "https" else 80)


def check_url(url: str, purpose: str = PURPOSE_FETCH) -> List[str]:
    """
    Prüft eine Adresse und liefert die aufgelösten, erlaubten IP-Adressen.

    Raises:
        SsrfBlocked: falsches Schema, kein Host, nicht auflösbar oder internes Ziel.
    """
    _scheme, host, port = _split(url)
    try:
        return _checked_addresses(host, port, purpose)
    except SsrfBlocked as exc:
        exc.url = url
        raise


def is_url_allowed(url: str, purpose: str = PURPOSE_FETCH) -> bool:
    try:
        check_url(url, purpose)
        return True
    except SsrfBlocked:
        return False


# ------------------------------------------------------------------- Verbindung mit Prüfung

def _guarded_new_conn(conn: Any, parent_new_conn: Any, purpose: str) -> socket.socket:
    """
    Löst den Host beim Verbindungsaufbau auf, prüft ihn und verbindet genau die geprüfte Adresse.
    TLS (SNI, Zertifikatsprüfung) läuft danach weiter gegen den Hostnamen.
    """
    if getattr(conn, "proxy", None) is not None:
        # Verbindung zum ausgehenden Proxy: das Ziel löst der Proxy auf. Die Adresse selbst
        # wurde in GuardedAdapter.send geprüft.
        return parent_new_conn()
    original = conn._dns_host
    addresses = _checked_addresses(original, conn.port, purpose)
    conn._dns_host = addresses[0]
    try:
        return parent_new_conn()
    finally:
        conn._dns_host = original


def _connection_classes(purpose: str) -> Tuple[type, type]:
    class GuardedHTTPConnection(HTTPConnection):
        def _new_conn(self) -> socket.socket:
            return _guarded_new_conn(self, super()._new_conn, purpose)

    class GuardedHTTPSConnection(HTTPSConnection):
        def _new_conn(self) -> socket.socket:
            return _guarded_new_conn(self, super()._new_conn, purpose)

    class GuardedHTTPPool(HTTPConnectionPool):
        ConnectionCls = GuardedHTTPConnection

    class GuardedHTTPSPool(HTTPSConnectionPool):
        ConnectionCls = GuardedHTTPSConnection

    return GuardedHTTPPool, GuardedHTTPSPool


class GuardedAdapter(HTTPAdapter):
    """Transport für requests: prüft jede Anfrage (auch jede Weiterleitung) und jede Verbindung."""

    def __init__(self, purpose: str = PURPOSE_FETCH, **kwargs: Any) -> None:
        self._purpose = purpose
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        http_pool, https_pool = _connection_classes(self._purpose)
        self.poolmanager.pool_classes_by_scheme = {"http": http_pool, "https": https_pool}

    def send(self, request: requests.PreparedRequest, *args: Any, **kwargs: Any) -> requests.Response:
        check_url(str(request.url or ""), self._purpose)
        return super().send(request, *args, **kwargs)


def guarded_session(purpose: str = PURPOSE_FETCH) -> requests.Session:
    """requests-Sitzung, die nur erlaubte Ziele erreicht. Höchstens ``MAX_REDIRECTS`` Weiterleitungen."""
    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    adapter = GuardedAdapter(purpose)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def request(method: str, url: str, purpose: str = PURPOSE_FETCH, **kwargs: Any) -> requests.Response:
    """
    Wie ``requests.request``, aber nur zu erlaubten Zielen. ``verify`` folgt ohne Angabe der
    TLS-Regel des Dienstes. Bei ``stream=True`` bleibt die Verbindung bis ``Response.close()`` offen.
    """
    check_url(url, purpose)
    kwargs.setdefault("verify", tls_verify())
    session = guarded_session(purpose)
    try:
        response = session.request(method, url, **kwargs)
    except BaseException:
        session.close()
        raise
    if kwargs.get("stream"):
        original_close = response.close

        def _close() -> None:
            try:
                original_close()
            finally:
                session.close()

        response.close = _close  # type: ignore[method-assign]
    else:
        session.close()
    return response


def get(url: str, **kwargs: Any) -> requests.Response:
    return request("GET", url, PURPOSE_FETCH, **kwargs)


def head(url: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("allow_redirects", False)
    return request("HEAD", url, PURPOSE_FETCH, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    return request("POST", url, PURPOSE_FETCH, **kwargs)


def post_webhook(url: str, **kwargs: Any) -> requests.Response:
    """Wie ``requests.post`` für Callback-Adressen von Aufrufern (Ausnahmen: WEBHOOK_ALLOWED_HOSTS)."""
    return request("POST", url, PURPOSE_WEBHOOK, **kwargs)


def check_callback_url(url: Optional[str]) -> None:
    """Prüft eine Callback-Adresse beim Anlegen eines Jobs. Leer ist erlaubt (kein Webhook)."""
    if url is None or not str(url).strip():
        return
    check_url(str(url), PURPOSE_WEBHOOK)


# ----------------------------------------------------------------------------------- yt-dlp

def _guarded_youtube_dl_class() -> type:
    import yt_dlp  # type: ignore

    class _GuardedYoutubeDL(yt_dlp.YoutubeDL):  # type: ignore[misc]
        """
        yt-dlp, das jede Adresse prüft, die es selbst abruft: die Seite, eingebettete Player,
        Manifeste, Fragmente und Mediendateien. Endet eine Weiterleitung auf einem internen Ziel,
        wird die Antwort verworfen. Adressen, die yt-dlp an ffmpeg übergibt, werden vor dem
        Download geprüft.
        """

        def urlopen(self, req: Any) -> Any:
            url = req if isinstance(req, str) else getattr(req, "url", None)
            if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                check_url(url, PURPOSE_FETCH)
            response = super().urlopen(req)
            final_url = getattr(response, "url", None)
            if isinstance(final_url, str) and final_url != url and final_url.lower().startswith(("http://", "https://")):
                try:
                    check_url(final_url, PURPOSE_FETCH)
                except SsrfBlocked:
                    try:
                        response.close()
                    except Exception:
                        pass
                    raise
            return response

        def dl(self, name: Any, info: Any, subtitle: bool = False, test: bool = False) -> Any:
            for candidate in _media_urls(info):
                check_url(candidate, PURPOSE_FETCH)
            return super().dl(name, info, subtitle, test)

    return _GuardedYoutubeDL


def _media_urls(info: Any) -> List[str]:
    """Adressen eines Formats, die ein Downloader (auch ffmpeg) direkt abruft."""
    urls: List[str] = []
    if not isinstance(info, dict):
        return urls
    for key in ("url", "manifest_url", "fragment_base_url"):
        value = info.get(key)
        if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
            urls.append(value)
    for sub in info.get("requested_formats") or []:
        urls.extend(_media_urls(sub))
    return urls


def GuardedYoutubeDL(*args: Any, **kwargs: Any) -> Any:
    """Erzeugt ein yt-dlp-Objekt mit SSRF-Prüfung (Ersatz für ``yt_dlp.YoutubeDL(...)``)."""
    return _guarded_youtube_dl_class()(*args, **kwargs)
